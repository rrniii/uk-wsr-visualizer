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
  prelabelStatus: document.getElementById("prelabelStatus"),
  prelabelSummary: document.getElementById("prelabelSummary"),
  prelabelEvidence: document.getElementById("prelabelEvidence"),
  acceptPrelabel: document.getElementById("acceptPrelabel"),
  editPrelabel: document.getElementById("editPrelabel"),
  brushTool: document.getElementById("brushTool"),
  polygonTool: document.getElementById("polygonTool"),
  brushControls: document.getElementById("brushControls"),
  brushSize: document.getElementById("brushSize"),
  brushSizeValue: document.getElementById("brushSizeValue"),
  eraserMode: document.getElementById("eraserMode"),
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
  dbzhColourbar: document.getElementById("dbzhColourbar"),
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
let brushGates = new Set();
let selectionTool = "brush";
let painting = false;
let prelabelDecision = "manual";

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
  setSelectionTool("brush");
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
  ui.canvas.addEventListener("pointerdown", startCanvasSelection);
  ui.canvas.addEventListener("pointermove", continueCanvasSelection);
  ui.canvas.addEventListener("pointerup", stopCanvasSelection);
  ui.canvas.addEventListener("pointercancel", stopCanvasSelection);
  ui.brushTool.addEventListener("click", () => setSelectionTool("brush"));
  ui.polygonTool.addEventListener("click", () => setSelectionTool("polygon"));
  ui.brushSize.addEventListener("input", () => {
    ui.brushSizeValue.value = `${ui.brushSize.value} px`;
  });
  ui.acceptPrelabel.addEventListener("click", acceptPrelabel);
  ui.editPrelabel.addEventListener("click", editPrelabel);
  ui.undoVertex.addEventListener("click", () => {
    if (selectionTool === "brush") brushGates.clear();
    else draftVertices.pop();
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
    brushGates.clear();
    prelabelDecision = target.annotation?.prelabel_decision || "manual";
    ui.reviewNotes.value = target.annotation?.notes || "";
    renderTargetSummary(summary);
    renderPrelabel();
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
  ui.dbzhColourbar.replaceChildren(makeColourbar(dbzh));
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
      scale.textContent = field.quantity;
      const image = document.createElement("img");
      image.src = field.image_url;
      image.alt = `Raw ${field.label || field.quantity} polar sweep`;
      image.loading = "lazy";
      header.append(name, scale);
      panel.append(header, image, makeColourbar(field));
      ui.fieldGallery.appendChild(panel);
    });
}

function startCanvasSelection(event) {
  if (!target || !baseImage) return;
  if (selectionTool === "brush") {
    painting = true;
    ui.canvas.setPointerCapture(event.pointerId);
    paintBrush(event);
    return;
  }
  addDraftVertex(event);
}

function continueCanvasSelection(event) {
  if (painting && selectionTool === "brush") paintBrush(event);
}

function stopCanvasSelection(event) {
  if (!painting) return;
  painting = false;
  if (ui.canvas.hasPointerCapture(event.pointerId)) {
    ui.canvas.releasePointerCapture(event.pointerId);
  }
}

