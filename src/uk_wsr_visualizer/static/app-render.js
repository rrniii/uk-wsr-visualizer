function ppiUrl(item, time, pulse = selectedPulse(item), quantity = selectedQuantity(item, pulse, time), dataset = optionalInputValue("datasetInput"), display = null) {
  const encodedQuantity = encodeURIComponent(quantity);
  const encodedPulse = encodeURIComponent(pulse);
  return `/api/ppi/${item.radar}/${item.date}/${encodedPulse}/${time}/${encodedQuantity}?${fieldParams(dataset, display).toString()}`;
}

function ppiFrameKey(item, time, pulse, quantity, dataset, display = null) {
  return ppiUrl(item, time, pulse, quantity, dataset, display);
}

function touchPpiFrameCacheKey(key) {
  state.ppiFrameCacheOrder = state.ppiFrameCacheOrder.filter((entry) => entry !== key);
  state.ppiFrameCacheOrder.push(key);
}

function cachedPpiFrame(key) {
  if (!state.ppiFrameCache.has(key)) return null;
  touchPpiFrameCacheKey(key);
  return state.ppiFrameCache.get(key);
}

function storePpiFrame(key, ppi) {
  state.ppiFrameCache.set(key, ppi);
  touchPpiFrameCacheKey(key);
  while (state.ppiFrameCacheOrder.length > state.maxPpiFrameCacheEntries) {
    const oldest = state.ppiFrameCacheOrder.shift();
    if (oldest) state.ppiFrameCache.delete(oldest);
  }
}

function clearPpiFrameCache() {
  state.ppiFrameCache.clear();
  state.ppiFrameCacheOrder = [];
  state.ppiFrameFetches.clear();
}

function frameRequestForPanel(panelIndex, timeOverride = "") {
  const selection = resolvePanelSelection(panelIndex);
  const item = selection.item;
  if (!item || !itemHasTimeMetadata(item)) return null;
  const quantity = selection.quantity || selectedQuantity(item);
  const pulse = selectedPulseForItem(item, quantity);
  if (!pulse || !quantity) return null;
  const times = availableTimesForSelection(item, pulse, quantity);
  if (!times.length) return null;
  const selectedTime = state.panelCount === 4 ? selection.time || el("timeSelect").value : el("timeSelect").value;
  const time = timeOverride || selectedTime || times[0];
  if (!times.includes(time)) return null;
  const elevations = availablePanelElevations(item, pulse, time, quantity);
  const elevationDatasets = elevations.map((record) => String(record.dataset));
  let dataset = selection.dataset || optionalInputValue("datasetInput") || "";
  if (dataset && elevationDatasets.length && !elevationDatasets.includes(String(dataset))) dataset = "";
  if (!dataset && elevationDatasets.length) dataset = elevationDatasets[0];
  return {item, pulse, time, quantity, dataset, times};
}

function prefetchPpiFrame(request) {
  if (!request) return;
  const key = ppiFrameKey(request.item, request.time, request.pulse, request.quantity, request.dataset);
  if (state.ppiFrameCache.has(key) || state.ppiFrameFetches.has(key)) return;
  fetchPpiFrame(key, ppiUrl(request.item, request.time, request.pulse, request.quantity, request.dataset)).catch((_err) => {
    // Prefetch failures are reported only if the user actually requests that frame.
  });
}

function prefetchRawFile(request) {
  if (!request || !rawVolumeItemHasFiles(request.item)) return;
  const key = `${itemKey(request.item)}:${request.pulse}:${request.time}`;
  if (state.rawPrefetches.has(key)) return;
  state.rawPrefetches.add(key);
  api(`/api/raw-cache/prefetch/${request.item.radar}/${request.item.date}/${encodeURIComponent(request.pulse)}/${request.time}`, {
    method: "POST",
  })
    .then((response) => response.json())
    .then((payload) => {
      if (payload.status === "cached") {
        if (!state.rawCacheByItem.has(itemKey(request.item))) state.rawCacheByItem.set(itemKey(request.item), new Set());
        state.rawCacheByItem.get(itemKey(request.item)).add(rawCacheTimeKey(request.pulse, request.time));
        refreshTimeControls();
      }
    })
    .catch((_err) => {
      // Raw prefetch is opportunistic. The requested frame will report any real download error.
    })
    .finally(() => state.rawPrefetches.delete(key));
}

function prefetchAdjacentFrames(direction = 1) {
  visiblePanelIndices().forEach((panelIndex) => {
    const current = frameRequestForPanel(panelIndex);
    if (!current || current.times.length < 2) return;
    const currentIndex = Math.max(0, current.times.indexOf(current.time));
    for (let offset = 1; offset <= state.animationPrefetchCount; offset += 1) {
      const nextIndex = (currentIndex + direction * offset + current.times.length) % current.times.length;
      const request = frameRequestForPanel(panelIndex, current.times[nextIndex]);
      prefetchRawFile(request);
      prefetchPpiFrame(request);
    }
  });
}

function identifyUrlForPanel(panel, row, column) {
  const quantity = encodeURIComponent(panel.dataset.quantity || selectedQuantity());
  const pulse = encodeURIComponent(panel.dataset.pulse || selectedPulse());
  const dataset = panel.dataset.fieldDataset || "";
  const params = new URLSearchParams({row: String(row), column: String(column), palette: el("paletteSelect").value});
  if (dataset) params.set("dataset", dataset);
  appendFilterParams(params);
  return `/api/identify/${panel.dataset.radar}/${panel.dataset.date}/${pulse}/${panel.dataset.time}/${quantity}?${params.toString()}`;
}

function applyOpacity() {
  panels().forEach((panel) => {
    const canvas = panel.querySelector(".ppi-canvas");
    canvas.style.opacity = el("opacityInput").value;
  });
}

function updateTimeStepOutput() {
  if (state.panelCount === 4 && !state.comparisonLinks.time) {
    const totals = visiblePanelIndices().map((index) => {
      const selection = panelSelection(index);
      const pulse = selectedPulseForItem(selection.item, selection.quantity);
      return availableTimesForSelection(selection.item, pulse, selection.quantity).length;
    });
    const canStep = totals.some((total) => total > 1);
    el("timeStepOutput").textContent = "per panel";
    el("timePrevButton").disabled = !canStep;
    el("timeNextButton").disabled = !canStep;
    return;
  }
  const select = el("timeSelect");
  const total = select.options.length;
  const current = total ? select.selectedIndex + 1 : 0;
  el("timeStepOutput").textContent = `${current} / ${total}`;
  const disabled = total < 2;
  el("timePrevButton").disabled = disabled;
  el("timeNextButton").disabled = disabled;
}

function cancelPendingPreviews() {
  state.previewTimers.forEach((timer) => clearTimeout(timer));
  state.previewTimers.clear();
  state.previewRequestSeq += 1;
  panels().forEach((panel) => {
    panel.dataset.previewRequestId = String(state.previewRequestSeq);
  });
}

function schedulePreview(panelIndex = 0, delayMs = 250, options = {}) {
  const existing = state.previewTimers.get(panelIndex);
  if (existing) clearTimeout(existing);
  const panel = panels()[panelIndex];
  if (panel) panel.dataset.previewRequestId = String(++state.previewRequestSeq);
  const timer = setTimeout(() => {
    state.previewTimers.delete(panelIndex);
    loadPpi(panelIndex, null, "", options).catch((err) => {
      const panel = panels()[panelIndex];
      if (panel) setPanelMessage(panel, err.message, true);
      setStatus(`Plot failed: ${err.message}`, true);
    });
  }, delayMs);
  state.previewTimers.set(panelIndex, timer);
}

