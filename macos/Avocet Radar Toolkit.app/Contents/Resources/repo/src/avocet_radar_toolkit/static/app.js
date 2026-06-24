const TILE_SIZE = 256;
const EARTH_RADIUS_M = 6371000;
const METADATA_HYDRATE_MAX_BYTES = 512 * 1024 * 1024;

const state = {
  items: [],
  activeItem: null,
  panelCount: 1,
  playing: false,
  timer: null,
  panelMeta: new Map(),
  previewTimers: new Map(),
  previewRequestSeq: 0,
  hydratingItems: new Map(),
};

const el = (id) => document.getElementById(id);
const panels = () => Array.from(document.querySelectorAll(".map-panel"));

function yyyymmdd(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  let match = raw.match(/^(\d{4})[-/ ]?(\d{1,2})[-/ ]?(\d{1,2})$/);
  if (!match) {
    match = raw.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (match) return `${match[3]}${match[1].padStart(2, "0")}${match[2].padStart(2, "0")}`;
    return raw.replaceAll("-", "");
  }
  return `${match[1]}${match[2].padStart(2, "0")}${match[3].padStart(2, "0")}`;
}

function formatDate(value) {
  const compact = yyyymmdd(value);
  return compact.length === 8 ? `${compact.slice(0, 4)}-${compact.slice(4, 6)}-${compact.slice(6, 8)}` : String(value || "");
}

function normalizeDateInput(id) {
  const node = el(id);
  const formatted = formatDate(node.value);
  if (formatted) node.value = formatted;
}

function setStatus(message, isError = false) {
  const node = el("statusText");
  node.textContent = message;
  node.classList.toggle("error", isError);
}

function setPanelMessage(panel, message, isError = false) {
  const node = panel.querySelector(".identify-readout");
  node.textContent = message;
  node.classList.toggle("error", isError);
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (_err) {
      // ignore non-JSON error bodies
    }
    throw new Error(detail);
  }
  return response;
}

async function loadStatus() {
  const response = await api("/api/status");
  const data = await response.json();
  const summaryResponse = await api("/api/catalog/summary");
  const summary = await summaryResponse.json();
  const source = data.remote_catalog ? "remote object-store catalog" : "local catalog";
  const detail = data.catalog_source ? ` (${data.catalog_source})` : "";
  setStatus(`Catalog loaded: ${data.item_count} item(s), ${summary.radars.length} radar(s) from ${source}${detail}.`);
}

async function loadRadars() {
  const response = await api("/api/radars");
  const data = await response.json();
  el("radarSelect").innerHTML = '<option value="">Any</option>' + data.radars
    .map((radar) => `<option value="${radar.slug}">${radar.label} (${radar.radar_num})</option>`)
    .join("");
}

function refreshFacetControls(items) {
  const pulses = [...new Set(items.flatMap((item) => item.pulses || []))].sort();
  const quantities = [...new Set(items.flatMap((item) => item.quantities || []))].sort();
  const selectedPulseValue = el("pulseSelect").value;
  const selectedQuantityValue = el("quantitySelect").value;
  el("pulseSelect").innerHTML = '<option value="">Any</option>' + pulses.map((value) => `<option value="${value}">${value}</option>`).join("");
  el("quantitySelect").innerHTML = '<option value="">Any</option>' + quantities.map((value) => `<option value="${value}">${value}</option>`).join("");
  el("pulseSelect").value = pulses.includes(selectedPulseValue) ? selectedPulseValue : "";
  el("quantitySelect").value = quantities.includes(selectedQuantityValue) ? selectedQuantityValue : "";
}

function itemKey(item) {
  return item ? `${item.radar}:${item.date}` : "";
}

function itemLabel(item) {
  return `${item.radar} ${formatDate(item.date)}`;
}

function refreshItemControls(items) {
  const previousKey = itemKey(state.activeItem);
  el("itemSelect").innerHTML = items
    .map((item, index) => `<option value="${index}">${itemLabel(item)}</option>`)
    .join("");
  const selectedIndex = Math.max(0, items.findIndex((item) => itemKey(item) === previousKey));
  state.activeItem = items.length ? items[selectedIndex] : null;
  if (items.length) el("itemSelect").value = String(selectedIndex);
  refreshTimeControls();
}