function addDraftVertex(event) {
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

function paintBrush(event) {
  const [x, y] = eventCanvasPoint(event);
  const radius = Number(ui.brushSize.value)
    * (ui.canvas.width / ui.canvas.getBoundingClientRect().width);
  const erase = ui.eraserMode.checked;
  const step = Math.max(2, Math.floor(radius / 8));
  for (let dx = -radius; dx <= radius; dx += step) {
    const height = Math.sqrt(Math.max(0, radius * radius - dx * dx));
    for (let dy = -height; dy <= height; dy += step) {
      const gate = canvasToGate(x + dx, y + dy);
      if (!gate) continue;
      const [ray, bin] = gate;
      for (let dr = -1; dr <= 1; dr += 1) {
        const wrappedRay = (ray + dr + target.shape[0]) % target.shape[0];
        const offset = wrappedRay * target.shape[1] + bin;
        if (erase) brushGates.delete(offset);
        else brushGates.add(offset);
      }
    }
  }
  prelabelDecision = prelabelDecision === "accepted" ? "edited" : prelabelDecision;
  drawCanvas();
}

function eventCanvasPoint(event) {
  const rect = ui.canvas.getBoundingClientRect();
  return [
    (event.clientX - rect.left) * (ui.canvas.width / rect.width),
    (event.clientY - rect.top) * (ui.canvas.height / rect.height),
  ];
}

function canvasToGate(x, y) {
  const centre = (ui.canvas.width - 1) / 2;
  const dx = x - centre;
  const dy = y - centre;
  const radial = Math.sqrt(dx * dx + dy * dy);
  if (radial > centre) return null;
  const azimuth = (Math.atan2(dx, -dy) + Math.PI * 2) % (Math.PI * 2);
  return [
    Math.min(target.shape[0] - 1, Math.floor(azimuth / (Math.PI * 2) * target.shape[0])),
    Math.min(target.shape[1] - 1, Math.floor(radial / centre * target.shape[1])),
  ];
}

function drawCanvas() {
  context.clearRect(0, 0, ui.canvas.width, ui.canvas.height);
  if (baseImage) {
    context.drawImage(baseImage, 0, 0, ui.canvas.width, ui.canvas.height);
  }
  regions.forEach((region) => drawRegion(region));
  if (brushGates.size) {
    drawRleGeometry(
      { type: "row_major_rle", runs: offsetsToRuns([...brushGates]) },
      actionColors[review.taxonomy[ui.labelSelect.value].action],
      0.34,
    );
  }
  if (draftVertices.length) {
    drawPolarPolygon(draftVertices, "#ffffff", false, true);
  }
  ui.draftStatus.textContent = selectionTool === "brush"
    ? `${brushGates.size} painted gates`
    : `${draftVertices.length} point${draftVertices.length === 1 ? "" : "s"}`;
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
    return;
  }
  if (region.geometry.type === "row_major_rle") {
    drawRleGeometry(region.geometry, color, 0.24);
  }
}