function qcDisplaySummary(ppi) {
  const qc = ppi.qc || {};
  const noise = ppi.noise_floor || {};
  const qcCounts = Object.entries(qc.flag_counts || {})
    .filter(([, count]) => Number(count) > 0)
    .sort(([left], [right]) => left.localeCompare(right));
  if (qc.enabled && qcCounts.length) {
    const total = qcCounts.reduce((sum, [, count]) => sum + Number(count || 0), 0);
    return {
      short: `cleanup on (${total.toLocaleString()} gates)`,
      detail: `QC ${qc.version || "qc"}: ${qcCounts.map(([flag, count]) => `${flag} ${Number(count).toLocaleString()}`).join(", ")}`,
    };
  }
  if (noise.enabled) {
    const masked = Number(noise.masked_count || 0);
    return {
      short: masked ? `cleanup on (${masked.toLocaleString()} gates)` : "cleanup on",
      detail: `Noise-floor cleanup: ${noise.method || "estimated"} ${noise.operation || "mask"} +${fmtNumber(noise.margin_db, 1)} dB; ${masked.toLocaleString()} masked gates`,
    };
  }
  return {short: "cleanup off", detail: "No learned cleanup or noise-floor mask was applied."};
}

function shouldPreservePanelView(panel, item, options = {}) {
  if (options.recenter || options.preserveView === false || !panel?._mapTransform) return false;
  const previousRadar = panel.dataset.radar || "";
  return Boolean(previousRadar && item?.radar && previousRadar === item.radar);
}

function updatePanelAfterPpiLoad(panelIndex, panel, item, pulse, time, quantity, ppi) {
  const meta = ppi.metadata;
  panel.dataset.fieldDataset = meta.dataset || panel.dataset.fieldDataset || "";
  if (state.panelCount === 4) {
    setPanelSelection(panelIndex, {itemKey: itemKey(item), quantity, time, dataset: panel.dataset.fieldDataset, elevationDeg: Number(meta.elevation_deg)});
    refreshPanelControls(panelIndex);
  }
  const stats = ppi.stats || {};
  const quality = qcDisplaySummary(ppi);
  const title = `${itemLabel(item)} ${pulse} ${time} ${quantity} ${elevationLabel(meta.elevation_deg)}`;
  const detail = `${ppi.source_shape[0]} rays x ${ppi.source_shape[1]} gates, ${sweepLabel(meta)}, ${ppi.palette}, display=${fmtNumber(stats.scale_min, 1)} to ${fmtNumber(stats.scale_max, 1)}, ${quality.detail}`;
  const titleNode = panel.querySelector(".panel-title");
  titleNode.textContent = title;
  titleNode.title = `${title}\n${detail}`;
  const summaryNode = panel.querySelector(".panel-summary");
  if (summaryNode) {
    summaryNode.textContent = `${quantity} | ${elevationLabel(meta.elevation_deg)} | ${time}`;
    summaryNode.title = `${title}\n${detail}`;
  }
  clearPanelMessage(panel);
  const readout = panel.querySelector(".identify-readout");
  if (readout) {
    readout.textContent = `${ppi.source_shape[0]} x ${ppi.source_shape[1]} gates | ${sweepLabel(meta)} | ${quality.short}`;
    readout.title = detail;
    readout.classList.remove("error");
    readout.classList.add("compact");
  }
  setStatus(`Displayed ${itemLabel(item)} ${pulse} ${time} ${quantity} at ${sweepLabel(meta)}.`);
  if (panelIndex === 0) {
    recordRecentSelection(item, pulse, time, quantity, panel.dataset.fieldDataset);
  }
}

async function fetchPpiFrame(key, url) {
  const cached = cachedPpiFrame(key);
  if (cached) {
    pushPerformanceEvent({kind: "ppi-frame", operation: "memory frame cache", cache_hit: true, elapsed_ms: 0, key});
    return cached;
  }
  if (state.ppiFrameFetches.has(key)) return state.ppiFrameFetches.get(key);
  const task = (async () => {
    const start = performance.now();
    const response = await api(url);
    const parseStart = performance.now();
    const ppi = await response.json();
    const elapsed = performance.now() - start;
    pushPerformanceEvent({
      kind: "ppi-frame",
      operation: "fetch and parse frame",
      cache_hit: false,
      elapsed_ms: elapsed,
      parse_ms: performance.now() - parseStart,
      server_elapsed_ms: Number(response.headers.get("X-UK-WSR-Elapsed-Ms")) || null,
      backend: ppi._performance || null,
      key,
    });
    storePpiFrame(key, ppi);
    return ppi;
  })();
  state.ppiFrameFetches.set(key, task);
  try {
    return await task;
  } finally {
    state.ppiFrameFetches.delete(key);
  }
}

function resolvePanelSelection(panelIndex, selectionOverride = null) {
  let selection;
  if (selectionOverride && selectionOverride.item) {
    selection = selectionOverride;
  } else if (selectionOverride && selectionOverride.radar && selectionOverride.date) {
    selection = {item: selectionOverride};
  } else if (state.panelCount === 4) {
    selection = panelSelection(panelIndex);
  } else {
    selection = {
      item: state.activeItem,
      quantity: el("quantitySelect").value || DEFAULT_VARIABLE,
      dataset: optionalInputValue("datasetInput"),
    };
  }
  return selection;
}

function applyPanelFrame(panelIndex, panel, item, pulse, time, quantity, dataset, ppi, preserveView) {
  // The identity belongs to the pixels on screen, including while a replacement loads.
  panel.dataset.radar = item.radar;
  panel.dataset.date = item.date;
  panel.dataset.time = time;
  panel.dataset.pulse = pulse;
  panel.dataset.quantity = quantity;
  panel.dataset.fieldDataset = dataset;
  state.panelMeta.set(panelIndex, ppi);
  renderPanel(panel, ppi, {preserveView});
  updatePanelAfterPpiLoad(panelIndex, panel, item, pulse, time, quantity, ppi);
}