function uniqueSorted(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null && String(value) !== "").map(String))].sort();
}

function availableTimesForSelection(item, pulse = selectedPulse(item), quantity = el("quantitySelect").value) {
  if (!item) return [];
  const records = Array.isArray(item.quantity_records) ? item.quantity_records : [];
  if (records.length) {
    const matches = records
      .filter((record) => (!pulse || record.pulse === pulse) && (!quantity || record.quantity === quantity))
      .map((record) => record.time);
    return uniqueSorted(matches);
  }
  if (pulse && item.times_by_pulse && Array.isArray(item.times_by_pulse[pulse])) {
    return uniqueSorted(item.times_by_pulse[pulse]);
  }
  return uniqueSorted(item.times || []);
}

function itemHasTimeMetadata(item) {
  if (!item) return false;
  if (Array.isArray(item.quantity_records) && item.quantity_records.length) return true;
  if (Array.isArray(item.times) && item.times.length) return true;
  return Object.values(item.times_by_pulse || {}).some((times) => Array.isArray(times) && times.length);
}

function refreshTimeControls() {
  const item = state.activeItem;
  const selected = el("timeSelect").value;
  const times = availableTimesForSelection(item);
  el("timeSelect").innerHTML = times.map((time) => `<option value="${time}">${time}</option>`).join("");
  if (times.includes(selected)) {
    el("timeSelect").value = selected;
  } else if (times.length) {
    el("timeSelect").value = times[0];
  }
  el("timeSelect").disabled = times.length === 0;
  updateTimeStepOutput();
}

function replaceCatalogItem(updated) {
  const key = itemKey(updated);
  const index = state.items.findIndex((item) => itemKey(item) === key);
  if (index >= 0) {
    state.items[index] = updated;
    el("itemSelect").options[index].textContent = itemLabel(updated);
  }
  if (itemKey(state.activeItem) === key) state.activeItem = updated;
  return updated;
}

function describeItemMetadata(item) {
  const pulses = item.pulses && item.pulses.length ? item.pulses.join(", ") : "no pulses";
  const times = uniqueSorted(item.times || []);
  const quantities = item.quantities && item.quantities.length ? item.quantities.join(", ") : "no quantities";
  const timeSummary = times.length ? `${times.length} time(s), ${times[0]} to ${times[times.length - 1]}` : "no times";
  return `${timeSummary}; ${pulses}; ${quantities}`;
}

async function hydrateItemDetails(item) {
  if (!item || itemHasTimeMetadata(item)) return item;
  const key = itemKey(item);
  if (state.hydratingItems.has(key)) return state.hydratingItems.get(key);
  if (Number(item.file_size || 0) > METADATA_HYDRATE_MAX_BYTES) {
    const message =
      `Catalog day ${itemLabel(item)} exists, but its public catalog entry does not include the pulse/time/quantity index. ` +
      `The raw aggregate is ${formatBytes(item.file_size)}, so the app will not download it just to discover times. ` +
      `Publish a detailed aggregate metadata catalog for this day, or choose a catalog item that already lists times.`;
    setStatus(message, true);
    panels().forEach((panel) => setPanelMessage(panel, message, true));
    return item;
  }
  const task = (async () => {
    setStatus(`Catalog day found for ${itemLabel(item)}. Loading its time and field metadata from the raw aggregate cache...`);
    panels().forEach((panel) => setPanelMessage(panel, `Loading ${itemLabel(item)} time and field metadata...`));
    const response = await api(`/api/item/${item.radar}/${item.date}/hydrate`);
    const updated = replaceCatalogItem(await response.json());
    refreshFacetControls(state.items);
    refreshTimeControls();
    if (itemHasTimeMetadata(updated)) {
      setStatus(`Loaded ${itemLabel(updated)} details: ${describeItemMetadata(updated)}.`);
    } else {
      setStatus(`Catalog day ${itemLabel(updated)} exists, but no pulse/time/quantity metadata was found in the raw aggregate.`, true);
    }
    return updated;
  })();
  state.hydratingItems.set(key, task);
  try {
    return await task;
  } finally {
    state.hydratingItems.delete(key);
  }
}