function drawRleGeometry(geometry, color, alpha) {
  context.save();
  context.fillStyle = colorWithAlpha(color, alpha);
  geometry.runs.forEach(([offset, length]) => {
    let cursor = offset;
    let remaining = length;
    while (remaining > 0) {
      const ray = Math.floor(cursor / target.shape[1]);
      const gate = cursor % target.shape[1];
      const span = Math.min(remaining, target.shape[1] - gate);
      const vertices = [
        polarToCanvas([ray, gate]),
        polarToCanvas([ray + 1, gate]),
        polarToCanvas([ray + 1, gate + span]),
        polarToCanvas([ray, gate + span]),
      ];
      context.beginPath();
      vertices.forEach(([x, y], index) => {
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      context.closePath();
      context.fill();
      cursor += span;
      remaining -= span;
    }
  });
  context.restore();
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
  if (selectionTool === "brush") {
    addBrushRegion();
    return;
  }
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

function addBrushRegion() {
  if (!brushGates.size) {
    showStatus("Paint at least one gate", true);
    return;
  }
  regions.push(newRegion({
    type: "row_major_rle",
    runs: offsetsToRuns([...brushGates]),
  }));
  brushGates.clear();
  ui.regionNotes.value = "";
  prelabelDecision = prelabelDecision === "manual" ? "manual" : "edited";
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

function setSelectionTool(tool) {
  selectionTool = tool;
  const brushing = tool === "brush";
  ui.brushTool.classList.toggle("active", brushing);
  ui.brushTool.setAttribute("aria-pressed", String(brushing));
  ui.polygonTool.classList.toggle("active", !brushing);
  ui.polygonTool.setAttribute("aria-pressed", String(!brushing));
  ui.brushControls.hidden = !brushing;
  ui.addPolygon.textContent = brushing ? "Add painted selection" : "Add region";
  ui.canvas.classList.toggle("brush-cursor", brushing);
  drawCanvas();
}

function renderPrelabel() {
  const proposal = target.prelabel;
  if (!proposal) {
    ui.prelabelSummary.textContent = "No prelabel is available.";
    ui.prelabelEvidence.replaceChildren();
    ui.acceptPrelabel.disabled = true;
    ui.editPrelabel.disabled = true;
    return;
  }
  const summary = proposal.summary;
  ui.prelabelSummary.textContent = `${summary.classified_percent}% of valid gates have a high-confidence proposal; uncertain gates remain unlabelled.`;
  ui.prelabelEvidence.replaceChildren();
  Object.entries(summary.class_counts)
    .filter(([, count]) => count > 0)
    .sort((left, right) => right[1] - left[1])
    .forEach(([label, count]) => {
      const row = document.createElement("div");
      const name = document.createElement("span");
      name.textContent = titleCase(label);
      const value = document.createElement("strong");
      value.textContent = Number(count).toLocaleString();
      row.append(name, value);
      ui.prelabelEvidence.appendChild(row);
    });
  ui.prelabelStatus.textContent = titleCase(prelabelDecision === "manual" ? "proposal" : prelabelDecision);
  ui.prelabelStatus.className = `proposal-badge ${prelabelDecision}`;
  ui.acceptPrelabel.disabled = !proposal.regions.length;
  ui.editPrelabel.disabled = !proposal.regions.length;
}

function acceptPrelabel() {
  regions = structuredClone(target.prelabel.regions);
  brushGates.clear();
  draftVertices = [];
  prelabelDecision = "accepted";
  renderPrelabel();
  renderRegionList();
  drawCanvas();
  showStatus("Fuzzy proposal accepted. Save to record your confirmation.");
}

function editPrelabel() {
  regions = structuredClone(target.prelabel.regions);
  brushGates.clear();
  draftVertices = [];
  prelabelDecision = "edited";
  setSelectionTool("brush");
  renderPrelabel();
  renderRegionList();
  drawCanvas();
  showStatus("Proposal loaded. Delete labels or paint corrections, then save.");
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
          prelabel_decision: prelabelDecision,
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
  if (geometry.type === "row_major_rle") {
    const gates = geometry.runs.reduce((total, run) => total + run[1], 0);
    return `${gates.toLocaleString()} painted gates`;
  }
  return geometry.type;
}

function makeColourbar(field) {
  const wrapper = document.createElement("div");
  wrapper.className = "colourbar";
  const bar = document.createElement("div");
  bar.className = "colourbar-ramp";
  bar.style.background = `linear-gradient(90deg, ${field.palette_stops
    .map(([position, color]) => `${color} ${position * 100}%`)
    .join(", ")})`;
  const labels = document.createElement("div");
  labels.className = "colourbar-labels";
  const minimum = document.createElement("span");
  minimum.textContent = formatScale(field.scale_min, field.quantity);
  const midpoint = document.createElement("span");
  midpoint.textContent = formatScale((field.scale_min + field.scale_max) / 2, field.quantity);
  const maximum = document.createElement("span");
  maximum.textContent = formatScale(field.scale_max, field.quantity);
  labels.append(minimum, midpoint, maximum);
  wrapper.append(bar, labels);
  return wrapper;
}

function formatScale(value, quantity) {
  const units = {
    DBZH: "dBZ",
    VRADH: "m/s",
    ZDR: "dB",
    PHIDP: "deg",
    WRADH: "m/s",
  };
  const digits = Math.abs(value) < 2 ? 1 : 0;
  return `${Number(value).toFixed(digits)}${units[quantity] ? ` ${units[quantity]}` : ""}`;
}

function offsetsToRuns(rawOffsets) {
  const offsets = [...new Set(rawOffsets)].sort((left, right) => left - right);
  if (!offsets.length) return [];
  const runs = [];
  let start = offsets[0];
  let previous = start;
  for (let index = 1; index < offsets.length; index += 1) {
    const current = offsets[index];
    if (current !== previous + 1) {
      runs.push([start, previous - start + 1]);
      start = current;
    }
    previous = current;
  }
  runs.push([start, previous - start + 1]);
  return runs;
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