async function loadPpi(panelIndex = 0, selectionOverride = null, timeOverride = "", options = {}) {
  const loadStart = performance.now();
  const panel = panels()[panelIndex];
  if (!panel) return;
  // Own the panel before hydration, which can finish after a newer selection.
  const requestId = String(++state.previewRequestSeq);
  const source = state.catalogSourceId;
  const searchRequestId = state.searchRequestSeq;
  panel.dataset.previewRequestId = requestId;
  const isCurrent = () => state.catalogSourceId === source && state.searchRequestSeq === searchRequestId
    && panels()[panelIndex] === panel && panel.dataset.previewRequestId === requestId;
  const selection = resolvePanelSelection(panelIndex, selectionOverride);
  let item = selection.item;
  if (!item) {
    invalidatePanelRadar(panelIndex, panel);
    return;
  }
  const hasPreviousFrame = Boolean(state.panelMeta.get(panelIndex));
  const keepPrevious = options.keepPrevious !== false && hasPreviousFrame;
  const previousPanelState = {
    title: panel.querySelector(".panel-title")?.textContent || "",
    summary: panel.querySelector(".panel-summary")?.textContent || "",
    radar: panel.dataset.radar,
    date: panel.dataset.date,
    time: panel.dataset.time,
    pulse: panel.dataset.pulse,
    quantity: panel.dataset.quantity,
    fieldDataset: panel.dataset.fieldDataset,
  };
  try {
    item = await hydrateItemDetails(item, {isCurrent, panel});
    if (!isCurrent()) return;
    refreshRawCacheStatus(item, {isCurrent}).catch((_err) => {
      // Cache status is an optimization; do not interrupt plotting if it is unavailable.
    });
    const quantity = selection.quantity || selectedQuantity(item);
    const pulse = selectedPulseForItem(item, quantity);
    const availableTimes = availableTimesForSelection(item, pulse, quantity);
    const requestedTime = timeOverride || (state.panelCount === 4 ? selection.time || el("timeSelect").value : el("timeSelect").value) || availableTimes[0] || "";
    const time = state.panelCount === 4 && state.comparisonLinks.time
      ? requestedTime
      : (availableTimes.includes(requestedTime) ? requestedTime : availableTimes[0]);
    if (state.panelCount === 4 && state.comparisonLinks.time && requestedTime && !availableTimes.includes(requestedTime)) {
      invalidatePanelRadar(panelIndex, panel);
      panel.querySelector(".panel-title").textContent = `${itemLabel(item)} ${pulse || ""} ${requestedTime} ${quantity || ""}`.trim();
      setPanelMessage(panel, `Linked time ${requestedTime} is not available for ${itemLabel(item)} ${quantity}. Choose another linked time or panel item.`, true);
      return;
    }
    if (!time || !pulse || !quantity) {
      invalidatePanelRadar(panelIndex, panel);
      panel.querySelector(".panel-title").textContent = itemLabel(item);
      setPanelMessage(panel, `No available time for ${itemLabel(item)} with the selected pulse and variable.`, true);
      setStatus(`No available radar time for ${itemLabel(item)} with the selected pulse and variable.`, true);
      return;
    }
    const elevations = availablePanelElevations(item, pulse, time, quantity);
    const resolvedElevation = resolveElevationSelection(elevations, selection);
    const dataset = resolvedElevation.dataset;
    if (state.panelCount === 4) {
      setPanelSelection(panelIndex, {
        itemKey: itemKey(item),
        quantity,
        time,
        dataset,
        elevationDeg: resolvedElevation.elevationDeg,
      });
      refreshPanelControls(panelIndex);
    }

    const preserveView = shouldPreservePanelView(panel, item, options);
    const display = state.panelCount === 4 ? panelDisplay(panelIndex) : null;
    const frameKey = ppiFrameKey(item, time, pulse, quantity, dataset, display);
    const url = ppiUrl(item, time, pulse, quantity, dataset, display);
    const cached = cachedPpiFrame(frameKey);
    if (cached) {
      applyPanelFrame(panelIndex, panel, item, pulse, time, quantity, dataset, cached, preserveView);
      setPanelLoading(panel, "", false);
      setActivityStage("Frame rendered from memory cache", `${itemLabel(item)} ${pulse} ${time} ${quantity}`);
      pushPerformanceEvent({
        kind: "load-ppi",
        operation: "load complete",
        cache_hit: true,
        elapsed_ms: performance.now() - loadStart,
        panel: panelIndex,
        radar: item.radar,
        date: item.date,
        pulse,
        time,
        quantity,
        dataset,
      });
      return;
    }
    if (keepPrevious) {
      setPanelLoading(panel, "Loading next frame...", true);
      setStatus(`Loading next frame ${itemLabel(item)} ${pulse} ${time} ${quantity}...`);
      setActivityStage("Rendering", `loading next frame ${itemLabel(item)} ${pulse} ${time} ${quantity}`);
    } else {
      setPanelMessage(panel, "Loading raw PPI data from object store/cache...");
      setStatus(`Loading ${itemLabel(item)} ${pulse} ${time} ${quantity}...`);
      setActivityStage("Rendering", `${itemLabel(item)} ${pulse} ${time} ${quantity}`);
      clearPanel(panel);
    }

    const ppi = await fetchPpiFrame(frameKey, url);
    if (!isCurrent()) return;
    applyPanelFrame(panelIndex, panel, item, pulse, time, quantity, dataset, ppi, preserveView);
    const rawState = ppi._performance && ppi._performance.raw_cache_hit ? "raw file cached" : "frame rendered";
    setActivityStage("Frame rendered", `${itemLabel(item)} ${pulse} ${time} ${quantity}; ${rawState}`);
    pushPerformanceEvent({
      kind: "load-ppi",
      operation: "load complete",
      cache_hit: false,
      elapsed_ms: performance.now() - loadStart,
      panel: panelIndex,
      radar: item.radar,
      date: item.date,
      pulse,
      time,
      quantity,
      dataset,
      backend: ppi._performance || null,
    });
  } catch (err) {
    if (!isCurrent()) return;
    if (keepPrevious) {
      restorePanelFrameIdentity(panel, previousPanelState);
    } else {
      invalidatePanelRadar(panelIndex, panel);
    }
    setPanelMessage(
      panel,
      `Frame failed: ${err.message}. ${keepPrevious ? "The previous selection remains visible; it is not the requested frame." : ""}`.trim(),
      true,
    );
    setStatus(`Plot failed: ${err.message}`, true);
    setActivityStage("Frame failed", err.message, true, () => loadPpi(panelIndex, selectionOverride, timeOverride, options));
    throw err;
  } finally {
    if (isCurrent()) setPanelLoading(panel, "", false);
  }
}

function restorePanelFrameIdentity(panel, previous) {
  const title = panel.querySelector(".panel-title");
  if (title) title.textContent = previous.title || "";
  const summary = panel.querySelector(".panel-summary");
  if (summary) summary.textContent = previous.summary || "";
  ["radar", "date", "time", "pulse", "quantity", "fieldDataset"].forEach((key) => {
    const value = previous[key];
    if (value === undefined) {
      delete panel.dataset[key];
    } else {
      panel.dataset[key] = value;
    }
  });
}

function invalidatePanelRadar(panelIndex, panel) {
  state.panelMeta.delete(panelIndex);
  setPanelLoading(panel, "", false);
  const legend = panel.querySelector(".colour-legend");
  if (legend) legend.hidden = true;
  const crosshair = panel.querySelector(".crosshair");
  if (crosshair) crosshair.hidden = true;
  ["time", "pulse", "quantity", "fieldDataset"].forEach((key) => delete panel.dataset[key]);
  ["ppi-canvas", "map-overlay-canvas"].forEach((className) => {
    const canvas = panel.querySelector(`.${className}`);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  });
  const readout = panel.querySelector(".identify-readout");
  if (readout) {
    readout.textContent = "No radar frame is displayed for this selection.";
    readout.title = readout.textContent;
    readout.classList.remove("error");
    readout.classList.add("compact");
  }
}

function clearPanel(panel, resetMetadata = false) {
  syncPanelViewport(panel);
  setPanelLoading(panel, "", false);
  panel.querySelector(".tile-layer").innerHTML = "";
  panel.querySelector(".tile-layer").dataset.tileSignature = "";
  const legend = panel.querySelector(".colour-legend");
  if (legend) legend.hidden = true;
  state.panelMeta.delete(panels().indexOf(panel));
  if (resetMetadata) {
    panel.querySelector(".panel-title").textContent = "";
    delete panel.dataset.radar;
    delete panel.dataset.date;
    delete panel.dataset.time;
    delete panel.dataset.pulse;
    delete panel.dataset.quantity;
    delete panel.dataset.fieldDataset;
    delete panel.dataset.previewRequestId;
  }
  ["ppi-canvas", "map-overlay-canvas"].forEach((className) => {
    const canvas = panel.querySelector(`.${className}`);
    const ctx = canvas.getContext("2d");
    const viewport = panelViewportSize(panel);
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  });
}