async function prepareActiveItemForDisplay() {
  if (!state.activeItem) return null;
  const item = await hydrateItemDetails(state.activeItem);
  refreshTimeControls();
  if (!availableTimesForSelection(item).length) {
    setStatus(`No available radar times for ${itemLabel(item)} with the selected pulse and quantity. Choose Any or another field.`, true);
  }
  return item;
}

async function searchCatalog() {
  normalizeDateInput("startInput");
  normalizeDateInput("endInput");
  const params = new URLSearchParams();
  const radar = el("radarSelect").value;
  const start = yyyymmdd(el("startInput").value);
  const end = yyyymmdd(el("endInput").value);
  const pulse = el("pulseSelect").value;
  const quantity = el("quantitySelect").value;
  if (radar) params.set("radar", radar);
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (pulse) params.set("pulse", pulse);
  if (quantity) params.set("quantity", quantity);

  const response = await api(`/api/catalog?${params.toString()}`);
  const data = await response.json();
  state.items = data.items;
  refreshFacetControls(state.items);
  refreshItemControls(state.items);
  if (state.items.length) {
    const radars = [...new Set(state.items.map((item) => item.radar))].sort();
    const dates = state.items.map((item) => item.date).sort();
    setStatus(`Catalog search: ${state.items.length} item(s), ${radars.join(", ")}, ${formatDate(dates[0])} to ${formatDate(dates[dates.length - 1])}.`);
    await prepareActiveItemForDisplay();
    schedulePreview();
  } else {
    setStatus("Catalog search returned no data for the selected radar/date/pulse/quantity. Adjust the selection and search again.", true);
    panels().forEach((panel) => {
      clearPanel(panel);
      setPanelMessage(panel, "No catalog data matches the current selection.", true);
    });
  }
}

function selectedQuantity(item = state.activeItem, pulse = selectedPulse(item), time = el("timeSelect").value) {
  const explicit = el("quantitySelect").value;
  if (explicit) return explicit;
  if (!item) return "";
  const records = Array.isArray(item.quantity_records) ? item.quantity_records : [];
  const match = records.find((record) => (!pulse || record.pulse === pulse) && (!time || record.time === time));
  if (match) return match.quantity;
  return item.quantities && item.quantities.length ? item.quantities[0] : "";
}

function selectedPulse(item = state.activeItem) {
  const explicit = el("pulseSelect").value;
  if (explicit) return explicit;
  return item && item.pulses.length ? item.pulses[0] : "";
}

function filterParams() {
  const mapping = {
    minRangeInput: "min_range_km",
    maxRangeInput: "max_range_km",
    minAzimuthInput: "min_azimuth_deg",
    maxAzimuthInput: "max_azimuth_deg",
    minValueInput: "min_value",
    maxValueInput: "max_value",
    cappiHeightInput: "cappi_height_m",
  };
  const params = {};
  Object.entries(mapping).forEach(([id, key]) => {
    const value = el(id).value.trim();
    if (value !== "") params[key] = Number(value);
  });
  if (el("paletteSelect").value === "custom") {
    const stops = el("customPaletteInput").value.trim();
    if (stops) params.palette_stops = stops;
  }
  return params;
}

function appendFilterParams(params) {
  Object.entries(filterParams()).forEach(([key, value]) => params.set(key, String(value)));
  return params;
}

function fieldParams() {
  const dataset = el("datasetInput").value.trim();
  const params = new URLSearchParams({
    palette: el("paletteSelect").value,
    max_rays: "360",
    max_bins: "360",
  });
  if (dataset) params.set("dataset", dataset);
  appendFilterParams(params);
  return params;
}

function ppiUrl(item, time, pulse = selectedPulse(item), quantity = selectedQuantity(item, pulse, time)) {
  const encodedQuantity = encodeURIComponent(quantity);
  const encodedPulse = encodeURIComponent(pulse);
  return `/api/ppi/${item.radar}/${item.date}/${encodedPulse}/${time}/${encodedQuantity}?${fieldParams().toString()}`;
}

