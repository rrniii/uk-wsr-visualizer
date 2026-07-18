"use strict";

const ui = {
  reviewIdentity: document.getElementById("reviewIdentity"),
  progressLabel: document.getElementById("progressLabel"),
  progressBar: document.getElementById("progressBar"),
  previousTarget: document.getElementById("previousTarget"),
  nextTarget: document.getElementById("nextTarget"),
  completionMarker: document.getElementById("completionMarker"),
  targetPosition: document.getElementById("targetPosition"),
  targetTitle: document.getElementById("targetTitle"),
  targetMetadata: document.getElementById("targetMetadata"),
  labelSelect: document.getElementById("labelSelect"),
  actionBadge: document.getElementById("actionBadge"),
  classificationDescription: document.getElementById("classificationDescription"),
  confidenceInput: document.getElementById("confidenceInput"),
  confidenceValue: document.getElementById("confidenceValue"),
  regionNotes: document.getElementById("regionNotes"),
  undoVertex: document.getElementById("undoVertex"),
  addPolygon: document.getElementById("addPolygon"),
  addFullSweep: document.getElementById("addFullSweep"),
  regionCount: document.getElementById("regionCount"),
  regionList: document.getElementById("regionList"),
  reviewNotes: document.getElementById("reviewNotes"),
  saveTarget: document.getElementById("saveTarget"),
  statusMessage: document.getElementById("statusMessage"),
  dbzhScale: document.getElementById("dbzhScale"),
  draftStatus: document.getElementById("draftStatus"),
  canvas: document.getElementById("annotationCanvas"),
  fieldGallery: document.getElementById("fieldGallery"),
};

const context = ui.canvas.getContext("2d");
const actionColors = {
  remove: "#ef706b",
  retain: "#61c681",
  ignore: "#e8b854",
};