function panelControlInset(panel) {
  if (state.panelCount !== 4) return 0;
  const controls = panel?.querySelector(".panel-controls");
  return controls && !controls.hidden ? Math.max(0, Math.ceil(controls.getBoundingClientRect().height)) : 0;
}

function syncPanelViewport(panel) {
  const inset = panelControlInset(panel);
  panel.style.setProperty("--panel-control-inset", `${inset}px`);
  return inset;
}

function panelViewportSize(panel) {
  const inset = syncPanelViewport(panel);
  return {
    width: Math.max(1, panel.clientWidth),
    height: Math.max(1, panel.clientHeight - inset),
    inset,
  };
}

function lonLatToWorld(lon, lat, zoom) {
  const scale = TILE_SIZE * 2 ** zoom;
  const sinLat = Math.sin((Math.max(-85.05113, Math.min(85.05113, lat)) * Math.PI) / 180);
  return {
    x: ((lon + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
  };
}

function worldToLonLat(x, y, zoom) {
  const scale = TILE_SIZE * 2 ** zoom;
  const lon = (x / scale) * 360 - 180;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  const lat = (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  return {lon, lat};
}

function chooseMapTransform(panel, metadata) {
  const {width, height} = panelViewportSize(panel);
  const [west, south, east, north] = metadata.geographic_bbox;
  const nw0 = lonLatToWorld(west, north, 0);
  const se0 = lonLatToWorld(east, south, 0);
  const bboxWidth0 = Math.max(1e-6, Math.abs(se0.x - nw0.x));
  const bboxHeight0 = Math.max(1e-6, Math.abs(se0.y - nw0.y));
  const fitScale = Math.min((width * 0.96) / bboxWidth0, (height * 0.96) / bboxHeight0);
  const zoom = Math.max(3, Math.min(12.5, Math.log2(fitScale)));
  const tileZoom = Math.max(0, Math.min(19, Math.ceil(zoom)));
  const tileScale = 2 ** (zoom - tileZoom);
  const center = lonLatToWorld(metadata.longitude, metadata.latitude, zoom);
  return {
    zoom,
    tileZoom,
    tileScale,
    width,
    height,
    centerX: center.x,
    centerY: center.y,
    left: center.x - width / 2,
    top: center.y - height / 2,
  };
}

function updateTileTransform(transform) {
  transform.tileZoom = Math.max(0, Math.min(19, Math.ceil(transform.zoom)));
  transform.tileScale = 2 ** (transform.zoom - transform.tileZoom);
  transform.centerX = transform.left + transform.width / 2;
  transform.centerY = transform.top + transform.height / 2;
  return transform;
}

function resizeMapTransform(panel, transform) {
  const {width, height} = panelViewportSize(panel);
  if (width === transform.width && height === transform.height) return updateTileTransform(transform);
  const center = worldToLonLat(transform.left + transform.width / 2, transform.top + transform.height / 2, transform.zoom);
  const centerWorld = lonLatToWorld(center.lon, center.lat, transform.zoom);
  return updateTileTransform({
    ...transform,
    width,
    height,
    left: centerWorld.x - width / 2,
    top: centerWorld.y - height / 2,
  });
}

function projectLonLat(lon, lat, transform) {
  const point = lonLatToWorld(lon, lat, transform.zoom);
  return {x: point.x - transform.left, y: point.y - transform.top};
}

function pixelToLonLat(x, y, transform) {
  return worldToLonLat(transform.left + x, transform.top + y, transform.zoom);
}

function renderTiles(panel, transform) {
  const layer = panel.querySelector(".tile-layer");
  const basemap = el("basemapSelect").value;
  const tileScale = transform.tileScale || 1;
  const tileZoom = transform.tileZoom ?? Math.round(transform.zoom);
  const leftAtTileZoom = transform.left / tileScale;
  const topAtTileZoom = transform.top / tileScale;
  const minTileX = Math.floor(leftAtTileZoom / TILE_SIZE);
  const maxTileX = Math.floor((leftAtTileZoom + transform.width / tileScale) / TILE_SIZE);
  const minTileY = Math.floor(topAtTileZoom / TILE_SIZE);
  const maxTileY = Math.floor((topAtTileZoom + transform.height / tileScale) / TILE_SIZE);
  const signature = [
    basemap,
    tileZoom,
    Math.round(minTileX),
    Math.round(maxTileX),
    Math.round(minTileY),
    Math.round(maxTileY),
    Math.round(transform.left),
    Math.round(transform.top),
    Math.round(transform.width),
    Math.round(transform.height),
  ].join(":");
  if (layer.dataset.tileSignature === signature) return;
  layer.dataset.tileSignature = signature;
  layer.innerHTML = "";
  if (basemap !== "osm") return;
  const tileLimit = 2 ** tileZoom;
  for (let tx = minTileX; tx <= maxTileX; tx += 1) {
    for (let ty = minTileY; ty <= maxTileY; ty += 1) {
      if (ty < 0 || ty >= tileLimit) continue;
      const wrappedX = ((tx % tileLimit) + tileLimit) % tileLimit;
      const image = document.createElement("img");
      image.alt = "";
      image.crossOrigin = "anonymous";
      image.decoding = "async";
      image.loading = "lazy";
      image.src = `https://tile.openstreetmap.org/${tileZoom}/${wrappedX}/${ty}.png`;
      image.style.left = `${tx * TILE_SIZE * tileScale - transform.left}px`;
      image.style.top = `${ty * TILE_SIZE * tileScale - transform.top}px`;
      image.style.width = `${TILE_SIZE * tileScale}px`;
      image.style.height = `${TILE_SIZE * tileScale}px`;
      layer.appendChild(image);
    }
  }
}

function geographicPoint(metadata, xM, yM) {
  const lat0 = (metadata.latitude * Math.PI) / 180;
  const lon0 = (metadata.longitude * Math.PI) / 180;
  const rho = Math.hypot(xM, yM);
  if (rho === 0) return {lon: metadata.longitude, lat: metadata.latitude};
  const c = rho / EARTH_RADIUS_M;
  const lat = Math.asin(Math.cos(c) * Math.sin(lat0) + (yM * Math.sin(c) * Math.cos(lat0)) / rho);
  const lon = lon0 + Math.atan2(xM * Math.sin(c), rho * Math.cos(lat0) * Math.cos(c) - yM * Math.sin(lat0) * Math.sin(c));
  return {lon: (lon * 180) / Math.PI, lat: (lat * 180) / Math.PI};
}

function radarPoint(metadata, rangeM, azimuthDeg) {
  const az = (azimuthDeg * Math.PI) / 180;
  return geographicPoint(metadata, rangeM * Math.sin(az), rangeM * Math.cos(az));
}

function metersPerPixel(metadata, zoom) {
  return (156543.03392 * Math.cos((metadata.latitude * Math.PI) / 180)) / 2 ** zoom;
}

function parseCustomStops(spec) {
  const stops = [];
  (spec || "").split(",").forEach((entry) => {
    const raw = entry.trim();
    if (!raw || !raw.includes(":")) return;
    const [posText, colorText] = raw.split(":", 2);
    const color = colorText.trim().replace("#", "");
    if (color.length !== 6) return;
    stops.push({
      position: Math.max(0, Math.min(1, Number(posText.trim()))),
      rgb: [
        parseInt(color.slice(0, 2), 16),
        parseInt(color.slice(2, 4), 16),
        parseInt(color.slice(4, 6), 16),
      ],
    });
  });
  stops.sort((a, b) => a.position - b.position);
  if (!stops.length) return [
    {position: 0, rgb: [0, 0, 0]},
    {position: 0.5, rgb: [40, 180, 80]},
    {position: 1, rgb: [255, 255, 255]},
  ];
  if (stops[0].position > 0) stops.unshift({position: 0, rgb: stops[0].rgb});
  if (stops[stops.length - 1].position < 1) stops.push({position: 1, rgb: stops[stops.length - 1].rgb});
  return stops;
}

function interpolateColor(value, stops) {
  const normalized = value / 255;
  let left = stops[0];
  let right = stops[stops.length - 1];
  for (let index = 1; index < stops.length; index += 1) {
    if (normalized <= stops[index].position) {
      right = stops[index];
      left = stops[index - 1];
      break;
    }
  }
  const span = Math.max(0.0001, right.position - left.position);
  const t = Math.max(0, Math.min(1, (normalized - left.position) / span));
  return left.rgb.map((channel, index) => Math.round(channel + (right.rgb[index] - channel) * t));
}

const STANDARD_PALETTES = {
  homeyer: [
    [0.00, [245, 245, 245]],
    [0.08, [120, 200, 255]],
    [0.18, [20, 80, 220]],
    [0.30, [25, 170, 60]],
    [0.43, [250, 230, 30]],
    [0.56, [245, 125, 20]],
    [0.68, [210, 25, 35]],
    [0.80, [185, 35, 160]],
    [0.91, [250, 250, 250]],
    [1.00, [120, 70, 40]],
  ],
  budrd18: [
    [0.00, [5, 48, 97]],
    [0.18, [33, 102, 172]],
    [0.34, [146, 197, 222]],
    [0.50, [247, 247, 247]],
    [0.66, [244, 165, 130]],
    [0.82, [178, 24, 43]],
    [1.00, [103, 0, 31]],
  ],
  refdiff: [
    [0.00, [49, 54, 149]],
    [0.20, [69, 117, 180]],
    [0.40, [171, 217, 233]],
    [0.50, [255, 255, 191]],
    [0.60, [254, 224, 144]],
    [0.80, [244, 109, 67]],
    [1.00, [165, 0, 38]],
  ],
  nws_spw: [
    [0.00, [255, 255, 255]],
    [0.15, [153, 204, 255]],
    [0.30, [76, 153, 255]],
    [0.45, [76, 204, 76]],
    [0.60, [255, 230, 0]],
    [0.78, [255, 128, 0]],
    [1.00, [180, 0, 0]],
  ],
  wild25: [
    [0.00, [68, 1, 84]],
    [0.18, [59, 82, 139]],
    [0.34, [33, 145, 140]],
    [0.50, [94, 201, 98]],
    [0.66, [253, 231, 37]],
    [0.82, [241, 135, 33]],
    [1.00, [180, 40, 120]],
  ],
  theodore16: [
    [0.00, [49, 54, 149]],
    [0.20, [69, 117, 180]],
    [0.40, [116, 173, 209]],
    [0.50, [255, 255, 191]],
    [0.64, [254, 224, 144]],
    [0.80, [244, 109, 67]],
    [1.00, [165, 0, 38]],
  ],
  rrate11: [
    [0.00, [247, 252, 245]],
    [0.14, [199, 233, 192]],
    [0.28, [116, 196, 118]],
    [0.42, [49, 163, 84]],
    [0.58, [254, 224, 144]],
    [0.74, [253, 141, 60]],
    [1.00, [189, 0, 38]],
  ],
  carbone17: [
    [0.00, [38, 38, 38]],
    [0.18, [88, 88, 88]],
    [0.36, [150, 150, 150]],
    [0.52, [210, 210, 210]],
    [0.68, [150, 200, 255]],
    [0.84, [60, 140, 220]],
    [1.00, [10, 65, 140]],
  ],
};

function standardPaletteStops(name) {
  const key = String(name || "").toLowerCase();
  const rawStops = STANDARD_PALETTES[key];
  if (!rawStops) return null;
  return rawStops.map(([position, rgb]) => ({position, rgb}));
}

function paletteColor(value, palette, customStops) {
  const standardStops = standardPaletteStops(palette);
  if (standardStops) return interpolateColor(value, standardStops);
  if (palette === "custom") return interpolateColor(value, customStops);
  if (palette === "thermal") {
    return [
      value,
      Math.max(0, Math.min(255, Math.round(value * 1.35 - 75))),
      Math.max(0, Math.min(255, Math.round(255 - value * 1.2))),
    ];
  }
  if (palette === "velocity") {
    return [
      Math.max(0, Math.min(255, value * 2 - 255)),
      Math.max(0, Math.min(255, 255 - Math.abs(value - 128) * 2)),
      Math.max(0, Math.min(255, 255 - value * 2)),
    ];
  }
  if (palette === "radar") {
    return [
      Math.max(0, Math.min(255, value * 2 - 120)),
      Math.max(0, Math.min(255, value * 2)),
      Math.max(0, Math.min(255, 180 - value * 2)),
    ];
  }
  return [value, value, value];
}

function quantityUnit(quantity) {
  const key = String(quantity || "").toUpperCase();
  if (["DBZ", "DBZH", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"].includes(key)) return "dBZ";
  if (key.startsWith("VRAD") || key.includes("VEL")) return "m/s";
  if (key.startsWith("WRAD") || key.includes("WIDTH")) return "m/s";
  if (key === "ZDR" || key.includes("DIFFERENTIAL_REFLECTIVITY")) return "dB";
  if (key === "PHIDP" || key === "UPHIDP" || key.includes("PHASE")) return "deg";
  if (key === "KDP" || key.includes("SPECIFIC_DIFFERENTIAL_PHASE")) return "deg/km";
  if (key === "RHOHV" || key === "SQI" || key === "QIND") return "unitless";
  if (key === "RATE" || key === "RR" || key.includes("RAIN")) return "mm/h";
  if (key === "SNR" || key === "DBM") return "dB";
  return "";
}

function legendValue(value, span) {
  if (!Number.isFinite(value)) return "n/a";
  const absSpan = Math.abs(span);
  if (absSpan >= 50) return String(Math.round(value));
  if (absSpan >= 5) return Number(value).toFixed(1);
  return Number(value).toFixed(2);
}

function legendGradient(palette, paletteStops) {
  const customStops = parseCustomStops(paletteStops);
  const entries = [];
  for (let index = 0; index <= 16; index += 1) {
    const scaled = Math.round((index / 16) * 255);
    const color = paletteColor(scaled, palette, customStops);
    entries.push(`rgb(${color[0]}, ${color[1]}, ${color[2]}) ${Math.round((index / 16) * 100)}%`);
  }
  return `linear-gradient(to top, ${entries.join(", ")})`;
}

function renderLegend(panel, ppi) {
  const legend = panel.querySelector(".colour-legend");
  if (!legend) return;
  const stats = ppi.stats || {};
  const scaleMin = Number(stats.scale_min);
  const scaleMax = Number(stats.scale_max);
  if (!Number.isFinite(scaleMin) || !Number.isFinite(scaleMax)) {
    legend.hidden = true;
    return;
  }
  const quantity = panel.dataset.quantity || selectedQuantity();
  const unit = quantityUnit(quantity);
  const span = scaleMax - scaleMin;
  const midpoint = scaleMin + span / 2;
  const title = document.createElement("div");
  title.className = "legend-title";
  title.textContent = `${quantity || "Field"} (${ppi.palette})`;

  const ramp = document.createElement("div");
  ramp.className = "legend-ramp";
  ramp.style.background = legendGradient(ppi.palette, ppi.palette_stops);

  const ticks = document.createElement("div");
  ticks.className = "legend-ticks";
  [scaleMax, midpoint, scaleMin].forEach((value) => {
    const tick = document.createElement("span");
    tick.textContent = `${legendValue(value, span)}${unit ? ` ${unit}` : ""}`;
    ticks.append(tick);
  });

  legend.replaceChildren(title, ramp, ticks);
  legend.hidden = false;
}

function renderPpi(panel, ppi, transform) {
  const canvas = panel.querySelector(".ppi-canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = transform.width;
  canvas.height = transform.height;
  canvas.style.opacity = el("opacityInput").value;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const metadata = ppi.metadata;
  const customStops = parseCustomStops(ppi.palette_stops);
  const azStep = 360 / Math.max(1, metadata.nrays);
  const gateEdges = ppi.gate_edges || {};
  const azimuthEdges = gateEdges.azimuth_deg || [];
  const rangeEdges = gateEdges.range_m || [];
  if (azimuthEdges.length === ppi.rows + 1 && rangeEdges.length === ppi.columns + 1) {
    renderPpiGateMesh(ctx, ppi, transform, customStops, azimuthEdges, rangeEdges);
    return;
  }
  const cellSize = Math.max(1, Math.min(5, (metadata.rscale_m * ppi.column_stride) / metersPerPixel(metadata, transform.zoom)));
  for (let row = 0; row < ppi.rows; row += 1) {
    const sourceRow = Math.min(metadata.nrays - 1, row * ppi.row_stride + (ppi.row_stride - 1) / 2);
    const azimuth = (sourceRow + 0.5) * azStep;
    for (let column = 0; column < ppi.columns; column += 1) {
      if (!ppi.valid[row][column]) continue;
      const sourceColumn = Math.min(metadata.nbins - 1, column * ppi.column_stride + (ppi.column_stride - 1) / 2);
      const rangeM = metadata.rstart_km * 1000 + (sourceColumn + 0.5) * metadata.rscale_m;
      const geo = radarPoint(metadata, rangeM, azimuth);
      const point = projectLonLat(geo.lon, geo.lat, transform);
      if (point.x < -cellSize || point.y < -cellSize || point.x > canvas.width + cellSize || point.y > canvas.height + cellSize) continue;
      const color = paletteColor(ppi.scaled[row][column], ppi.palette, customStops);
      ctx.fillStyle = `rgb(${color[0]},${color[1]},${color[2]})`;
      ctx.fillRect(point.x - cellSize / 2, point.y - cellSize / 2, cellSize, cellSize);
    }
  }
}

function renderPpiGateMesh(ctx, ppi, transform, customStops, azimuthEdges, rangeEdges) {
  const metadata = ppi.metadata;
  for (let row = 0; row < ppi.rows; row += 1) {
    const az0 = azimuthEdges[row];
    const az1 = azimuthEdges[row + 1];
    for (let column = 0; column < ppi.columns; column += 1) {
      if (!ppi.valid[row][column]) continue;
      const r0 = rangeEdges[column];
      const r1 = rangeEdges[column + 1];
      const c0 = radarPoint(metadata, r0, az0);
      const c1 = radarPoint(metadata, r1, az0);
      const c2 = radarPoint(metadata, r1, az1);
      const c3 = radarPoint(metadata, r0, az1);
      const corners = [
        projectLonLat(c0.lon, c0.lat, transform),
        projectLonLat(c1.lon, c1.lat, transform),
        projectLonLat(c2.lon, c2.lat, transform),
        projectLonLat(c3.lon, c3.lat, transform),
      ];
      if (!polygonIntersectsCanvas(corners, ctx.canvas.width, ctx.canvas.height)) continue;
      const color = paletteColor(ppi.scaled[row][column], ppi.palette, customStops);
      ctx.fillStyle = `rgb(${color[0]},${color[1]},${color[2]})`;
      ctx.strokeStyle = ctx.fillStyle;
      ctx.lineWidth = 0.75;
      ctx.beginPath();
      ctx.moveTo(corners[0].x, corners[0].y);
      ctx.lineTo(corners[1].x, corners[1].y);
      ctx.lineTo(corners[2].x, corners[2].y);
      ctx.lineTo(corners[3].x, corners[3].y);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  }
}

function polygonIntersectsCanvas(points, width, height) {
  const finite = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!finite.length) return false;
  const xs = finite.map((point) => point.x);
  const ys = finite.map((point) => point.y);
  return Math.max(...xs) >= 0 && Math.min(...xs) <= width && Math.max(...ys) >= 0 && Math.min(...ys) <= height;
}

function drawLine(ctx, points) {
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
}

function renderOverlay(panel, ppi, transform) {
  const canvas = panel.querySelector(".map-overlay-canvas");
  const ctx = canvas.getContext("2d");
  canvas.width = transform.width;
  canvas.height = transform.height;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const metadata = ppi.metadata;
  const dark = el("basemapSelect").value === "dark";
  ctx.strokeStyle = dark ? "rgba(255,255,255,0.45)" : "rgba(20,35,45,0.42)";
  ctx.fillStyle = dark ? "rgba(255,255,255,0.82)" : "rgba(20,35,45,0.8)";
  ctx.lineWidth = 1;
  const showRangeRings = !el("rangeRingsInput") || el("rangeRingsInput").checked;
  if (showRangeRings) {
    const requestedStepKm = Number(optionalInputValue("rangeRingSpacingInput"));
    const ringStepM = Number.isFinite(requestedStepKm) && requestedStepKm > 0
      ? requestedStepKm * 1000
      : metadata.max_range_m > 180000 ? 50000 : 25000;
    for (let rangeM = ringStepM; rangeM <= metadata.max_range_m; rangeM += ringStepM) {
      ctx.beginPath();
      const points = [];
      for (let az = 0; az <= 360; az += 4) {
        const geo = radarPoint(metadata, rangeM, az);
        points.push(projectLonLat(geo.lon, geo.lat, transform));
      }
      drawLine(ctx, points);
      ctx.stroke();
      const labelGeo = radarPoint(metadata, rangeM, 90);
      const label = projectLonLat(labelGeo.lon, labelGeo.lat, transform);
      ctx.fillText(`${Math.round(rangeM / 1000)} km`, label.x + 4, label.y - 4);
    }
    [0, 45, 90, 135, 180, 225, 270, 315].forEach((az) => {
      const center = projectLonLat(metadata.longitude, metadata.latitude, transform);
      const edgeGeo = radarPoint(metadata, metadata.max_range_m, az);
      const edge = projectLonLat(edgeGeo.lon, edgeGeo.lat, transform);
      ctx.beginPath();
      ctx.moveTo(center.x, center.y);
      ctx.lineTo(edge.x, edge.y);
      ctx.stroke();
    });
  }
  const radar = projectLonLat(metadata.longitude, metadata.latitude, transform);
  ctx.fillStyle = "#111827";
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(radar.x, radar.y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function renderPanel(panel, ppi, options = {}) {
  const start = performance.now();
  syncPanelViewport(panel);
  const preserveView = options.preserveView !== false;
  const transform = preserveView && panel._mapTransform ? resizeMapTransform(panel, panel._mapTransform) : chooseMapTransform(panel, ppi.metadata);
  panel._mapTransform = transform;
  const tilesStart = performance.now();
  renderTiles(panel, transform);
  const ppiStart = performance.now();
  renderPpi(panel, ppi, transform);
  const overlayStart = performance.now();
  renderOverlay(panel, ppi, transform);
  const legendStart = performance.now();
  renderLegend(panel, ppi);
  pushPerformanceEvent({
    kind: "render",
    operation: "render panel",
    elapsed_ms: performance.now() - start,
    tiles_ms: ppiStart - tilesStart,
    ppi_canvas_ms: overlayStart - ppiStart,
    overlay_ms: legendStart - overlayStart,
    legend_ms: performance.now() - legendStart,
    rows: ppi.rows,
    columns: ppi.columns,
    source_shape: ppi.source_shape,
    radar: panel.dataset.radar || "",
    date: panel.dataset.date || "",
    time: panel.dataset.time || "",
    quantity: panel.dataset.quantity || "",
  });
}

function syncLinkedViewFromPanel(sourcePanel) {
  if (state.panelCount !== 4 || !state.comparisonLinks.view || !sourcePanel?._mapTransform) return;
  state.pendingLinkedViewSource = sourcePanel;
  if (state.linkedViewAnimationFrame) return;
  state.linkedViewAnimationFrame = requestAnimationFrame(() => {
    const pendingSource = state.pendingLinkedViewSource;
    state.linkedViewAnimationFrame = 0;
    state.pendingLinkedViewSource = null;
    syncLinkedViewFromPanelNow(pendingSource);
  });
}

function syncLinkedViewFromPanelNow(sourcePanel) {
  if (state.panelCount !== 4 || !state.comparisonLinks.view || !sourcePanel?._mapTransform) return;
  const sourceTransform = sourcePanel._mapTransform;
  const center = pixelToLonLat(sourceTransform.width / 2, sourceTransform.height / 2, sourceTransform);
  visiblePanelIndices().forEach((index) => {
    const panel = panels()[index];
    if (!panel || panel === sourcePanel) return;
    const ppi = state.panelMeta.get(index);
    if (!ppi) return;
    const {width, height} = panelViewportSize(panel);
    const world = lonLatToWorld(center.lon, center.lat, sourceTransform.zoom);
    panel._mapTransform = updateTileTransform({
      ...sourceTransform,
      width,
      height,
      left: world.x - width / 2,
      top: world.y - height / 2,
    });
    renderPanel(panel, ppi);
  });
}

async function stepFrame(delta, loadImmediately = false) {
  if (state.panelCount === 4 && !state.comparisonLinks.time) {
    visiblePanelIndices().forEach((index) => {
      const selection = panelSelection(index);
      const pulse = selectedPulseForItem(selection.item, selection.quantity);
      const times = availableTimesForSelection(selection.item, pulse, selection.quantity);
      if (times.length < 2) return;
      const currentIndex = Math.max(0, times.indexOf(selection.time));
      const nextIndex = (currentIndex + delta + times.length) % times.length;
      setPanelSelection(index, {time: times[nextIndex]});
    });
    updateTimeStepOutput();
    refreshAllPanelControls();
    if (loadImmediately) await loadVisiblePpisNow({keepPrevious: true, preserveView: true});
    else scheduleVisiblePreviews(0, {keepPrevious: true, preserveView: true});
    prefetchAdjacentFrames(delta >= 0 ? 1 : -1);
    return;
  }
  const select = el("timeSelect");
  if (!select.options.length) return;
  const next = (select.selectedIndex + delta + select.options.length) % select.options.length;
  select.selectedIndex = next;
  updateTimeStepOutput();
  refreshElevationControls();
  refreshAllPanelControls();
  if (loadImmediately) await loadVisiblePpisNow({keepPrevious: true, preserveView: true});
  else scheduleVisiblePreviews(0, {keepPrevious: true, preserveView: true});
  prefetchAdjacentFrames(delta >= 0 ? 1 : -1);
}

function stepElevation(delta) {
  const select = el("datasetInput");
  if (!select || select.disabled || select.options.length < 2) return;
  select.selectedIndex = (select.selectedIndex + delta + select.options.length) % select.options.length;
  if (state.panelCount === 4) {
    setPanelSelection(0, {dataset: optionalInputValue("datasetInput")});
    syncLinkedPanelSelection(0, {dataset: optionalInputValue("datasetInput")});
    refreshAllPanelControls();
  }
  scheduleVisiblePreviews(0);
}

async function stepItem(delta) {
  const select = el("itemSelect");
  if (!select || select.options.length < 2) return;
  select.selectedIndex = (select.selectedIndex + delta + select.options.length) % select.options.length;
  state.activeItem = state.items[Number(select.value)];
  if (!await prepareActiveItemForDisplay()) return;
  if (state.panelCount === 4) {
    setPanelSelection(0, {itemKey: itemKey(state.activeItem), dataset: optionalInputValue("datasetInput")});
    refreshAllPanelControls();
  }
  scheduleVisiblePreviews(0);
}

function resetPanelView(panel, sync = true) {
  const index = Number(panel.dataset.panel);
  const ppi = state.panelMeta.get(index);
  if (!ppi) return;
  delete panel._mapTransform;
  renderPanel(panel, ppi, {preserveView: false});
  if (sync) syncLinkedViewFromPanel(panel);
}

function fitVisiblePanels() {
  // Each comparison panel fits around its own radar. Do not let the last panel
  // overwrite the other three merely because the view link happens to be on.
  visiblePanelIndices().forEach((index) => resetPanelView(panels()[index], false));
}

async function playLoop() {
  if (!state.playing || state.animationBusy) return;
  state.animationBusy = true;
  try {
    el("animationStatus").textContent = "Loading next animation frame without clearing the current view...";
    await stepFrame(1, true);
    el("animationStatus").textContent = `Loaded frame ${el("timeStepOutput").textContent}; preloading upcoming frames.`;
    prefetchAdjacentFrames(1);
  } catch (err) {
    el("animationStatus").textContent = `Animation paused: ${err.message}`;
    setStatus(`Animation paused: ${err.message}`, true);
    state.playing = false;
    el("playButton").textContent = "Play";
  } finally {
    state.animationBusy = false;
  }
  if (state.playing) {
    state.timer = setTimeout(playLoop, Number(el("delayInput").value) || 600);
  }
}

function togglePlay() {
  state.playing = !state.playing;
  el("playButton").textContent = state.playing ? "Pause" : "Play";
  if (state.playing) {
    clearTimeout(state.timer);
    prefetchAdjacentFrames(1);
    playLoop();
  } else {
    clearTimeout(state.timer);
    el("animationStatus").textContent = "Animation paused.";
  }
}

function setPanelCount(count) {
  state.panelCount = count;
  const grid = el("panelGrid");
  grid.classList.toggle("one-panel", count === 1);
  grid.classList.toggle("four-panel", count === 4);
  document.querySelectorAll(".view-button").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.panelCount) === count);
  });
  updateDisplayControlMode();
  updateComparisonSidebarControlMode();
  if (count === 4 && state.items.length) {
    initializePanelDisplays();
    initializePanelSelections();
    refreshAllPanelControls();
    refreshTimeControls();
    panels().forEach((_panel, index) => {
      loadPpi(index).catch((err) => {
        setPanelMessage(panels()[index], err.message, true);
        setStatus(`Plot failed: ${err.message}`, true);
      });
    });
  } else {
    refreshTimeControls();
    schedulePreview(0, 0);
  }
}

function setBasemap(value) {
  el("panelGrid").dataset.basemap = value;
  panels().forEach((panel, index) => {
    const ppi = state.panelMeta.get(index);
    if (ppi) renderPanel(panel, ppi);
  });
}

function fmtNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
  return Number(value).toFixed(digits);
}

function elevationLabel(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "elev n/a";
  return `elev ${Number(value).toFixed(2)} deg`;
}

function valueLabel(quantity, value) {
  if (value === null || value === undefined) return `${quantity || "value"}=n/a`;
  const unit = quantityUnit(quantity);
  const numeric = Number(value);
  const formatted = Number.isFinite(numeric) ? fmtNumber(numeric, Math.abs(numeric) >= 100 ? 1 : 2) : String(value);
  return `${quantity || "value"}=${formatted}${unit ? ` ${unit}` : ""}`;
}

function identifyValueText(data) {
  if (data.masked_by_noise_floor) return `${data.quantity || "value"}=masked by cleanup filter`;
  return valueLabel(data.quantity, data.value);
}

function updatePointerFieldState() {
  document.querySelectorAll(".pointer-field-toggle").forEach((input) => {
    state.pointerFields[input.value] = input.checked;
  });
}

function applyPointerFieldState() {
  document.querySelectorAll(".pointer-field-toggle").forEach((input) => {
    input.checked = state.pointerFields[input.value] !== false;
  });
}

function beamHeightM(rangeM, elevationDeg, siteHeightM = 0) {
  const range = Number(rangeM);
  const elevation = Number(elevationDeg);
  if (!Number.isFinite(range) || !Number.isFinite(elevation)) return null;
  const effectiveEarthRadiusM = (4 / 3) * EARTH_RADIUS_M;
  const theta = (elevation * Math.PI) / 180;
  const height = Math.sqrt(
    range ** 2 + effectiveEarthRadiusM ** 2 + 2 * range * effectiveEarthRadiusM * Math.sin(theta),
  ) - effectiveEarthRadiusM + (Number(siteHeightM) || 0);
  return Number.isFinite(height) ? height : null;
}

function captureFrame() {
  const panel = panels()[0];
  const output = composePanelScreenshot(panel, true);
  if (!output) return;
  const capture = document.createElement("img");
  capture.src = output.toDataURL("image/png");
  capture.alt = "Captured radar PPI";
  el("captures").prepend(capture);
  document.querySelector(".captures").classList.add("has-captures");
  canvasBlob(output)
    .then((blob) => downloadBlob(`uk-wsr-capture-${Date.now()}.png`, blob, "image/png"))
    .catch((err) => setStatus(`Could not save map image: ${err.message}`, true));
}

function composePanelScreenshot(panel, includeTiles = true) {
  const source = panel?.querySelector(".ppi-canvas");
  if (!source || !source.width || !source.height) return null;
  const output = document.createElement("canvas");
  const legendWidth = 190;
  const headerHeight = 50;
  output.width = source.width + legendWidth;
  output.height = source.height + headerHeight;
  const ctx = output.getContext("2d");
  const ppi = state.panelMeta.get(Number(panel.dataset.panel));
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, output.width, output.height);
  ctx.fillStyle = "#1d2730";
  ctx.fillRect(0, 0, output.width, headerHeight);
  ctx.fillStyle = "#ffffff";
  ctx.font = "600 16px system-ui, sans-serif";
  ctx.fillText(panel.querySelector(".panel-title")?.textContent || "UK WSR Visualizer", 12, 22);
  ctx.font = "12px system-ui, sans-serif";
  const selectionText = [
    panel.dataset.radar,
    formatDate(panel.dataset.date),
    panel.dataset.pulse,
    panel.dataset.time,
    panel.dataset.quantity,
    panel.dataset.fieldDataset,
  ].filter(Boolean).join(" ");
  ctx.fillText(selectionText || "Screen view export: map, radar PPI, range rings and legend", 12, 40);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, headerHeight, source.width, source.height);
  ctx.clip();
  ctx.fillStyle = el("basemapSelect").value === "dark" ? "#1d2730" : "#dfe6ec";
  ctx.fillRect(0, headerHeight, source.width, source.height);
  if (includeTiles && el("basemapSelect").value === "osm") {
    panel.querySelectorAll(".tile-layer img").forEach((image) => {
      if (!image.complete || image.naturalWidth <= 0) return;
      ctx.drawImage(image, parseFloat(image.style.left) || 0, headerHeight + (parseFloat(image.style.top) || 0), parseFloat(image.style.width) || image.width, parseFloat(image.style.height) || image.height);
    });
  }
  ctx.drawImage(source, 0, headerHeight);
  ctx.drawImage(panel.querySelector(".map-overlay-canvas"), 0, headerHeight);
  ctx.restore();
  if (ppi?.stats) {
    const legendHeight = Math.max(120, Math.min(360, source.height - 80));
    const legendY = headerHeight + Math.max(36, Math.floor((source.height - legendHeight) / 2));
    drawScreenshotLegend(ctx, ppi, source.width + 22, legendY, legendHeight, panel.dataset.quantity || "Field");
  }
  return output;
}

function drawScreenshotLegend(ctx, ppi, x, y, height, quantity) {
  const min = Number(ppi.stats.scale_min);
  const max = Number(ppi.stats.scale_max);
  if (!Number.isFinite(min) || !Number.isFinite(max)) return;
  const rampWidth = 24;
  for (let row = 0; row < height; row += 1) {
    const scaled = Math.round(255 * (1 - row / Math.max(1, height - 1)));
    const color = paletteColor(scaled, ppi.palette, parseCustomStops(ppi.palette_stops));
    ctx.fillStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
    ctx.fillRect(x, y + row, rampWidth, 1);
  }
  ctx.strokeStyle = "#334155";
  ctx.strokeRect(x, y, rampWidth, height);
  ctx.fillStyle = "#1d2730";
  ctx.font = "600 13px system-ui, sans-serif";
  ctx.fillText(`${quantity} (${ppi.palette})`, x - 2, y - 8);
  ctx.font = "12px system-ui, sans-serif";
  const unit = quantityUnit(quantity);
  const span = max - min;
  [[max, y + 10], [min + span / 2, y + height / 2], [min, y + height - 2]].forEach(([value, position]) => {
    ctx.fillText(`${legendValue(value, span)}${unit ? ` ${unit}` : ""}`, x + rampWidth + 10, position);
  });
}

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("could not encode screenshot PNG"));
      }, "image/png");
    } catch (err) {
      reject(err);
    }
  });
}