function identifyUrlForPanel(panel, row, column) {
  const quantity = encodeURIComponent(panel.dataset.quantity || selectedQuantity());
  const pulse = encodeURIComponent(panel.dataset.pulse || selectedPulse());
  const dataset = el("datasetInput").value.trim();
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
  const select = el("timeSelect");
  const total = select.options.length;
  const current = total ? select.selectedIndex + 1 : 0;
  el("timeStepOutput").textContent = `${current} / ${total}`;
  const disabled = total < 2;
  el("timePrevButton").disabled = disabled;
  el("timeNextButton").disabled = disabled;
}

function schedulePreview(panelIndex = 0, delayMs = 250) {
  const existing = state.previewTimers.get(panelIndex);
  if (existing) clearTimeout(existing);
  const timer = setTimeout(() => {
    state.previewTimers.delete(panelIndex);
    loadPpi(panelIndex).catch((err) => {
      const panel = panels()[panelIndex];
      if (panel) setPanelMessage(panel, err.message, true);
      setStatus(`Plot failed: ${err.message}`, true);
    });
  }, delayMs);
  state.previewTimers.set(panelIndex, timer);
}

async function loadPpi(panelIndex = 0, itemOverride = null, timeOverride = "") {
  let item = itemOverride || state.activeItem;
  if (!item) return;
  item = await hydrateItemDetails(item);
  const pulse = selectedPulse(item);
  const availableTimes = availableTimesForSelection(item, pulse);
  const requestedTime = timeOverride || el("timeSelect").value || availableTimes[0] || "";
  const time = availableTimes.includes(requestedTime) ? requestedTime : availableTimes[0];
  const quantity = selectedQuantity(item, pulse, time);
  const panel = panels()[panelIndex];
  if (!time || !pulse || !quantity) {
    clearPanel(panel);
    panel.querySelector(".panel-title").textContent = itemLabel(item);
    setPanelMessage(panel, `No available time for ${itemLabel(item)} with the selected pulse and quantity.`, true);
    setStatus(`No available radar time for ${itemLabel(item)} with the selected pulse and quantity.`, true);
    return;
  }

  const requestId = String(++state.previewRequestSeq);
  panel.dataset.previewRequestId = requestId;
  panel.dataset.radar = item.radar;
  panel.dataset.date = item.date;
  panel.dataset.time = time;
  panel.dataset.pulse = pulse;
  panel.dataset.quantity = quantity;
  panel.querySelector(".panel-title").textContent = `${itemLabel(item)} ${pulse} ${time} ${quantity}`;
  setPanelMessage(panel, "Loading raw PPI data from object store/cache...");
  setStatus(`Loading ${itemLabel(item)} ${pulse} ${time} ${quantity}...`);
  clearPanel(panel);

  const response = await api(ppiUrl(item, time, pulse, quantity));
  const ppi = await response.json();
  if (panel.dataset.previewRequestId !== requestId) return;
  state.panelMeta.set(panelIndex, ppi);
  renderPanel(panel, ppi);
  const meta = ppi.metadata;
  const stats = ppi.stats || {};
  setPanelMessage(
    panel,
    `${ppi.source_shape[0]} x ${ppi.source_shape[1]} bins, ${ppi.palette}, scale=${fmtNumber(stats.scale_min, 1)} to ${fmtNumber(stats.scale_max, 1)}, elevation=${fmtNumber(meta.elevation_deg, 2)} deg`,
  );
  setStatus(`Displayed ${itemLabel(item)} ${pulse} ${time} ${quantity}.`);
}

