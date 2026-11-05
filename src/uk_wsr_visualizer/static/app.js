function currentSessionState() {
  return {
    radar: el("radarSelect").value,
    start: el("startInput").value,
    end: el("endInput").value,
    pulse: el("pulseSelect").value,
    quantity: el("quantitySelect").value,
    itemIndex: el("itemSelect").value,
    time: el("timeSelect").value,
    dataset: optionalInputValue("datasetInput"),
    opacity: el("opacityInput").value,
    palette: el("paletteSelect").value,
    customPalette: el("customPaletteInput").value,
    basemap: el("basemapSelect").value,
    filters: filterParams(),
    displayRange: {
      min: optionalInputValue("displayMinInput"),
      max: optionalInputValue("displayMaxInput"),
    },
    rangeRings: {
      enabled: el("rangeRingsInput").checked,
      spacingKm: optionalInputValue("rangeRingSpacingInput"),
    },
    panelCount: state.panelCount,
    panelSelections: state.panelSelections,
    panelDisplays: state.panelDisplays,
    pointerFields: state.pointerFields,
    comparisonLinks: state.comparisonLinks,
  };
}

async function saveSession() {
  const sessionId = el("sessionIdInput").value.trim() || "default";
  const response = await api(`/api/session/${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({title: sessionId, state: currentSessionState()}),
  });
  const data = await response.json();
  el("sessionStatus").textContent = `Saved ${data.session_id} at ${data.updated_at}`;
}

async function loadSession() {
  const sessionId = el("sessionIdInput").value.trim() || "default";
  const response = await api(`/api/session/${encodeURIComponent(sessionId)}`);
  const data = await response.json();
  await applySessionState(data.state || {});
  el("sessionStatus").textContent = `Loaded ${data.session_id} from ${data.updated_at}`;
}

async function applySessionState(saved) {
  el("radarSelect").value = saved.radar || "";
  el("startInput").value = saved.start || "";
  el("endInput").value = saved.end || "";
  el("pulseSelect").value = saved.pulse || "";
  el("quantitySelect").value = saved.quantity || DEFAULT_VARIABLE;
  setOptionalInputValue("datasetInput", saved.dataset);
  el("opacityInput").value = saved.opacity || "0.85";
  el("paletteSelect").value = saved.palette || "gray";
  el("customPaletteInput").value = saved.customPalette || "0:#000000,0.5:#28b450,1:#ffffff";
  el("basemapSelect").value = saved.basemap || "osm";
  const savedFilters = saved.filters || {};
  el("minRangeInput").value = savedFilters.min_range_km ?? "";
  el("maxRangeInput").value = savedFilters.max_range_km ?? "";
  el("minAzimuthInput").value = savedFilters.min_azimuth_deg ?? "";
  el("maxAzimuthInput").value = savedFilters.max_azimuth_deg ?? "";
  el("minValueInput").value = savedFilters.min_value ?? "";
  el("maxValueInput").value = savedFilters.max_value ?? "";
  el("cappiHeightInput").value = savedFilters.cappi_height_m ?? "";
  const cleanupEnabled = savedFilters.noise_floor_enabled;
  el("noiseFloorInput").checked = cleanupEnabled === undefined
    ? DEFAULT_CLEANUP_ENABLED
    : cleanupEnabled === true || cleanupEnabled === "true";
  el("noiseFloorMethodSelect").value = savedFilters.noise_floor_method || "estimated";
  el("noiseFloorMarginInput").value = savedFilters.noise_floor_margin_db ?? String(DEFAULT_CLEANUP_MARGIN_DB);
  el("backgroundModelPathInput").value = savedFilters.qc_background_model_path ?? "";
  el("displayMinInput").value = saved.displayRange?.min ?? "";
  el("displayMaxInput").value = saved.displayRange?.max ?? "";
  el("rangeRingsInput").checked = saved.rangeRings?.enabled !== false;
  el("rangeRingSpacingInput").value = saved.rangeRings?.spacingKm ?? "";
  if (saved.comparisonLinks && typeof saved.comparisonLinks === "object") {
    state.comparisonLinks = {
      ...state.comparisonLinks,
      ...saved.comparisonLinks,
    };
    applyComparisonLinkState();
  }
  if (Array.isArray(saved.panelSelections)) {
    state.panelSelections = [0, 1, 2, 3].map((index) => ({...(saved.panelSelections[index] || {})}));
  }
  if (Array.isArray(saved.panelDisplays)) {
    state.panelDisplays = [0, 1, 2, 3].map((index) => ({...(saved.panelDisplays[index] || {})}));
  }
  if (saved.pointerFields && typeof saved.pointerFields === "object") {
    state.pointerFields = {
      ...state.pointerFields,
      ...saved.pointerFields,
    };
    applyPointerFieldState();
  }
  setPanelCount(Number(saved.panelCount) || 1);
  await searchCatalog();
  if (saved.itemIndex && el("itemSelect").options[Number(saved.itemIndex)]) {
    el("itemSelect").value = saved.itemIndex;
    state.activeItem = state.items[Number(saved.itemIndex)];
    await prepareActiveItemForDisplay();
  }
  if (saved.time) el("timeSelect").value = saved.time;
  refreshElevationControls(saved.dataset);
  setBasemap(el("basemapSelect").value);
  if (state.panelCount === 4) {
    initializePanelSelections();
    refreshTimeControls();
    refreshAllPanelControls();
    scheduleVisiblePreviews();
  } else {
    schedulePreview();
  }
}

async function downloadProject() {
  const sessionId = el("sessionIdInput").value.trim() || "default";
  const now = new Date().toISOString();
  const project = {
    type: "uk-wsr-visualizer-project",
    version: 1,
    exported_at: now,
    application: "uk-wsr-visualizer",
    session: {
      session_id: sessionId,
      title: sessionId,
      version: 1,
      created_at: now,
      updated_at: now,
      notes: [],
      state: currentSessionState(),
    },
  };
  const filename = `${sessionId}.uk-wsr-visualizer-project.json`;
  const saved = await downloadBlob(filename, JSON.stringify(project, null, 2), "application/json");
  el("sessionStatus").textContent = `Downloaded ${saved.path || filename}`;
}

async function importProjectFile(file) {
  const payload = JSON.parse(await file.text());
  if (payload.type !== "uk-wsr-visualizer-project" || !payload.session || !payload.session.state) {
    throw new Error("Not a UK WSR Visualizer project file.");
  }
  el("sessionIdInput").value = payload.session.session_id || "imported";
  await applySessionState(payload.session.state);
  el("sessionStatus").textContent = `Imported ${payload.session.session_id || file.name}`;
}

async function showObjectUrl() {
  const item = state.activeItem;
  if (!item) return;
  const response = await api(`/api/object-url/${item.radar}/${item.date}`);
  const data = await response.json();
  el("metadataOutput").textContent = JSON.stringify(data, null, 2);
  el("metadataDialog").showModal();
}

async function clearRawCache() {
  const response = await api("/api/cache/raw/clear", {method: "POST"});
  const data = await response.json();
  state.panelMeta.clear();
  clearPpiFrameCache();
  setStatus(`Cleared raw cache: removed ${data.removed_count} file(s), ${Math.round((data.removed_bytes || 0) / 1024 / 1024)} MB.`);
}

async function openObjectUrl() {
  const item = state.activeItem;
  if (!item) return;
  const response = await api(`/api/object-url/${item.radar}/${item.date}`);
  const data = await response.json();
  const url = data.external_url || data.object_url;
  if (!url) {
    setStatus("No source URL is available for the selected item.", true);
    return;
  }
  window.open(url, "_blank", "noopener");
}

const FIELD_EXPORT_FORMATS = new Set(["screenshot_png", "png", "mp4", "kmz", "geotiff", "cf_netcdf", "geojson", "shapefile", "field_csv", "qc_mask"]);

function coordinateModeForExport(format) {
  return {
    screenshot_png: "screen_view",
    png: "polar_ppi",
    mp4: "polar_ppi_animation",
    kmz: "georeferenced_map_overlay",
    geotiff: "georeferenced_cartesian",
    cf_netcdf: "georeferenced_cartesian",
    geojson: "georeferenced_vector",
    shapefile: "georeferenced_vector",
    field_csv: "polar_gate_table",
    qc_mask: "polar_gate_mask",
    native_hdf5: "source_native",
    metadata_json: "catalog_metadata",
  }[format] || "unspecified";
}

function exportFormatLabel(format) {
  const option = Array.from(el("exportFormatSelect").options).find((entry) => entry.value === format);
  return option ? option.textContent : format;
}

function updateMp4ExportControls() {
  const options = el("mp4ExportOptions");
  if (!options) return;
  const isMp4 = el("exportFormatSelect").value === "mp4";
  options.hidden = !isMp4;
  if (!isMp4) return;

  const panel = panels()[0];
  const item = itemByKey(`${panel.dataset.radar}:${panel.dataset.date}`) || state.activeItem;
  const pulse = panel.dataset.pulse || selectedPulse(item);
  const quantity = panel.dataset.quantity || selectedQuantity(item, pulse, panel.dataset.time || el("timeSelect").value);
  const times = availableTimesForSelection(item, pulse, quantity);
  const startSelect = el("mp4StartTimeSelect");
  const endSelect = el("mp4EndTimeSelect");
  const previousStart = startSelect.value;
  const previousEnd = endSelect.value;
  const optionHtml = times.map((time) => `<option value="${escapeHtml(time)}">${escapeHtml(time)}</option>`).join("");
  startSelect.innerHTML = optionHtml;
  endSelect.innerHTML = optionHtml;
  startSelect.value = times.includes(previousStart) ? previousStart : times[0] || "";
  endSelect.value = times.includes(previousEnd) ? previousEnd : times[times.length - 1] || "";
  const fullDay = el("mp4FullDayInput").checked;
  startSelect.disabled = fullDay || !times.length;
  endSelect.disabled = fullDay || !times.length;

  let selectedTimes = times;
  if (!fullDay && times.length) {
    const startIndex = times.indexOf(startSelect.value);
    const endIndex = times.indexOf(endSelect.value);
    selectedTimes = startIndex >= 0 && endIndex >= startIndex ? times.slice(startIndex, endIndex + 1) : [];
  }
  const delayMs = Math.max(50, Number(el("delayInput").value || 600));
  const durationSeconds = (selectedTimes.length * delayMs) / 1000;
  el("mp4ExportSummary").textContent = selectedTimes.length
    ? `${selectedTimes.length} frames, ${delayMs} ms per frame (${(1000 / delayMs).toFixed(2)} fps), estimated ${durationSeconds.toFixed(1)} s video.`
    : "Choose a valid start and end time.";
}

function currentPrimaryExportSelection(format) {
  const panel = panels()[0];
  const panelHasField = Boolean(panel?.dataset.radar && panel.dataset.date);
  const item = state.activeItem;
  if (!item && !panelHasField) throw new Error("Search the catalog and select a source object before exporting.");

  const request = {
    radar: panel.dataset.radar || item.radar,
    date: panel.dataset.date || item.date,
    format,
    palette: panelDisplay(0).palette,
    filters: filterParams(panelDisplay(0)),
    coordinate_mode: coordinateModeForExport(format),
  };
  if (FIELD_EXPORT_FORMATS.has(format)) {
    const pulse = panel.dataset.pulse || selectedPulse(item);
    const time = panel.dataset.time || el("timeSelect").value;
    const quantity = panel.dataset.quantity || selectedQuantity(item, pulse, time);
    if (!pulse || !time || !quantity) {
      throw new Error(`Load a plot-ready radar field before creating a ${format.toUpperCase()} export.`);
    }
    request.pulse = pulse;
    request.time = time;
    request.quantity = quantity;
    request.dataset = panel.dataset.fieldDataset || optionalInputValue("datasetInput") || null;
    if (format === "mp4") {
      const exportItem = itemByKey(`${request.radar}:${request.date}`) || item;
      const times = availableTimesForSelection(exportItem, pulse, quantity);
      const fullDay = el("mp4FullDayInput").checked;
      const startTime = fullDay ? times[0] : el("mp4StartTimeSelect").value;
      const endTime = fullDay ? times[times.length - 1] : el("mp4EndTimeSelect").value;
      const startIndex = times.indexOf(startTime);
      const endIndex = times.indexOf(endTime);
      if (times.length && (startIndex < 0 || endIndex < startIndex)) {
        throw new Error("Choose an animation end time that is at or after the start time.");
      }
      request.times = times.length ? times.slice(startIndex, endIndex + 1) : [time];
      request.animation_full_day = fullDay;
      request.animation_start_time = request.times[0] || time;
      request.animation_end_time = request.times[request.times.length - 1] || time;
      request.frame_delay_ms = Number(el("delayInput").value || 600);
    }
    if (panelDisplay(0).palette === "custom") {
      request.filters.palette_stops = el("customPaletteInput").value.trim();
    }
  }
  return request;
}

function updateExportLinks(job) {
  const node = el("exportLinks");
  if (!node) return;
  node.replaceChildren();
  if (!job || job.status !== "complete" || !job.download_url) {
    node.hidden = true;
    return;
  }
  const download = document.createElement("a");
  download.href = job.download_url;
  download.textContent = "Download export artifact";
  download.setAttribute("download", "");

  const manifest = document.createElement("a");
  manifest.href = `/api/export/${encodeURIComponent(job.job_id)}/manifest`;
  manifest.textContent = "Open provenance manifest";
  manifest.target = "_blank";
  manifest.rel = "noopener";

  node.append(download, manifest);
  node.hidden = false;
}

function setExportJob(job) {
  state.exportJob = job || null;
  const complete = Boolean(job && job.status === "complete" && job.download_url);
  el("viewManifestButton").disabled = !complete;
  el("downloadExportButton").disabled = !complete;
  updateExportLinks(job);
}

async function createScreenshotExport(request) {
  const panel = panels()[0];
  const ppi = state.panelMeta.get(0);
  if (!ppi) throw new Error("Load a radar plot before creating a screenshot export.");
  let warning = "";
  let canvas = composePanelScreenshot(panel, true);
  let pngBlob;
  try {
    pngBlob = await canvasBlob(canvas);
  } catch (_err) {
    warning = "External basemap tiles could not be embedded because the tile server did not permit canvas export; radar and range overlays are included.";
    canvas = composePanelScreenshot(panel, false);
    pngBlob = await canvasBlob(canvas);
  }
  const safeParts = [request.radar, formatDate(request.date), request.pulse, request.time, request.quantity, request.dataset || "auto"]
    .filter(Boolean)
    .map((part) => String(part).replace(/[^A-Za-z0-9._-]+/g, "-"));
  const stem = `${safeParts.join("_")}_screen-view`;
  const pngSave = await downloadBlob(`${stem}.png`, pngBlob, "image/png");
  const citation = await (await api("/api/citation")).json();
  const manifest = {
    version: 1,
    generated_at: new Date().toISOString(),
    format: "screenshot_png",
    coordinate_mode: request.coordinate_mode,
    warning,
    request,
    selection: {
      radar: request.radar,
      date: request.date,
      pulse: request.pulse,
      time: request.time,
      quantity: request.quantity,
      dataset: request.dataset,
      palette: request.palette,
      filters: request.filters,
      view: panel._mapTransform ? {
        zoom: panel._mapTransform.zoom,
        tile_zoom: panel._mapTransform.tileZoom,
        center: pixelToLonLat(panel._mapTransform.width / 2, panel._mapTransform.height / 2, panel._mapTransform),
        basemap: el("basemapSelect").value,
      } : null,
    },
    source: {
      item_id: state.activeItem?.item_id || "",
      object_key: state.activeItem?.object_key || "",
      object_url: state.activeItem?.object_url || "",
    },
    software: citation.software,
    article: citation.article,
    source_data: citation.source_data,
    infrastructure: citation.infrastructure,
    citation_instruction: citation.user_instruction,
  };
  const manifestSave = await downloadBlob(`${stem}.manifest.json`, JSON.stringify(manifest, null, 2), "application/json");
  setExportJob(null);
  el("exportStatus").textContent = [
    "Screenshot export complete.",
    `PNG: ${pngSave.path || `${stem}.png`}`,
    `Manifest: ${manifestSave.path || `${stem}.manifest.json`}`,
    warning || "The screenshot uses the current screen-view coordinate mode.",
  ].join("\n");
  setStatus(`Screenshot export complete for ${request.radar} ${formatDate(request.date)}.`);
}

async function createExport() {
  const format = el("exportFormatSelect").value;
  const request = currentPrimaryExportSelection(format);
  setExportJob(null);
  const label = exportFormatLabel(format);
  if (format === "screenshot_png") {
    await createScreenshotExport(request);
    return;
  }
  el("exportStatus").textContent = `Creating ${label} for ${request.radar} ${formatDate(request.date)}...`;
  setStatus(`Creating ${label} for ${request.radar} ${formatDate(request.date)}...`);
  const response = await api("/api/export", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(request),
  });
  const job = await response.json();
  setExportJob(job);
  if (job.status !== "complete") {
    const message = job.error || "export did not complete";
    el("exportStatus").textContent = `Export failed: ${message}`;
    setStatus(`Export failed: ${message}`, true);
    return;
  }
  el("exportStatus").textContent = [
    `Export complete: ${job.job_id}`,
    `Format: ${exportFormatLabel(job.request.format)} (${job.request.coordinate_mode || coordinateModeForExport(job.request.format)})`,
    `Selection: ${job.request.radar} ${formatDate(job.request.date)} ${job.request.pulse || ""} ${job.request.time || ""} ${job.request.quantity || ""}`.trim(),
    "Use the links below for the artifact and provenance manifest.",
  ].join("\n");
  setStatus(`Export complete: ${exportFormatLabel(job.request.format)} for ${job.request.radar} ${formatDate(job.request.date)}.`);
}

async function showExportManifest() {
  if (!state.exportJob) throw new Error("Create an export before viewing a manifest.");
  const response = await api(`/api/export/${encodeURIComponent(state.exportJob.job_id)}/manifest`);
  const manifest = await response.json();
  el("metadataOutput").textContent = JSON.stringify(manifest, null, 2);
  el("metadataDialog").showModal();
}

function browserDownloadCurrentExport() {
  const link = document.createElement("a");
  link.href = state.exportJob.download_url;
  link.setAttribute("download", "");
  document.body.append(link);
  link.click();
  link.remove();
  setStatus(`Download started for ${state.exportJob.job_id}.`);
}

async function downloadCurrentExport() {
  if (!state.exportJob?.download_url) {
    setStatus("Create a completed export before downloading.", true);
    return;
  }
  if (isLocalAppServer()) {
    try {
      const response = await api(`/api/export/${encodeURIComponent(state.exportJob.job_id)}/save-to-downloads`, {method: "POST"});
      const saved = await response.json();
      const label = saved.is_directory ? "export folder" : "export";
      const detail = saved.is_directory && saved.artifact_count ? ` (${saved.artifact_count} files)` : "";
      const message = `Saved ${label}${detail} to ${saved.path}.`;
      setStatus(message);
      el("exportStatus").textContent = `${el("exportStatus").textContent}\n${message}`;
      return;
    } catch (err) {
      console.warn("Desktop export save failed; falling back to browser download.", err);
      setStatus(`Desktop save failed; trying browser download: ${err.message}`, true);
    }
  }
  browserDownloadCurrentExport();
}

function rangeBearingFromRadar(metadata, lon, lat) {
  const lat1 = (metadata.latitude * Math.PI) / 180;
  const lat2 = (lat * Math.PI) / 180;
  const deltaLat = ((lat - metadata.latitude) * Math.PI) / 180;
  const deltaLon = ((lon - metadata.longitude) * Math.PI) / 180;
  const a = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
  const rangeM = 2 * EARTH_RADIUS_M * Math.atan2(Math.sqrt(a), Math.sqrt(Math.max(0, 1 - a)));
  const y = Math.sin(deltaLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(deltaLon);
  const azimuthDeg = ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
  return {rangeM, azimuthDeg};
}

function binFromMouse(panel, event) {
  const panelIndex = Number(panel.dataset.panel);
  const ppi = state.panelMeta.get(panelIndex);
  const transform = panel._mapTransform;
  if (!ppi || !transform) return null;
  const rect = panel.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top - panelControlInset(panel);
  if (y < 0) return null;
  const geo = pixelToLonLat(x, y, transform);
  const rb = rangeBearingFromRadar(ppi.metadata, geo.lon, geo.lat);
  if (rb.rangeM < ppi.metadata.rstart_km * 1000 || rb.rangeM > ppi.metadata.max_range_m) {
    return {ppi, lon: geo.lon, lat: geo.lat, outside: true};
  }
  const row = Math.max(0, Math.min(ppi.metadata.nrays - 1, Math.floor((rb.azimuthDeg / 360) * ppi.metadata.nrays)));
  const column = Math.max(0, Math.min(ppi.metadata.nbins - 1, Math.floor((rb.rangeM - ppi.metadata.rstart_km * 1000) / ppi.metadata.rscale_m)));
  return {ppi, lon: geo.lon, lat: geo.lat, rangeM: rb.rangeM, azimuthDeg: rb.azimuthDeg, row, column, outside: false};
}

function describeHit(hit, valueText = "") {
  const fields = state.pointerFields;
  const parts = [];
  const metadata = hit.ppi?.metadata || {};
  if (fields.value && valueText) parts.push(valueText);
  if (fields.bin) parts.push(`row=${hit.row}`, `col=${hit.column}`);
  if (fields.range) {
    parts.push(`range=${fmtNumber(hit.rangeM / 1000, 2)} km`);
    parts.push(`az=${fmtNumber(hit.azimuthDeg, 1)} deg`);
  }
  if (fields.height) {
    const height = beamHeightM(hit.rangeM, metadata.elevation_deg, metadata.height_m);
    parts.push(`height=${height === null ? "n/a" : `${fmtNumber(height / 1000, 2)} km`}`);
  }
  if (fields.elevation) parts.push(sweepLabel(metadata));
  if (fields.latlon) parts.push(`lat=${fmtNumber(hit.lat, 5)}`, `lon=${fmtNumber(hit.lon, 5)}`);
  return parts.length ? parts.join(", ") : "Pointer readout is hidden. Turn on a Pointer field above.";
}

function describeOutsideHit(hit) {
  const parts = [];
  if (state.pointerFields.latlon) parts.push(`lat=${fmtNumber(hit.lat, 5)}`, `lon=${fmtNumber(hit.lon, 5)}`);
  parts.push("outside radar range");
  return parts.join(", ");
}

function scheduleHoverIdentify(panel, hit) {
  const panelIndex = Number(panel.dataset.panel);
  const existing = state.identifyTimers.get(panelIndex);
  if (existing) clearTimeout(existing);
  const requestId = String(++state.identifyRequestSeq);
  panel.dataset.identifyRequestId = requestId;
  const timer = setTimeout(async () => {
    state.identifyTimers.delete(panelIndex);
    if (panel.dataset.identifyRequestId !== requestId || !panel.dataset.radar) return;
    try {
      const response = await api(identifyUrlForPanel(panel, hit.row, hit.column));
      const data = await response.json();
      if (panel.dataset.identifyRequestId !== requestId) return;
      setPanelReadout(panel, describeHit(hit, identifyValueText(data)));
    } catch (_err) {
      // Keep the immediate location readout if a hover identify request is interrupted.
    }
  }, 140);
  state.identifyTimers.set(panelIndex, timer);
}

function panelPoint(panel, event) {
  const rect = panel.getBoundingClientRect();
  return {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top - panelControlInset(panel),
  };
}

function zoomPanelAt(panel, x, y, zoomDelta) {
  const panelIndex = Number(panel.dataset.panel);
  const ppi = state.panelMeta.get(panelIndex);
  const transform = panel._mapTransform;
  if (!ppi || !transform) return;
  const before = pixelToLonLat(x, y, transform);
  const zoom = Math.max(3, Math.min(14, transform.zoom + zoomDelta));
  const world = lonLatToWorld(before.lon, before.lat, zoom);
  const {width, height} = panelViewportSize(panel);
  panel._mapTransform = updateTileTransform({
    ...transform,
    zoom,
    width,
    height,
    left: world.x - x,
    top: world.y - y,
  });
  if (panel._zoomRenderTimer) clearTimeout(panel._zoomRenderTimer);
  panel._zoomRenderTimer = setTimeout(() => {
    delete panel._zoomRenderTimer;
    renderPanel(panel, ppi);
    syncLinkedViewFromPanel(panel);
  }, 60);
}

function panPanel(panel, dx, dy) {
  const panelIndex = Number(panel.dataset.panel);
  const ppi = state.panelMeta.get(panelIndex);
  const transform = panel._mapTransform;
  if (!ppi || !transform) return;
  panel._mapTransform = updateTileTransform({
    ...transform,
    left: transform.left - dx,
    top: transform.top - dy,
  });
  renderPanel(panel, ppi);
  syncLinkedViewFromPanel(panel);
}

function movablePanelLayers(panel) {
  return [
    panel.querySelector(".tile-layer"),
    panel.querySelector(".ppi-canvas"),
    panel.querySelector(".map-overlay-canvas"),
  ].filter(Boolean);
}

function setPanelPreviewTranslation(panel, dx, dy) {
  movablePanelLayers(panel).forEach((layer) => {
    layer.style.transform = `translate(${dx}px, ${dy}px)`;
  });
}

function previewPanelPan(panel, dx, dy) {
  const preview = panel._panPreview;
  if (!preview) return;
  preview.dx += dx;
  preview.dy += dy;
  setPanelPreviewTranslation(panel, preview.dx, preview.dy);
  if (state.panelCount === 4 && state.comparisonLinks.view) {
    visiblePanelIndices().forEach((index) => {
      const linkedPanel = panels()[index];
      if (linkedPanel && linkedPanel !== panel) setPanelPreviewTranslation(linkedPanel, preview.dx, preview.dy);
    });
  }
}

function commitPanelPan(panel) {
  const preview = panel._panPreview;
  delete panel._panPreview;
  visiblePanelIndices().forEach((index) => setPanelPreviewTranslation(panels()[index], 0, 0));
  if (!preview || (!preview.dx && !preview.dy)) return;
  const transform = panel._mapTransform;
  const ppi = state.panelMeta.get(Number(panel.dataset.panel));
  if (!transform || !ppi) return;
  panel._mapTransform = updateTileTransform({
    ...transform,
    left: transform.left - preview.dx,
    top: transform.top - preview.dy,
  });
  renderPanel(panel, ppi);
  syncLinkedViewFromPanel(panel);
}

function touchPoint(panel, touch) {
  const rect = panel.getBoundingClientRect();
  return {
    x: touch.clientX - rect.left,
    y: touch.clientY - rect.top - panelControlInset(panel),
  };
}

function touchDistance(first, second) {
  return Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY);
}

function touchMidpoint(panel, first, second) {
  const left = touchPoint(panel, first);
  const right = touchPoint(panel, second);
  return {
    x: (left.x + right.x) / 2,
    y: (left.y + right.y) / 2,
  };
}

function updateComparisonLinkState() {
  state.comparisonLinks.view = el("linkViewInput").checked;
  state.comparisonLinks.time = el("linkTimeInput").checked;
  state.comparisonLinks.variable = el("linkVariableInput").checked;
  state.comparisonLinks.elevation = el("linkElevationInput").checked;
  state.comparisonLinks.colour = el("linkColourInput").checked;
}

function applyComparisonLinkState() {
  [
    ["linkViewInput", "view"],
    ["linkTimeInput", "time"],
    ["linkVariableInput", "variable"],
    ["linkElevationInput", "elevation"],
    ["linkColourInput", "colour"],
  ].forEach(([id, key]) => {
    const node = el(id);
    if (node) node.checked = Boolean(state.comparisonLinks[key]);
  });
}

function isTextEntryTarget(target) {
  const tagName = target?.tagName;
  return tagName === "INPUT" || tagName === "SELECT" || tagName === "TEXTAREA" || target?.isContentEditable;
}

function handleKeyboardNavigation(event) {
  if (isTextEntryTarget(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
  if (event.key === "ArrowLeft" && event.shiftKey) {
    event.preventDefault();
    stepItem(-1).catch((err) => setStatus(err.message, true));
  } else if (event.key === "ArrowRight" && event.shiftKey) {
    event.preventDefault();
    stepItem(1).catch((err) => setStatus(err.message, true));
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    stepFrame(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    stepFrame(1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    stepElevation(-1);
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    stepElevation(1);
  } else if (event.key === "0") {
    event.preventDefault();
    panels().forEach((panel) => resetPanelView(panel));
  }
}

function hideHelpTooltip() {
  const tooltip = document.getElementById("helpTooltipPopover");
  if (!tooltip) return;
  const owner = document.querySelector('[aria-describedby="helpTooltipPopover"]');
  if (owner) owner.removeAttribute("aria-describedby");
  tooltip.hidden = true;
}

function showHelpTooltip(target) {
  if (!document.body.classList.contains("help-tooltips") || !target?.dataset.help) return;
  let tooltip = document.getElementById("helpTooltipPopover");
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.id = "helpTooltipPopover";
    tooltip.className = "help-tooltip-popover";
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
  }
  hideHelpTooltip();
  tooltip.textContent = target.dataset.help;
  tooltip.hidden = false;
  target.setAttribute("aria-describedby", tooltip.id);

  const targetRect = target.getBoundingClientRect();
  const margin = 8;
  const left = Math.min(
    Math.max(margin, targetRect.left),
    Math.max(margin, window.innerWidth - tooltip.offsetWidth - margin),
  );
  const below = targetRect.bottom + 6;
  const top = below + tooltip.offsetHeight <= window.innerHeight - margin
    ? below
    : Math.max(margin, targetRect.top - tooltip.offsetHeight - 6);
  tooltip.style.left = `${Math.round(left)}px`;
  tooltip.style.top = `${Math.round(top)}px`;
}

function attachHelpTooltipEvents() {
  document.addEventListener("pointerover", (event) => {
    const target = event.target.closest?.("[data-help]");
    if (target) showHelpTooltip(target);
  });
  document.addEventListener("pointerout", (event) => {
    const target = event.target.closest?.("[data-help]");
    if (target && !target.contains(event.relatedTarget)) hideHelpTooltip();
  });
  document.addEventListener("focusin", (event) => {
    const target = event.target.closest?.("[data-help]");
    if (target) showHelpTooltip(target);
  });
  document.addEventListener("focusout", (event) => {
    if (event.target.closest?.("[data-help]")) hideHelpTooltip();
  });
  window.addEventListener("resize", hideHelpTooltip);
  document.addEventListener("scroll", hideHelpTooltip, true);
}

function attachEvents() {
  applyPointerFieldState();
  applyComparisonLinkState();
  attachHelpTooltipEvents();
  el("refreshButton").addEventListener("click", () => refreshCatalogAndSearch().catch((err) => reportLoadError(err, "Refresh failed")));
  el("retryLoadButton").addEventListener("click", () => retryLastLoad().catch((err) => reportLoadError(err, "Retry failed")));
  el("searchButton").addEventListener("click", () => searchCatalog().catch((err) => reportLoadError(err, "Catalog search failed")));
  el("catalogSourceSelect").addEventListener("change", () => selectCatalogSource().catch((err) => reportLoadError(err, "Could not switch data era", selectCatalogSource)));
  el("radarSelect").addEventListener("change", () => refreshAvailability().catch((err) => setStatus(err.message, true)));
  el("helpToggle").addEventListener("change", () => {
    document.body.classList.toggle("help-tooltips", el("helpToggle").checked);
    if (!el("helpToggle").checked) hideHelpTooltip();
  });
  el("firstAvailableButton").addEventListener("click", () => useAvailableDate("first"));
  el("latestAvailableButton").addEventListener("click", () => useAvailableDate("latest"));
  el("clearRecentButton").addEventListener("click", () => clearRecentSelections().catch((err) => setStatus(err.message, true)));
  ["startInput", "endInput"].forEach((id) => {
    el(id).addEventListener("blur", () => {
      normalizeDateInput(id);
      handleDateSelectionChanged();
    });
    el(id).addEventListener("change", handleDateSelectionChanged);
    el(id).addEventListener("input", () => {
      const value = el(id).value.trim();
      if (value === "" || value.length >= 10) handleDateSelectionChanged();
    });
  });
  el("itemSelect").addEventListener("change", () => {
    state.activeItem = state.items[Number(el("itemSelect").value)];
    prepareActiveItemForDisplay()
      .then(() => {
        if (state.panelCount === 4) {
          setPanelSelection(0, {
            itemKey: itemKey(state.activeItem),
            quantity: el("quantitySelect").value || DEFAULT_VARIABLE,
            dataset: optionalInputValue("datasetInput"),
          });
          refreshPanelControls(0);
          refreshTimeControls();
          schedulePreview(0, 0);
        } else {
          schedulePreview(0, 0);
        }
      })
      .catch((err) => {
        reportLoadError(err, "Could not load item details", async () => prepareActiveItemForDisplay());
        panels().forEach((panel) => setPanelMessage(panel, err.message, true));
      });
  });
  [
    "timeSelect",
    "datasetInput",
    "pulseSelect",
    "quantitySelect",
    "customPaletteInput",
    "minRangeInput",
    "maxRangeInput",
    "minAzimuthInput",
    "maxAzimuthInput",
    "minValueInput",
    "maxValueInput",
    "cappiHeightInput",
    "displayMinInput",
    "displayMaxInput",
    "noiseFloorInput",
    "noiseFloorMethodSelect",
    "noiseFloorMarginInput",
    "backgroundModelPathInput",
    "rangeRingsInput",
    "rangeRingSpacingInput",
  ].forEach((id) => {
    el(id).addEventListener("change", () => {
      if (id === "pulseSelect" || id === "quantitySelect") {
        if (id === "pulseSelect") refreshVariableControls(state.activeItem);
        if (state.panelCount === 4 && id === "quantitySelect") {
          const patch = {quantity: el("quantitySelect").value || DEFAULT_VARIABLE, dataset: ""};
          setPanelSelection(0, patch);
          syncLinkedPanelSelection(0, patch);
        }
        refreshTimeControls();
        refreshElevationControls();
        if (!el("timeSelect").options.length && state.activeItem) {
          setStatus(`No available radar times for ${itemLabel(state.activeItem)} with the selected ${id === "pulseSelect" ? "pulse" : "variable"}.`, true);
        }
      }
      else if (id === "timeSelect") {
        updateTimeStepOutput();
        refreshElevationControls();
        refreshAllPanelControls();
      }
      else if (id === "datasetInput" && state.panelCount === 4) {
        const selection = panelSelection(0);
        const pulse = selectedPulseForItem(selection.item, selection.quantity);
        const elevations = availablePanelElevations(selection.item, pulse, selection.time, selection.quantity);
        const dataset = optionalInputValue("datasetInput");
        const patch = {dataset, elevationDeg: elevationDegForDataset(elevations, dataset)};
        setPanelSelection(0, patch);
        syncLinkedPanelSelection(0, patch);
      }
      scheduleVisiblePreviews();
    });
  });
  el("opacityInput").addEventListener("input", applyOpacity);
  el("paletteSelect").addEventListener("change", () => scheduleVisiblePreviews());
  el("basemapSelect").addEventListener("change", () => setBasemap(el("basemapSelect").value));
  ["linkViewInput", "linkTimeInput", "linkVariableInput", "linkElevationInput", "linkColourInput"].forEach((id) => {
    el(id).addEventListener("change", () => {
      const sourceSelection = {...(state.panelSelections[0] || {})};
      updateComparisonLinkState();
      if (id === "linkTimeInput") refreshTimeControls();
      if (id === "linkVariableInput" && state.comparisonLinks.variable) {
        const quantity = sourceSelection.quantity || panelSelection(0).quantity;
        setPanelSelection(0, {quantity});
        syncLinkedPanelSelection(0, {quantity});
      }
      if (id === "linkElevationInput" && state.comparisonLinks.elevation) {
        const dataset = sourceSelection.dataset || panelSelection(0).dataset;
        const elevationDeg = sourceSelection.elevationDeg ?? panelSelection(0).elevationDeg;
        setPanelSelection(0, {dataset, elevationDeg});
        syncLinkedPanelSelection(0, {dataset, elevationDeg});
      }
      if (id === "linkVariableInput" || id === "linkElevationInput" || id === "linkColourInput") {
        refreshAllPanelControls();
        syncComparisonSidebarFromPanels();
        if (id === "linkVariableInput" && state.comparisonLinks.variable) refreshTimeControls();
      }
      updateComparisonSidebarControlMode();
      if (id === "linkViewInput" && state.comparisonLinks.view) {
        const source = panels().find((panel, index) => state.panelMeta.has(index));
        if (source) syncLinkedViewFromPanel(source);
      }
      scheduleVisiblePreviews();
    });
  });
  el("prevButton").addEventListener("click", () => stepFrame(-1));
  el("nextButton").addEventListener("click", () => stepFrame(1));
  el("timePrevButton").addEventListener("click", () => stepFrame(-1));
  el("timeNextButton").addEventListener("click", () => stepFrame(1));
  el("playButton").addEventListener("click", togglePlay);
  el("captureButton").addEventListener("click", captureFrame);
  el("metadataButton").addEventListener("click", showMetadata);
  el("citationButton").addEventListener("click", () => showCitation().catch((err) => setStatus(err.message, true)));
  el("performanceButton").addEventListener("click", () => showPerformance().catch((err) => setStatus(err.message, true)));
  el("closeMetadataButton").addEventListener("click", () => el("metadataDialog").close());
  el("closeCitationButton").addEventListener("click", () => el("citationDialog").close());
  el("closePerformanceButton").addEventListener("click", () => el("performanceDialog").close());
  el("refreshPerformanceButton").addEventListener("click", () => renderPerformanceDialog().catch((err) => setStatus(err.message, true)));
  el("clearPerformanceButton").addEventListener("click", () => clearPerformanceEvents().catch((err) => setStatus(err.message, true)));
  el("downloadPerformanceButton").addEventListener("click", () => downloadPerformanceReport().catch((err) => setStatus(err.message, true)));
  el("saveSessionButton").addEventListener("click", () => saveSession().catch((err) => {
    el("sessionStatus").textContent = err.message;
  }));
  el("loadSessionButton").addEventListener("click", () => loadSession().catch((err) => {
    el("sessionStatus").textContent = err.message;
  }));
  el("downloadProjectButton").addEventListener("click", () => downloadProject().catch((err) => {
    el("sessionStatus").textContent = err.message;
    setStatus(err.message, true);
  }));
  el("projectFileInput").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    importProjectFile(file).catch((err) => {
      el("sessionStatus").textContent = err.message;
    });
  });
  el("clearRawCacheButton").addEventListener("click", () => clearRawCache().catch((err) => setStatus(err.message, true)));
  el("objectUrlButton").addEventListener("click", () => showObjectUrl().catch((err) => setStatus(err.message, true)));
  el("openObjectButton").addEventListener("click", () => openObjectUrl().catch((err) => setStatus(err.message, true)));
  el("fitViewButton").addEventListener("click", fitVisiblePanels);
  el("exportFormatSelect").addEventListener("change", updateMp4ExportControls);
  ["mp4FullDayInput", "mp4StartTimeSelect", "mp4EndTimeSelect", "delayInput"].forEach((id) => {
    el(id).addEventListener("change", updateMp4ExportControls);
  });
  el("createExportButton").addEventListener("click", () => createExport().catch((err) => {
    el("exportStatus").textContent = err.message;
    setStatus(err.message, true);
  }));
  el("viewManifestButton").addEventListener("click", () => showExportManifest().catch((err) => setStatus(err.message, true)));
  el("downloadExportButton").addEventListener("click", () => downloadCurrentExport().catch((err) => setStatus(err.message, true)));
  document.querySelectorAll(".view-button").forEach((button) => {
    button.addEventListener("click", () => setPanelCount(Number(button.dataset.panelCount)));
  });
  document.querySelectorAll(".pointer-field-toggle").forEach((input) => {
    input.addEventListener("change", updatePointerFieldState);
  });
  panels().forEach((panel) => {
    const panelIndex = Number(panel.dataset.panel);
    const panelItemSelect = panel.querySelector(".panel-item-select");
    const panelVariableSelect = panel.querySelector(".panel-variable-select");
    const panelTimeSelect = panel.querySelector(".panel-time-select");
    const panelElevationSelect = panel.querySelector(".panel-elevation-select");
    const panelPaletteSelect = panel.querySelector(".panel-palette-select");
    const panelDisplayMinInput = panel.querySelector(".panel-display-min-input");
    const panelDisplayMaxInput = panel.querySelector(".panel-display-max-input");
    const panelControls = panel.querySelector(".panel-controls");
    if (panelControls && !panelControls.querySelector(".panel-display-toggle")) {
      const displayToggle = document.createElement("button");
      displayToggle.type = "button";
      displayToggle.className = "panel-display-toggle";
      displayToggle.textContent = "Display";
      displayToggle.title = "Show or hide this panel's palette and display limits.";
      displayToggle.setAttribute("aria-expanded", "false");
      displayToggle.addEventListener("click", () => {
        const expanded = panel.classList.toggle("show-panel-display");
        displayToggle.setAttribute("aria-expanded", String(expanded));
        const ppi = state.panelMeta.get(panelIndex);
        if (ppi) renderPanel(panel, ppi);
      });
      panelControls.insertBefore(displayToggle, panelControls.querySelector(".panel-display-controls"));
    }
    if (panelItemSelect) {
      panelItemSelect.addEventListener("change", async () => {
        setPanelSelection(panelIndex, {itemKey: panelItemSelect.value, quantity: DEFAULT_VARIABLE, dataset: ""});
        const item = itemByKey(panelItemSelect.value);
        if (item) {
          await hydrateItemDetails(item);
          if (panelIndex === 0) {
            state.activeItem = item;
            const activeIndex = state.items.findIndex((candidate) => itemKey(candidate) === itemKey(item));
            if (activeIndex >= 0) el("itemSelect").value = String(activeIndex);
            refreshVariableControls(item);
          }
        }
        refreshPanelControls(panelIndex);
        refreshTimeControls();
        schedulePreview(panelIndex, 0);
      });
    }
    if (panelVariableSelect) {
      panelVariableSelect.addEventListener("change", () => {
        setPanelSelection(panelIndex, {quantity: panelVariableSelect.value || DEFAULT_VARIABLE, dataset: ""});
        syncLinkedPanelSelection(panelIndex, {quantity: panelVariableSelect.value || DEFAULT_VARIABLE, dataset: ""});
        refreshAllPanelControls();
        refreshTimeControls();
        syncComparisonSidebarFromPanels();
        scheduleVisiblePreviews(0);
      });
    }
    if (panelTimeSelect) {
      panelTimeSelect.addEventListener("change", () => {
        setPanelSelection(panelIndex, {time: panelTimeSelect.value || "", dataset: ""});
        syncLinkedPanelSelection(panelIndex, {time: panelTimeSelect.value || "", dataset: ""});
        refreshPanelControls(panelIndex);
        updateTimeStepOutput();
        scheduleVisiblePreviews(0);
      });
    }
    if (panelElevationSelect) {
      panelElevationSelect.addEventListener("change", () => {
        const selection = panelSelection(panelIndex);
        const pulse = selectedPulseForItem(selection.item, selection.quantity);
        const elevations = availablePanelElevations(selection.item, pulse, selection.time, selection.quantity);
        const elevationDeg = elevationDegForDataset(elevations, panelElevationSelect.value);
        setPanelSelection(panelIndex, {dataset: panelElevationSelect.value || "", elevationDeg});
        syncLinkedPanelSelection(panelIndex, {dataset: panelElevationSelect.value || "", elevationDeg});
        refreshAllPanelControls();
        syncComparisonSidebarFromPanels();
        visiblePanelIndices().forEach((index) => schedulePreview(index, 0));
      });
    }
    [panelPaletteSelect, panelDisplayMinInput, panelDisplayMaxInput].forEach((control) => {
      if (!control) return;
      control.addEventListener("change", () => {
        setPanelDisplay(panelIndex, {
          palette: panelPaletteSelect?.value || panelDisplay(panelIndex).palette,
          displayMin: panelDisplayMinInput?.value || "",
          displayMax: panelDisplayMaxInput?.value || "",
        });
        refreshAllPanelControls();
        visiblePanelIndices().forEach((index) => schedulePreview(index, 0));
      });
    });
    panel.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      setStatus("Use Export & Provenance for a labelled screen view, polar PPI, georeferenced product, or raw source file.");
    });
    panel.addEventListener("wheel", (event) => {
      if (!state.panelMeta.has(Number(panel.dataset.panel))) return;
      if (event.target.closest(".panel-controls")) return;
      event.preventDefault();
      const point = panelPoint(panel, event);
      const delta = event.deltaY < 0 ? 0.35 : -0.35;
      zoomPanelAt(panel, point.x, point.y, delta);
    }, {passive: false});
    panel.addEventListener("mousedown", (event) => {
      if (event.button !== 0 || !state.panelMeta.has(Number(panel.dataset.panel))) return;
      if (event.target.closest(".panel-controls")) return;
      panel._dragState = {
        startX: event.clientX,
        startY: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        moved: false,
      };
      panel._panPreview = {dx: 0, dy: 0};
      panel.classList.add("is-panning");
    });
    panel.addEventListener("dblclick", (event) => {
      if (!state.panelMeta.has(Number(panel.dataset.panel))) return;
      event.preventDefault();
      const point = panelPoint(panel, event);
      zoomPanelAt(panel, point.x, point.y, event.shiftKey ? -0.7 : 0.7);
    });
    panel.addEventListener("touchstart", (event) => {
      if (!state.panelMeta.has(Number(panel.dataset.panel))) return;
      if (event.target.closest(".panel-controls")) return;
      if (event.touches.length === 1) {
        const point = touchPoint(panel, event.touches[0]);
        panel._touchState = {mode: "pan", lastX: point.x, lastY: point.y};
        panel._panPreview = {dx: 0, dy: 0};
        panel.classList.add("is-panning");
        event.preventDefault();
      } else if (event.touches.length === 2) {
        const midpoint = touchMidpoint(panel, event.touches[0], event.touches[1]);
        panel._touchState = {
          mode: "pinch",
          lastDistance: touchDistance(event.touches[0], event.touches[1]),
          x: midpoint.x,
          y: midpoint.y,
        };
        panel.classList.add("is-panning");
        event.preventDefault();
      }
    }, {passive: false});
    panel.addEventListener("touchmove", (event) => {
      const stateForTouch = panel._touchState;
      if (!stateForTouch || !state.panelMeta.has(Number(panel.dataset.panel))) return;
      if (stateForTouch.mode === "pan" && event.touches.length === 1) {
        const point = touchPoint(panel, event.touches[0]);
        previewPanelPan(panel, point.x - stateForTouch.lastX, point.y - stateForTouch.lastY);
        stateForTouch.lastX = point.x;
        stateForTouch.lastY = point.y;
        event.preventDefault();
      } else if (stateForTouch.mode === "pinch" && event.touches.length === 2) {
        const distance = touchDistance(event.touches[0], event.touches[1]);
        const midpoint = touchMidpoint(panel, event.touches[0], event.touches[1]);
        if (stateForTouch.lastDistance > 0 && distance > 0) {
          zoomPanelAt(panel, midpoint.x, midpoint.y, Math.log2(distance / stateForTouch.lastDistance));
        }
        stateForTouch.lastDistance = distance;
        stateForTouch.x = midpoint.x;
        stateForTouch.y = midpoint.y;
        event.preventDefault();
      }
    }, {passive: false});
    ["touchend", "touchcancel"].forEach((eventName) => {
      panel.addEventListener(eventName, () => {
        commitPanelPan(panel);
        delete panel._touchState;
        panel.classList.remove("is-panning");
      });
    });
    panel.addEventListener("mousemove", (event) => {
      if (panel._dragState) {
        const dx = event.clientX - panel._dragState.lastX;
        const dy = event.clientY - panel._dragState.lastY;
        const totalDx = event.clientX - panel._dragState.startX;
        const totalDy = event.clientY - panel._dragState.startY;
        if (Math.hypot(totalDx, totalDy) > 3) panel._dragState.moved = true;
        panel._dragState.lastX = event.clientX;
        panel._dragState.lastY = event.clientY;
        previewPanelPan(panel, dx, dy);
        return;
      }
      const rect = panel.getBoundingClientRect();
      const crosshair = panel.querySelector(".crosshair");
      crosshair.hidden = false;
      crosshair.style.left = `${event.clientX - rect.left}px`;
      crosshair.style.top = `${event.clientY - rect.top}px`;
      const hit = binFromMouse(panel, event);
      if (!hit) return;
      if (hit.outside) {
        panel.dataset.identifyRequestId = String(++state.identifyRequestSeq);
        setPanelReadout(panel, describeOutsideHit(hit));
        return;
      }
      setPanelReadout(panel, describeHit(hit));
      scheduleHoverIdentify(panel, hit);
    });
    panel.addEventListener("mouseleave", () => {
      panel.querySelector(".crosshair").hidden = true;
      const panelIndex = Number(panel.dataset.panel);
      const existing = state.identifyTimers.get(panelIndex);
      if (existing) clearTimeout(existing);
      state.identifyTimers.delete(panelIndex);
    });
    panel.addEventListener("mouseup", () => {
      if (panel._dragState?.moved) panel._suppressNextClick = true;
      commitPanelPan(panel);
      delete panel._dragState;
      panel.classList.remove("is-panning");
    });
    panel.addEventListener("click", async (event) => {
      if (panel._suppressNextClick) {
        delete panel._suppressNextClick;
        return;
      }
      delete panel._dragState;
      const hit = binFromMouse(panel, event);
      if (!hit || hit.outside || !panel.dataset.radar) return;
      try {
        const response = await api(identifyUrlForPanel(panel, hit.row, hit.column));
        const data = await response.json();
        setPanelReadout(panel, describeHit(hit, identifyValueText(data)));
      } catch (err) {
        setPanelReadout(panel, err.message, true);
      }
    });
  });
  window.addEventListener("resize", () => {
    panels().forEach((panel, index) => {
      const ppi = state.panelMeta.get(index);
      if (ppi) renderPanel(panel, ppi);
    });
  });
  window.addEventListener("mouseup", () => {
    panels().forEach((panel) => {
      if (panel._dragState?.moved) panel._suppressNextClick = true;
      commitPanelPan(panel);
      delete panel._dragState;
      panel.classList.remove("is-panning");
    });
  });
  window.addEventListener("keydown", handleKeyboardNavigation);
}

async function init() {
  attachEvents();
  setActivityStage("Server ready", "initialising catalog...");
  await loadCatalogSources();
  const statusOk = await loadStatus();
  if (!statusOk) return;
  await loadRadars();
  await loadRecentSelections();
  updateMp4ExportControls();
  setBasemap(el("basemapSelect").value);
  try {
    await searchCatalog();
  } catch (err) {
    if (!el("statusText").classList.contains("error")) {
      reportLoadError(err, "Initial catalog search failed");
    }
  }
}

init().catch((err) => reportLoadError(err, "Startup failed"));