function isLocalAppServer() {
  return ["127.0.0.1", "localhost", "::1", ""].includes(window.location.hostname);
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error || new Error("could not read download data"));
    reader.readAsDataURL(blob);
  });
}

async function saveBlobToDesktopDownloads(filename, blob) {
  const contentBase64 = await blobToBase64(blob);
  const response = await api("/api/local-download", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      filename,
      content_type: blob.type || "application/octet-stream",
      content_base64: contentBase64,
    }),
  });
  return response.json();
}

async function downloadBlob(filename, content, type = "application/octet-stream") {
  const blob = content instanceof Blob ? content : new Blob([content], {type});
  if (isLocalAppServer()) {
    try {
      const saved = await saveBlobToDesktopDownloads(filename, blob);
      setStatus(`Saved ${saved.filename} to ${saved.path}.`);
      return saved;
    } catch (err) {
      console.warn("Desktop save failed; falling back to browser download.", err);
    }
  }
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  setStatus(`Download started for ${filename}.`);
  return {ok: true, filename, path: filename, browser_download: true};
}

function showMetadata() {
  el("metadataOutput").textContent = JSON.stringify(state.activeItem || state.items.slice(0, 3), null, 2);
  el("metadataDialog").showModal();
}

async function showCitation() {
  const response = await api("/api/citation");
  const data = await response.json();
  el("citationOutput").textContent = JSON.stringify(data, null, 2);
  el("citationDialog").showModal();
}