function clearPanel(panel) {
  panel.querySelector(".tile-layer").innerHTML = "";
  const legend = panel.querySelector(".colour-legend");
  if (legend) legend.hidden = true;
  ["ppi-canvas", "map-overlay-canvas"].forEach((className) => {
    const canvas = panel.querySelector(`.${className}`);
    const ctx = canvas.getContext("2d");
    canvas.width = Math.max(1, panel.clientWidth);
    canvas.height = Math.max(1, panel.clientHeight);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  });
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
  const width = Math.max(1, panel.clientWidth);
  const height = Math.max(1, panel.clientHeight);
  const [west, south, east, north] = metadata.geographic_bbox;
  let zoom = 6;
  for (let candidate = 3; candidate <= 11; candidate += 1) {
    const nw = lonLatToWorld(west, north, candidate);
    const se = lonLatToWorld(east, south, candidate);
    if ((se.x - nw.x) <= width * 0.86 && (se.y - nw.y) <= height * 0.86) {
      zoom = candidate;
    }
  }
  const center = lonLatToWorld(metadata.longitude, metadata.latitude, zoom);
  return {
    zoom,
    width,
    height,
    centerX: center.x,
    centerY: center.y,
    left: center.x - width / 2,
    top: center.y - height / 2,
  };
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
  layer.innerHTML = "";
  if (el("basemapSelect").value !== "osm") return;
  const minTileX = Math.floor(transform.left / TILE_SIZE);
  const maxTileX = Math.floor((transform.left + transform.width) / TILE_SIZE);
  const minTileY = Math.floor(transform.top / TILE_SIZE);
  const maxTileY = Math.floor((transform.top + transform.height) / TILE_SIZE);
  const tileLimit = 2 ** transform.zoom;
  for (let tx = minTileX; tx <= maxTileX; tx += 1) {
    for (let ty = minTileY; ty <= maxTileY; ty += 1) {
      if (ty < 0 || ty >= tileLimit) continue;
      const wrappedX = ((tx % tileLimit) + tileLimit) % tileLimit;
      const image = document.createElement("img");
      image.alt = "";
      image.decoding = "async";
      image.loading = "lazy";
      image.src = `https://tile.openstreetmap.org/${transform.zoom}/${wrappedX}/${ty}.png`;
      image.style.left = `${tx * TILE_SIZE - transform.left}px`;
      image.style.top = `${ty * TILE_SIZE - transform.top}px`;
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
  const ringStepM = metadata.max_range_m > 180000 ? 50000 : 25000;
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
  const radar = projectLonLat(metadata.longitude, metadata.latitude, transform);
  ctx.fillStyle = "#111827";
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(radar.x, radar.y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
}

function renderPanel(panel, ppi) {
  const transform = chooseMapTransform(panel, ppi.metadata);
  panel._mapTransform = transform;
  renderTiles(panel, transform);
  renderPpi(panel, ppi, transform);
  renderOverlay(panel, ppi, transform);
  renderLegend(panel, ppi);
}

function stepFrame(delta) {
  const select = el("timeSelect");
  if (!select.options.length) return;
  const next = (select.selectedIndex + delta + select.options.length) % select.options.length;
  select.selectedIndex = next;
  updateTimeStepOutput();
  schedulePreview(0, 0);
}

function togglePlay() {
  state.playing = !state.playing;
  el("playButton").textContent = state.playing ? "Pause" : "Play";
  if (state.playing) {
    state.timer = setInterval(() => stepFrame(1), Number(el("delayInput").value) || 600);
  } else {
    clearInterval(state.timer);
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
  if (count === 4 && state.items.length) {
    panels().forEach((_panel, index) => {
      const item = state.items[index % state.items.length];
      loadPpi(index, item).catch((err) => {
        setPanelMessage(panels()[index], err.message, true);
        setStatus(`Plot failed: ${err.message}`, true);
      });
    });
  } else {
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

function captureFrame() {
  const panel = panels()[0];
  const source = panel.querySelector(".ppi-canvas");
  if (!source.width || !source.height) return;
  const output = document.createElement("canvas");
  output.width = source.width;
  output.height = source.height;
  const ctx = output.getContext("2d");
  ctx.fillStyle = el("basemapSelect").value === "dark" ? "#1d2730" : "#dfe6ec";
  ctx.fillRect(0, 0, output.width, output.height);
  ctx.drawImage(source, 0, 0);
  ctx.drawImage(panel.querySelector(".map-overlay-canvas"), 0, 0);
  const capture = document.createElement("img");
  capture.src = output.toDataURL("image/png");
  capture.alt = "Captured radar PPI";
  el("captures").prepend(capture);
}

function showMetadata() {
  el("metadataOutput").textContent = JSON.stringify(state.activeItem || state.items.slice(0, 3), null, 2);
  el("metadataDialog").showModal();
}

function currentSessionState() {
  return {
    radar: el("radarSelect").value,
    start: el("startInput").value,
    end: el("endInput").value,
    pulse: el("pulseSelect").value,
    quantity: el("quantitySelect").value,
    itemIndex: el("itemSelect").value,
    time: el("timeSelect").value,
    dataset: el("datasetInput").value,
    opacity: el("opacityInput").value,
    palette: el("paletteSelect").value,
    customPalette: el("customPaletteInput").value,
    basemap: el("basemapSelect").value,
    filters: filterParams(),
    panelCount: state.panelCount,
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
  el("quantitySelect").value = saved.quantity || "";
  el("datasetInput").value = saved.dataset || "";
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
  setPanelCount(Number(saved.panelCount) || 1);
  await searchCatalog();
  if (saved.itemIndex && el("itemSelect").options[Number(saved.itemIndex)]) {
    el("itemSelect").value = saved.itemIndex;
    state.activeItem = state.items[Number(saved.itemIndex)];
    await prepareActiveItemForDisplay();
  }
  if (saved.time) el("timeSelect").value = saved.time;
  setBasemap(el("basemapSelect").value);
  schedulePreview();
}

function downloadProject() {
  const sessionId = el("sessionIdInput").value.trim() || "default";
  const now = new Date().toISOString();
  const project = {
    type: "avocet-wct-project",
    version: 1,
    exported_at: now,
    application: "avocet-radar-toolkit",
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
  const blob = new Blob([JSON.stringify(project, null, 2)], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${sessionId}.avocet-wct-project.json`;
  link.click();
  URL.revokeObjectURL(url);
  el("sessionStatus").textContent = `Downloaded ${link.download}`;
}

async function importProjectFile(file) {
  const payload = JSON.parse(await file.text());
  if (payload.type !== "avocet-wct-project" || !payload.session || !payload.session.state) {
    throw new Error("Not an Avocet WCT project file.");
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
  const y = event.clientY - rect.top;
  const geo = pixelToLonLat(x, y, transform);
  const rb = rangeBearingFromRadar(ppi.metadata, geo.lon, geo.lat);
  if (rb.rangeM < ppi.metadata.rstart_km * 1000 || rb.rangeM > ppi.metadata.max_range_m) {
    return {ppi, lon: geo.lon, lat: geo.lat, outside: true};
  }
  const row = Math.max(0, Math.min(ppi.metadata.nrays - 1, Math.floor((rb.azimuthDeg / 360) * ppi.metadata.nrays)));
  const column = Math.max(0, Math.min(ppi.metadata.nbins - 1, Math.floor((rb.rangeM - ppi.metadata.rstart_km * 1000) / ppi.metadata.rscale_m)));
  return {ppi, lon: geo.lon, lat: geo.lat, rangeM: rb.rangeM, azimuthDeg: rb.azimuthDeg, row, column, outside: false};
}

function attachEvents() {
  el("refreshButton").addEventListener("click", () => searchCatalog().catch((err) => setStatus(err.message, true)));
  el("searchButton").addEventListener("click", () => searchCatalog().catch((err) => setStatus(err.message, true)));
  ["startInput", "endInput"].forEach((id) => {
    el(id).addEventListener("blur", () => normalizeDateInput(id));
  });
  el("itemSelect").addEventListener("change", () => {
    state.activeItem = state.items[Number(el("itemSelect").value)];
    prepareActiveItemForDisplay()
      .then(() => schedulePreview(0, 0))
      .catch((err) => {
        setStatus(`Could not load item details: ${err.message}`, true);
        panels().forEach((panel) => setPanelMessage(panel, err.message, true));
      });
  });
  [
    "timeSelect",
    "pulseSelect",
    "quantitySelect",
    "datasetInput",
    "customPaletteInput",
    "minRangeInput",
    "maxRangeInput",
    "minAzimuthInput",
    "maxAzimuthInput",
    "minValueInput",
    "maxValueInput",
    "cappiHeightInput",
  ].forEach((id) => {
    el(id).addEventListener("change", () => {
      if (id === "pulseSelect" || id === "quantitySelect") {
        refreshTimeControls();
        if (!el("timeSelect").options.length && state.activeItem) {
          setStatus(`No available radar times for ${itemLabel(state.activeItem)} with the selected ${id === "pulseSelect" ? "pulse" : "quantity"}.`, true);
        }
      }
      else if (id === "timeSelect") updateTimeStepOutput();
      schedulePreview();
    });
  });
  el("opacityInput").addEventListener("input", applyOpacity);
  el("paletteSelect").addEventListener("change", () => schedulePreview());
  el("basemapSelect").addEventListener("change", () => setBasemap(el("basemapSelect").value));
  el("prevButton").addEventListener("click", () => stepFrame(-1));
  el("nextButton").addEventListener("click", () => stepFrame(1));
  el("timePrevButton").addEventListener("click", () => stepFrame(-1));
  el("timeNextButton").addEventListener("click", () => stepFrame(1));
  el("playButton").addEventListener("click", togglePlay);
  el("captureButton").addEventListener("click", captureFrame);
  el("metadataButton").addEventListener("click", showMetadata);
  el("closeMetadataButton").addEventListener("click", () => el("metadataDialog").close());
  el("saveSessionButton").addEventListener("click", () => saveSession().catch((err) => {
    el("sessionStatus").textContent = err.message;
  }));
  el("loadSessionButton").addEventListener("click", () => loadSession().catch((err) => {
    el("sessionStatus").textContent = err.message;
  }));
  el("downloadProjectButton").addEventListener("click", downloadProject);
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
  document.querySelectorAll(".view-button").forEach((button) => {
    button.addEventListener("click", () => setPanelCount(Number(button.dataset.panelCount)));
  });
  panels().forEach((panel) => {
    panel.addEventListener("mousemove", (event) => {
      const rect = panel.getBoundingClientRect();
      const crosshair = panel.querySelector(".crosshair");
      crosshair.hidden = false;
      crosshair.style.left = `${event.clientX - rect.left}px`;
      crosshair.style.top = `${event.clientY - rect.top}px`;
      const hit = binFromMouse(panel, event);
      if (!hit) return;
      if (hit.outside) {
        panel.querySelector(".identify-readout").textContent = `lat=${fmtNumber(hit.lat, 5)}, lon=${fmtNumber(hit.lon, 5)}, outside radar range`;
        return;
      }
      panel.querySelector(".identify-readout").textContent =
        `row=${hit.row}, col=${hit.column}, range=${fmtNumber(hit.rangeM / 1000, 2)} km, az=${fmtNumber(hit.azimuthDeg, 1)} deg, lat=${fmtNumber(hit.lat, 5)}, lon=${fmtNumber(hit.lon, 5)}`;
    });
    panel.addEventListener("mouseleave", () => {
      panel.querySelector(".crosshair").hidden = true;
    });
    panel.addEventListener("click", async (event) => {
      const hit = binFromMouse(panel, event);
      if (!hit || hit.outside || !panel.dataset.radar) return;
      try {
        const response = await api(identifyUrlForPanel(panel, hit.row, hit.column));
        const data = await response.json();
        const geo = data.latitude !== undefined
          ? `range=${fmtNumber(data.range_km, 2)} km, az=${fmtNumber(data.azimuth_deg, 1)} deg, lat=${fmtNumber(data.latitude, 5)}, lon=${fmtNumber(data.longitude, 5)}`
          : data.geospatial_error || "geospatial metadata unavailable";
        panel.querySelector(".identify-readout").textContent =
          `${data.quantity} value=${data.value}, row=${data.row}, col=${data.column}, ${geo}`;
      } catch (err) {
        panel.querySelector(".identify-readout").textContent = err.message;
      }
    });
  });
  window.addEventListener("resize", () => {
    panels().forEach((panel, index) => {
      const ppi = state.panelMeta.get(index);
      if (ppi) renderPanel(panel, ppi);
    });
  });
}

async function init() {
  attachEvents();
  await loadStatus();
  await loadRadars();
  setBasemap(el("basemapSelect").value);
  await searchCatalog();
}

init().catch((err) => setStatus(err.message, true));