let review = null;
let target = null;
let targetIndex = 0;
let baseImage = null;
let regions = [];
let draftVertices = [];

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_error) {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function boot() {
  bindEvents();
  try {
    review = await requestJson("/api/review");
    ui.reviewIdentity.textContent = `${review.reviewer} · ${review.stage}`;
    buildTaxonomy();
    const firstOpen = review.targets.findIndex((item) => !item.completed);
    targetIndex = firstOpen >= 0 ? firstOpen : 0;
    await loadTarget(targetIndex);
  } catch (error) {
    showStatus(error.message, true);
  }
}

function bindEvents() {
  ui.previousTarget.addEventListener("click", () => loadTarget(targetIndex - 1));
  ui.nextTarget.addEventListener("click", () => loadTarget(targetIndex + 1));
  ui.labelSelect.addEventListener("change", updateClassification);
  ui.confidenceInput.addEventListener("input", () => {
    ui.confidenceValue.value = Number(ui.confidenceInput.value).toFixed(2);
  });
  ui.canvas.addEventListener("pointerdown", addDraftVertex);
  ui.undoVertex.addEventListener("click", () => {
    draftVertices.pop();
    drawCanvas();
  });
  ui.addPolygon.addEventListener("click", addPolygonRegion);
  ui.addFullSweep.addEventListener("click", addFullSweepRegion);
  ui.saveTarget.addEventListener("click", saveTarget);
}

function buildTaxonomy() {
  const families = {};
  Object.entries(review.taxonomy).forEach(([label, definition]) => {
    const family = definition.family || "other";
    families[family] = families[family] || [];
    families[family].push([label, definition]);
  });
  ui.labelSelect.replaceChildren();
  Object.entries(families).forEach(([family, entries]) => {
    const group = document.createElement("optgroup");
    group.label = titleCase(family);
    entries.forEach(([label]) => {
      const option = document.createElement("option");
      option.value = label;
      option.textContent = titleCase(label);
      group.appendChild(option);
    });
    ui.labelSelect.appendChild(group);
  });
  ui.labelSelect.value = "receiver_noise";
  updateClassification();
}

async function loadTarget(index) {
  if (!review || !review.targets.length) return;
  targetIndex = Math.max(0, Math.min(index, review.targets.length - 1));
  const summary = review.targets[targetIndex];
  showStatus("Loading raw fields");
  try {
    target = await requestJson(`/api/targets/${encodeURIComponent(summary.target_id)}`);
    regions = structuredClone(target.annotation?.regions || []);
    draftVertices = [];
    ui.reviewNotes.value = target.annotation?.notes || "";
    renderTargetSummary(summary);
    renderGallery();
    await loadBaseImage();
    renderRegionList();
    updateProgress();
    showStatus("");
  } catch (error) {
    showStatus(error.message, true);
  }
}

function renderTargetSummary(summary) {
  ui.targetPosition.textContent = `Target ${targetIndex + 1} of ${review.targets.length}`;
  ui.targetTitle.textContent = `${target.radar} · ${target.date} ${target.time}`;
  ui.completionMarker.classList.toggle("complete", summary.completed);
  ui.targetMetadata.replaceChildren();
  const values = [
    ["Pulse", target.pulse.toUpperCase()],
    ["Sweep", `${target.dataset} · ${formatNumber(target.elevation_deg, 2)} deg`],
    ["Shape", `${target.shape[0]} rays × ${target.shape[1]} gates`],
    ["Split", target.split],
    ["Season", target.season],
    ["UTC slot", titleCase(target.utc_slot)],
    ["Selection", titleCase(target.selection_role)],
  ];
  values.forEach(([key, value]) => {
    const term = document.createElement("dt");
    term.textContent = key;
    const description = document.createElement("dd");
    description.textContent = value;
    ui.targetMetadata.append(term, description);
  });
  ui.previousTarget.disabled = targetIndex === 0;
  ui.nextTarget.disabled = targetIndex === review.targets.length - 1;
}

async function loadBaseImage() {
  const dbzh = target.visible_fields.find((field) => field.annotation_primary)
    || target.visible_fields.find((field) => field.quantity === "DBZH");
  ui.dbzhScale.textContent = `${dbzh.scale_min} to ${dbzh.scale_max} dBZ`;
  baseImage = new Image();
  baseImage.decoding = "async";
  const loaded = new Promise((resolve, reject) => {
    baseImage.onload = resolve;
    baseImage.onerror = () => reject(new Error("Raw DBZH image failed to load"));
  });
  baseImage.src = `${dbzh.image_url}?target=${encodeURIComponent(target.target_id)}`;
  await loaded;
  drawCanvas();
}

function renderGallery() {
  ui.fieldGallery.replaceChildren();
  const primary = target.visible_fields.find((field) => field.annotation_primary)
    || target.visible_fields.find((field) => field.quantity === "DBZH");
  target.visible_fields
    .filter((field) => field !== primary)
    .forEach((field) => {
      const panel = document.createElement("article");
      panel.className = "field-panel";
      const header = document.createElement("header");
      const name = document.createElement("strong");
      name.textContent = field.label || field.quantity;
      const scale = document.createElement("span");
      scale.textContent = `${field.scale_min} to ${field.scale_max}`;
      const image = document.createElement("img");
      image.src = field.image_url;
      image.alt = `Raw ${field.label || field.quantity} polar sweep`;
      image.loading = "lazy";
      header.append(name, scale);
      panel.append(header, image);
      ui.fieldGallery.appendChild(panel);
    });
}

function addDraftVertex(event) {
  if (!target || !baseImage) return;
  const rect = ui.canvas.getBoundingClientRect();
  const x = (event.clientX - rect.left) * (ui.canvas.width / rect.width);
  const y = (event.clientY - rect.top) * (ui.canvas.height / rect.height);
  const centre = (ui.canvas.width - 1) / 2;
  const dx = x - centre;
  const dy = y - centre;
  const radial = Math.sqrt(dx * dx + dy * dy);
  if (radial > centre) return;
  const azimuth = (Math.atan2(dx, -dy) + Math.PI * 2) % (Math.PI * 2);
  const ray = (azimuth / (Math.PI * 2)) * target.shape[0];
  const gate = Math.min(
    target.shape[1] - 0.0001,
    (radial / centre) * target.shape[1],
  );
  draftVertices.push([roundCoordinate(ray), roundCoordinate(gate)]);
  drawCanvas();
}

function drawCanvas() {
  context.clearRect(0, 0, ui.canvas.width, ui.canvas.height);
  if (baseImage) {
    context.drawImage(baseImage, 0, 0, ui.canvas.width, ui.canvas.height);
  }
  regions.forEach((region) => drawRegion(region));
  if (draftVertices.length) {
    drawPolarPolygon(draftVertices, "#ffffff", false, true);
  }
  ui.draftStatus.textContent = `${draftVertices.length} point${draftVertices.length === 1 ? "" : "s"}`;
}

function drawRegion(region) {
  const color = actionColors[region.action] || "#ffffff";
  if (region.geometry.type === "full_sweep") {
    const centre = (ui.canvas.width - 1) / 2;
    context.save();
    context.beginPath();
    context.arc(centre, centre, centre - 2, 0, Math.PI * 2);
    context.fillStyle = colorWithAlpha(color, 0.12);
    context.strokeStyle = color;
    context.lineWidth = 3;
    context.fill();
    context.stroke();
    context.restore();
    return;
  }
  if (region.geometry.type === "polar_gate_polygon") {
    drawPolarPolygon(region.geometry.vertices, color, true, false);
  }
}

function drawPolarPolygon(vertices, color, fill, draft) {
  if (!vertices.length) return;
  context.save();
  context.beginPath();
  vertices.forEach((vertex, index) => {
    const [x, y] = polarToCanvas(vertex);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  if (!draft && vertices.length >= 3) context.closePath();
  context.strokeStyle = color;
  context.lineWidth = draft ? 2 : 3;
  context.setLineDash(draft ? [7, 5] : []);
  if (fill) {
    context.fillStyle = colorWithAlpha(color, 0.22);
    context.fill();
  }
  context.stroke();
  vertices.forEach((vertex) => {
    const [x, y] = polarToCanvas(vertex);
    context.beginPath();
    context.arc(x, y, 4, 0, Math.PI * 2);
    context.fillStyle = color;
    context.fill();
  });
  context.restore();
}

function polarToCanvas(vertex) {
  const centre = (ui.canvas.width - 1) / 2;
  const azimuth = (vertex[0] / target.shape[0]) * Math.PI * 2;
  const radial = (vertex[1] / target.shape[1]) * centre;
  return [
    centre + Math.sin(azimuth) * radial,
    centre - Math.cos(azimuth) * radial,
  ];
}

function addPolygonRegion() {
  if (draftVertices.length < 3) {
    showStatus("A polygon needs at least three points", true);
    return;
  }
  regions.push(newRegion({
    type: "polar_gate_polygon",
    vertices: structuredClone(draftVertices),
  }));
  draftVertices = [];
  ui.regionNotes.value = "";
  renderRegionList();
  drawCanvas();
  showStatus("");
}

function addFullSweepRegion() {
  regions.push(newRegion({ type: "full_sweep" }));
  draftVertices = [];
  ui.regionNotes.value = "";
  renderRegionList();
  drawCanvas();
}

function newRegion(geometry) {
  const label = ui.labelSelect.value;
  const definition = review.taxonomy[label];
  return {
    region_id: makeRegionId(),
    label,
    action: definition.action,
    confidence: Number(ui.confidenceInput.value),
    geometry,
    notes: ui.regionNotes.value.trim(),
  };
}

function renderRegionList() {
  ui.regionList.replaceChildren();
  ui.regionCount.textContent = String(regions.length);
  regions.forEach((region, index) => {
    const row = document.createElement("div");
    row.className = "region-row";
    const swatch = document.createElement("span");
    swatch.className = "region-color";
    swatch.style.background = actionColors[region.action];
    const text = document.createElement("div");
    const name = document.createElement("div");
    name.className = "region-name";
    name.textContent = titleCase(region.label);
    const detail = document.createElement("div");
    detail.className = "region-detail";
    detail.textContent = `${region.action} · ${region.confidence.toFixed(2)} · ${geometryName(region.geometry)}`;
    text.append(name, detail);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete";
    remove.addEventListener("click", () => {
      regions.splice(index, 1);
      renderRegionList();
      drawCanvas();
    });
    row.append(swatch, text, remove);
    ui.regionList.appendChild(row);
  });
}

async function saveTarget() {
  if (!regions.length) {
    showStatus("Add at least one labelled region", true);
    return;
  }
  ui.saveTarget.disabled = true;
  showStatus("Saving");
  try {
    await requestJson(
      `/api/targets/${encodeURIComponent(target.target_id)}/annotation`,
      {
        method: "POST",
        body: JSON.stringify({
          regions,
          notes: ui.reviewNotes.value.trim(),
        }),
      },
    );
    review.targets[targetIndex].completed = true;
    review.completed_count = review.targets.filter((item) => item.completed).length;
    updateProgress();
    if (targetIndex < review.targets.length - 1) {
      await loadTarget(targetIndex + 1);
    } else {
      renderTargetSummary(review.targets[targetIndex]);
      showStatus("Review selection complete");
    }
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    ui.saveTarget.disabled = false;
  }
}

function updateClassification() {
  if (!review) return;
  const definition = review.taxonomy[ui.labelSelect.value];
  ui.actionBadge.textContent = definition.action;
  ui.actionBadge.className = `action-badge ${definition.action}`;
  ui.classificationDescription.textContent = definition.description;
}

function updateProgress() {
  const complete = review.targets.filter((item) => item.completed).length;
  ui.progressLabel.textContent = `${complete} / ${review.targets.length}`;
  ui.progressBar.max = Math.max(1, review.targets.length);
  ui.progressBar.value = complete;
  ui.completionMarker.classList.toggle(
    "complete",
    review.targets[targetIndex].completed,
  );
}

function showStatus(message, error = false) {
  ui.statusMessage.textContent = message || "";
  ui.statusMessage.classList.toggle("error", error);
}

function geometryName(geometry) {
  if (geometry.type === "full_sweep") return "full sweep";
  if (geometry.type === "polar_gate_polygon") {
    return `${geometry.vertices.length} points`;
  }
  return geometry.type;
}

function formatNumber(value, places) {
  return value == null ? "unknown" : Number(value).toFixed(places);
}

function titleCase(value) {
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function roundCoordinate(value) {
  return Math.round(value * 10000) / 10000;
}

function colorWithAlpha(hex, alpha) {
  const red = parseInt(hex.slice(1, 3), 16);
  const green = parseInt(hex.slice(3, 5), 16);
  const blue = parseInt(hex.slice(5, 7), 16);
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function makeRegionId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return `region-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

boot();
