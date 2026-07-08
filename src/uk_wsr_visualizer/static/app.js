const TILE_SIZE = 256;
const EARTH_RADIUS_M = 6371000;
const DEFAULT_VARIABLE = "DBZH";
const DEFAULT_CLEANUP_ENABLED = true;
const DEFAULT_CLEANUP_MARGIN_DB = 0;
const DEFAULT_QC_MODE = "signal_preserving";

// The viewer is deliberately written as a single static file so the packaged
// desktop apps can serve it without a frontend build step. State is centralised
// here, and the helper sections below keep catalog discovery, panel rendering,
// map interaction, and session persistence separated.
const state = {
  items: [],
  activeItem: null,
  panelCount: 1,
  panelSelections: [{}, {}, {}, {}],
  playing: false,
  timer: null,
  animationBusy: false,
  panelMeta: new Map(),
  ppiFrameCache: new Map(),
  ppiFrameCacheOrder: [],
  ppiFrameFetches: new Map(),
  rawCacheByItem: new Map(),
  rawPrefetches: new Set(),
  maxPpiFrameCacheEntries: 48,
  animationPrefetchCount: 3,
  previewTimers: new Map(),
  identifyTimers: new Map(),
  previewRequestSeq: 0,
  identifyRequestSeq: 0,
  searchRequestSeq: 0,
  hydratingItems: new Map(),
  performanceEvents: [],
  maxPerformanceEvents: 300,
  catalogSummary: null,
  catalogAvailability: null,
  exportJob: null,
  radarRecords: [],
  recentSelections: [],
  lastLoadRetry: null,
  pointerFields: {
    value: true,
    range: true,
    height: true,
    elevation: true,
    latlon: true,
    bin: false,
  },
  comparisonLinks: {
    view: true,
    time: true,
    variable: false,
    elevation: false,
  },
};

const el = (id) => document.getElementById(id);
const panels = () => Array.from(document.querySelectorAll(".map-panel"));

function optionalInputValue(id) {
  const node = el(id);
  return node ? node.value.trim() : "";
}

function setOptionalInputValue(id, value) {
  const node = el(id);
  if (node) node.value = value || "";
}

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

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[char]);
}

function selectedDateRange() {
  return {
    start: yyyymmdd(el("startInput").value),
    end: yyyymmdd(el("endInput").value),
  };
}

function currentSelectionSummary() {
  return {
    radar: el("radarSelect")?.value || "",
    start: yyyymmdd(el("startInput")?.value || ""),
    end: yyyymmdd(el("endInput")?.value || ""),
    item: state.activeItem ? itemLabel(state.activeItem) : "",
    pulse: el("pulseSelect")?.value || "",
    time: el("timeSelect")?.value || "",
    variable: el("quantitySelect")?.value || DEFAULT_VARIABLE,
    elevation_dataset: optionalInputValue("datasetInput"),
    panel_count: state.panelCount,
  };
}

function dateRangeLabel(start, end) {
  if (start && end) return `${formatDate(start)} to ${formatDate(end)}`;
  if (start) return `from ${formatDate(start)}`;
  if (end) return `to ${formatDate(end)}`;
  return "all catalog dates";
}

function rangesOverlap(itemStart, itemEnd, start, end) {
  if (!itemStart || !itemEnd) return false;
  return (!start || itemEnd >= start) && (!end || itemStart <= end);
}

function radarLabelFromSlug(slug) {
  const record = state.radarRecords.find((radar) => radar.slug === slug);
  return record ? `${record.label} (${record.radar_num})` : slug;
}

function radarCoverage(slug) {
  const summary = state.catalogSummary;
  return summary && summary.by_radar ? summary.by_radar[slug] : null;
}

function radarAvailableForDateRange(slug) {
  const coverage = radarCoverage(slug);
  const {start, end} = selectedDateRange();
  return Boolean(coverage && rangesOverlap(coverage.start_date, coverage.end_date, start, end));
}

function availableRadarsForDateRange() {
  return state.radarRecords.filter((radar) => radarAvailableForDateRange(radar.slug));
}

function unavailableRadarsForDateRange() {
  return state.radarRecords.filter((radar) => !radarAvailableForDateRange(radar.slug));
}

function summarizeRadarList(radars, limit = 6) {
  const names = radars.map((radar) => radar.label || radar.slug);
  if (names.length <= limit) return names.join(", ");
  return `${names.slice(0, limit).join(", ")}, plus ${names.length - limit} more`;
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

function setActivityStage(stage, detail = "", isError = false, retryAction = null) {
  const strip = el("activityStrip");
  const text = el("activityText");
  const retry = el("retryLoadButton");
  if (!strip || !text || !retry) return;
  text.textContent = detail ? `${stage}: ${detail}` : stage;
  strip.classList.toggle("error", isError);
  state.lastLoadRetry = retryAction;
  retry.hidden = !retryAction;
}

async function retryLastLoad() {
  const action = state.lastLoadRetry || refreshCatalogAndSearch;
  setActivityStage("Retrying", "loading data state again...");
  await action();
}

function reportLoadError(err, label = "Load failed", retryAction = refreshCatalogAndSearch) {
  const message = err && err.message ? err.message : String(err);
  setStatus(message, true);
  setActivityStage(label, message, true, retryAction);
}

function pushPerformanceEvent(event) {
  const payload = {
    created_at: new Date().toISOString(),
    ...event,
  };
  state.performanceEvents.push(payload);
  if (state.performanceEvents.length > state.maxPerformanceEvents) {
    state.performanceEvents.splice(0, state.performanceEvents.length - state.maxPerformanceEvents);
  }
  renderPerformanceDialogIfOpen();
}

function shortApiPath(path) {
  const text = String(path || "");
  return text.length > 140 ? `${text.slice(0, 137)}...` : text;
}

function renderPerformanceDialogIfOpen() {
  const dialog = el("performanceDialog");
  if (!dialog || !dialog.open) return;
  renderPerformanceDialog();
}

function formatDurationMs(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return number >= 1000 ? `${(number / 1000).toFixed(2)} s` : `${number.toFixed(1)} ms`;
}

function summarizePerformanceEvent(event) {
  const label = event.operation || event.path || event.name || event.kind || "event";
  const elapsed = event.elapsed_ms ?? event.client_elapsed_ms;
  const server = event.server_elapsed_ms ? `, server ${formatDurationMs(event.server_elapsed_ms)}` : "";
  const detail = event.cache_hit === true ? ", cache hit" : event.cache_hit === false ? ", cache miss" : "";
  return `${event.created_at} | ${event.kind || "event"} | ${label} | ${formatDurationMs(elapsed)}${server}${detail}`;
}

async function fetchServerPerformance() {
  const response = await fetch("/api/performance?limit=120", {cache: "no-store"});
  if (!response.ok) throw new Error(response.statusText);
  return response.json();
}

async function renderPerformanceDialog() {
  const output = el("performanceOutput");
  if (!output) return;
  let server = null;
  try {
    server = await fetchServerPerformance();
  } catch (err) {
    server = {ok: false, error: err.message, events: []};
  }
  const clientEvents = state.performanceEvents.slice(-80);
  const serverEvents = (server.events || []).slice(-80);
  const lines = [
    "Client timings",
    ...clientEvents.map(summarizePerformanceEvent),
    "",
    "Server timings",
    ...serverEvents.map(summarizePerformanceEvent),
    "",
    "Server cache state",
    JSON.stringify(server.cache || {}, null, 2),
  ];
  output.textContent = lines.join("\n");
}

async function showPerformance() {
  await renderPerformanceDialog();
  el("performanceDialog").showModal();
}

async function clearPerformanceEvents() {
  state.performanceEvents = [];
  await fetch("/api/performance/clear", {method: "POST"}).catch((_err) => {});
  await renderPerformanceDialog();
}

async function downloadPerformanceReport() {
  const server = await fetchServerPerformance().catch((err) => ({ok: false, error: err.message, events: []}));
  const report = {
    created_at: new Date().toISOString(),
    app: "UK WSR Visualizer",
    client_events: state.performanceEvents,
    server,
    active_selection: currentSelectionSummary(),
  };
  await downloadBlob(`uk-wsr-performance-${Date.now()}.json`, JSON.stringify(report, null, 2), "application/json");
}

function setPanelMessage(panel, message, isError = false, detail = "") {
  const node = panel.querySelector(".identify-readout");
  node.textContent = message;
  node.title = detail || message;
  node.classList.toggle("error", isError);
  node.classList.toggle("compact", !isError);
}

function setPanelReadout(panel, message, isError = false) {
  const node = panel.querySelector(".identify-readout");
  node.textContent = message;
  node.title = message;
  node.classList.toggle("error", isError);
  node.classList.remove("compact");
}

function setPanelLoading(panel, message = "", active = false) {
  const node = panel?.querySelector(".panel-loading");
  if (!node) return;
  node.textContent = message || "Loading next frame...";
  node.hidden = !active;
}

function formatBytes(value) {
  const bytes = Number(value) || 0;
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

async function api(path, options) {
  const start = performance.now();
  let response = null;
  try {
    response = await fetch(path, options);
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
  } catch (err) {
    pushPerformanceEvent({
      kind: "fetch",
      path: shortApiPath(path),
      method: options?.method || "GET",
      status_code: response?.status || 0,
      client_elapsed_ms: performance.now() - start,
      error: err.message,
    });
    throw err;
  } finally {
    if (response && response.ok) {
      pushPerformanceEvent({
        kind: "fetch",
        path: shortApiPath(path),
        method: options?.method || "GET",
        status_code: response.status,
        client_elapsed_ms: performance.now() - start,
        server_elapsed_ms: Number(response.headers.get("X-UK-WSR-Elapsed-Ms")) || null,
        operation_elapsed_ms: Number(response.headers.get("X-UK-WSR-Operation-Elapsed-Ms")) || null,
      });
    }
  }
}

async function loadStatus() {
  setActivityStage("Server ready", "checking catalog status...");
  const response = await api("/api/status");
  const data = await response.json();
  const source = data.remote_catalog ? "remote object-store catalog" : "local catalog";
  const detail = data.catalog_source ? ` (${data.catalog_source})` : "";
  if (!data.ok) {
    const reason = data.catalog_error || "catalog is unavailable";
    setStatus(`Catalog unavailable from ${source}${detail}: ${reason}. The app is open; data controls will work once the catalog is reachable.`, true);
    setActivityStage("Catalog unavailable", reason, true, refreshCatalogAndSearch);
    return false;
  }
  setActivityStage("Catalog status loaded", "loading radar availability...");
  const summaryResponse = await api("/api/catalog/summary");
  const summary = await summaryResponse.json();
  state.catalogSummary = summary;
  const range = summary.start_date && summary.end_date ? `, ${formatDate(summary.start_date)} to ${formatDate(summary.end_date)}` : "";
  setStatus(`Catalog loaded: ${data.item_count} item(s), ${summary.radars.length} radar(s)${range} from ${source}${detail}.`);
  setActivityStage("Catalog loaded", `${data.item_count} item(s), ${summary.radars.length} radar(s)${range}`);
  refreshRadarOptions();
  updateAvailabilityPanel();
  return true;
}

async function catalogSummary() {
  if (state.catalogSummary) return state.catalogSummary;
  const response = await api("/api/catalog/summary");
  state.catalogSummary = await response.json();
  updateAvailabilityPanel();
  return state.catalogSummary;
}

function selectedRadarLabel() {
  const select = el("radarSelect");
  return select.value ? select.selectedOptions[0]?.textContent || select.value : "All radars";
}

function selectedCoverage() {
  const {start, end} = selectedDateRange();
  if (state.catalogAvailability && state.catalogAvailability.radar === el("radarSelect").value && !start && !end) {
    return state.catalogAvailability;
  }
  const summary = state.catalogSummary;
  if (!summary) return null;
  const radar = el("radarSelect").value;
  if (!radar) return summary;
  return summary.by_radar && summary.by_radar[radar] ? summary.by_radar[radar] : null;
}

function plotReadyDate(coverage, which) {
  if (!coverage) return "";
  if (which === "latest") return coverage.latest_plot_ready_date || coverage.end_date || "";
  return coverage.first_plot_ready_date || coverage.start_date || "";
}

function updateAvailabilityPanel() {
  const node = el("availabilityText");
  if (!node) return;
  const firstButton = el("firstAvailableButton");
  const latestButton = el("latestAvailableButton");
  const {start, end} = selectedDateRange();
  const rangeText = dateRangeLabel(start, end);
  const selectedRadar = el("radarSelect").value;
  const available = availableRadarsForDateRange();
  const unavailable = unavailableRadarsForDateRange();
  if (selectedRadar && !radarAvailableForDateRange(selectedRadar)) {
    const coverage = radarCoverage(selectedRadar);
    const coverageText = coverage && coverage.start_date && coverage.end_date
      ? `${radarLabelFromSlug(selectedRadar)} covers ${formatDate(coverage.start_date)} to ${formatDate(coverage.end_date)}.`
      : `${radarLabelFromSlug(selectedRadar)} is not in the loaded catalog.`;
    const alternatives = available.length ? ` Available for ${rangeText}: ${summarizeRadarList(available)}.` : ` No radars are available for ${rangeText}.`;
    node.textContent = `${coverageText} It is not available for ${rangeText}.${alternatives}`;
    if (firstButton) firstButton.disabled = true;
    if (latestButton) latestButton.disabled = true;
    return;
  }
  if (!selectedRadar && (start || end)) {
    const total = state.radarRecords.length;
    const unavailableText = unavailable.length ? ` ${unavailable.length} unavailable radar${unavailable.length === 1 ? "" : "s"} are disabled in the list.` : "";
    node.textContent = available.length
      ? `${available.length} of ${total} radar${total === 1 ? "" : "s"} available for ${rangeText}: ${summarizeRadarList(available)}.${unavailableText}`
      : `No radars are available for ${rangeText}. The loaded catalog covers ${formatDate(state.catalogSummary?.start_date)} to ${formatDate(state.catalogSummary?.end_date)}.`;
    if (firstButton) firstButton.disabled = true;
    if (latestButton) latestButton.disabled = true;
    return;
  }
  const coverage = selectedCoverage();
  if (!coverage || !coverage.start_date || !coverage.end_date) {
    const summaryRange = state.catalogSummary?.start_date && state.catalogSummary?.end_date
      ? ` The loaded catalog covers ${formatDate(state.catalogSummary.start_date)} to ${formatDate(state.catalogSummary.end_date)}.`
      : "";
    node.textContent = `${selectedRadarLabel()} has no days in the loaded catalog.${summaryRange} Choose a radar and date range that exist in the published catalog.`;
    if (firstButton) firstButton.disabled = true;
    if (latestButton) latestButton.disabled = true;
    return;
  }
  const count = Number(coverage.item_count || 0);
  const plotReady = coverage.first_plot_ready_date && coverage.latest_plot_ready_date
    ? ` Plot-ready days found from ${formatDate(coverage.first_plot_ready_date)} to ${formatDate(coverage.latest_plot_ready_date)}.`
    : coverage.plot_ready_probe
      ? " No plot-ready raw-volume days found yet for this radar."
      : ` Choose dates first, then select one of ${available.length || count} available radar${(available.length || count) === 1 ? "" : "s"} to find plot-ready raw-volume days.`;
  node.textContent = `${selectedRadarLabel()}: ${count} catalog day${count === 1 ? "" : "s"}, ${formatDate(coverage.start_date)} to ${formatDate(coverage.end_date)}.${plotReady}`;
  const canJump = !coverage.plot_ready_probe || Boolean(coverage.first_plot_ready_date || coverage.latest_plot_ready_date);
  if (firstButton) firstButton.disabled = !canJump;
  if (latestButton) latestButton.disabled = !canJump;
}

async function refreshAvailability() {
  const radar = el("radarSelect").value;
  state.catalogAvailability = null;
  const {start, end} = selectedDateRange();
  if (radar && !start && !end) {
    const response = await api(`/api/catalog/availability?radar=${encodeURIComponent(radar)}`);
    state.catalogAvailability = await response.json();
  }
  updateAvailabilityPanel();
}

function refreshRadarOptions() {
  const select = el("radarSelect");
  if (!select || !state.radarRecords.length) return;
  const current = select.value;
  const {start, end} = selectedDateRange();
  const hasDateFilter = Boolean(start || end);
  const options = ['<option value="">Any available radar</option>'];
  state.radarRecords.forEach((radar) => {
    const coverage = radarCoverage(radar.slug);
    const available = radarAvailableForDateRange(radar.slug);
    const coverageText = coverage && coverage.start_date && coverage.end_date
      ? `${formatDate(coverage.start_date)} to ${formatDate(coverage.end_date)}`
      : "no catalog days";
    const disabled = hasDateFilter && !available ? " disabled" : "";
    const suffix = hasDateFilter ? (available ? ` - available, ${coverageText}` : ` - unavailable, ${coverageText}`) : "";
    options.push(`<option value="${radar.slug}"${disabled}>${radar.label} (${radar.radar_num})${suffix}</option>`);
  });
  select.innerHTML = options.join("");
  if (current && [...select.options].some((option) => option.value === current && !option.disabled)) {
    select.value = current;
  } else {
    select.value = "";
  }
  updateAvailabilityPanel();
}

function useAvailableDate(which) {
  const coverage = selectedCoverage();
  if (!coverage || !coverage.start_date || !coverage.end_date) {
    updateAvailabilityPanel();
    return;
  }
  const date = plotReadyDate(coverage, which);
  el("startInput").value = formatDate(date);
  el("endInput").value = formatDate(date);
  searchCatalog().catch((err) => setStatus(err.message, true));
}

function handleDateSelectionChanged() {
  refreshRadarOptions();
  updateAvailabilityPanel();
}

async function loadRadars() {
  const response = await api("/api/radars");
  const data = await response.json();
  state.radarRecords = data.radars;
  refreshRadarOptions();
}

function recentLabel(selection) {
  const radar = selection.radar ? radarLabelFromSlug(selection.radar) : "Unknown radar";
  const field = [selection.pulse, selection.time, selection.quantity].filter(Boolean).join(" ");
  return {
    title: `${radar} ${formatDate(selection.date)}`.trim(),
    detail: `${field || "metadata"}${selection.dataset ? `, ${selection.dataset}` : ""}`.trim(),
  };
}

function renderRecentSelections() {
  const node = el("recentSelections");
  if (!node) return;
  node.innerHTML = "";
  if (!state.recentSelections.length) {
    node.textContent = "No recent selections on this device yet.";
    el("clearRecentButton").disabled = true;
    return;
  }
  el("clearRecentButton").disabled = false;
  state.recentSelections.forEach((selection, index) => {
    const labels = recentLabel(selection);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-selection";
    button.dataset.recentIndex = String(index);
    const title = document.createElement("strong");
    title.textContent = labels.title;
    const detail = document.createElement("span");
    detail.textContent = labels.detail || "Open selection";
    button.append(title, detail);
    button.addEventListener("click", () => restoreRecentSelection(selection).catch((err) => setStatus(err.message, true)));
    node.append(button);
  });
}

async function loadRecentSelections() {
  const response = await api("/api/recent-selections");
  const data = await response.json();
  state.recentSelections = Array.isArray(data.items) ? data.items : [];
  renderRecentSelections();
}

async function clearRecentSelections() {
  const response = await api("/api/recent-selections", {method: "DELETE"});
  const data = await response.json();
  state.recentSelections = Array.isArray(data.items) ? data.items : [];
  renderRecentSelections();
  setStatus("Cleared recent selections stored on this computer.");
}

function rawVolumeForSelection(item, pulse, time) {
  const volumes = Array.isArray(item?.raw_volumes) ? item.raw_volumes : [];
  return volumes.find((volume) => volume.pulse === pulse && volume.time === time) || null;
}

async function recordRecentSelection(item, pulse, time, quantity, dataset) {
  if (!item?.radar || !item.date) return;
  const volume = rawVolumeForSelection(item, pulse, time);
  const payload = {
    radar: item.radar,
    date: item.date,
    pulse,
    time,
    quantity,
    dataset: dataset || "",
    item_label: itemLabel(item),
    object_key: volume?.object_key || item.object_key || "",
    object_url: volume?.object_url || item.object_url || "",
    source_type: item.source_type || "",
  };
  try {
    const response = await api("/api/recent-selections", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    state.recentSelections = Array.isArray(data.items) ? data.items : [];
    renderRecentSelections();
  } catch (_err) {
    // Recents should never interrupt plotting.
  }
}

async function restoreRecentSelection(selection) {
  if (!selection?.radar || !selection.date) throw new Error("Recent selection is missing radar or date.");
  const radarSelect = el("radarSelect");
  if ([...radarSelect.options].some((option) => option.value === selection.radar && !option.disabled)) {
    radarSelect.value = selection.radar;
  }
  el("startInput").value = formatDate(selection.date);
  el("endInput").value = formatDate(selection.date);
  el("pulseSelect").value = "";
  setStatus(`Restoring recent selection ${radarLabelFromSlug(selection.radar)} ${formatDate(selection.date)}...`);
  await searchCatalog();
  const itemIndex = state.items.findIndex((item) => item.radar === selection.radar && item.date === selection.date);
  if (itemIndex < 0) throw new Error("The recent selection is not in the current catalog.");
  el("itemSelect").value = String(itemIndex);
  state.activeItem = state.items[itemIndex];
  await prepareActiveItemForDisplay();
  if (selection.pulse && [...el("pulseSelect").options].some((option) => option.value === selection.pulse)) {
    el("pulseSelect").value = selection.pulse;
  }
  refreshVariableControls(state.activeItem);
  if (selection.quantity && [...el("quantitySelect").options].some((option) => option.value === selection.quantity)) {
    el("quantitySelect").value = selection.quantity;
  }
  refreshTimeControls();
  if (selection.time && [...el("timeSelect").options].some((option) => option.value === selection.time)) {
    el("timeSelect").value = selection.time;
  }
  refreshElevationControls(selection.dataset || "");
  if (selection.dataset && [...el("datasetInput").options].some((option) => option.value === selection.dataset)) {
    el("datasetInput").value = selection.dataset;
  }
  updateTimeStepOutput();
  scheduleVisiblePreviews(0);
}

function refreshFacetControls(items) {
  const pulses = [...new Set(items.flatMap((item) => plotReadyPulsesForItem(item)))].sort();
  const selectedPulseValue = el("pulseSelect").value;
  el("pulseSelect").innerHTML = '<option value="">Any</option>' + pulses.map((value) => `<option value="${value}">${value}</option>`).join("");
  el("pulseSelect").value = pulses.includes(selectedPulseValue) ? selectedPulseValue : "";
}

function itemKey(item) {
  return item ? `${item.radar}:${item.date}` : "";
}

function itemLabel(item) {
  return `${item.radar} ${formatDate(item.date)}`;
}

function itemByKey(key) {
  return state.items.find((item) => itemKey(item) === key) || null;
}

function itemIndexByKey(key) {
  return state.items.findIndex((item) => itemKey(item) === key);
}

function refreshItemControls(items) {
  const previousKey = itemKey(state.activeItem);
  el("itemSelect").innerHTML = items
    .map((item, index) => `<option value="${index}">${itemLabel(item)}</option>`)
    .join("");
  const selectedIndex = Math.max(0, items.findIndex((item) => itemKey(item) === previousKey));
  state.activeItem = items.length ? items[selectedIndex] : null;
  if (items.length) el("itemSelect").value = String(selectedIndex);
  refreshVariableControls(state.activeItem);
  refreshTimeControls();
  refreshElevationControls();
  refreshAllPanelControls();
}

function uniqueSorted(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null && String(value) !== "").map(String))].sort();
}

function rawVolumeKey(pulse, time) {
  return `${pulse || ""}|${time || ""}`;
}

function rawVolumeKeySet(item) {
  return new Set((item && Array.isArray(item.raw_volumes) ? item.raw_volumes : []).map((volume) => rawVolumeKey(volume.pulse, volume.time)));
}

function isRawVolumeCatalogEntry(item) {
  return Boolean(item && item.source_type === "raw_volume_day");
}

function rawVolumeItemHasFiles(item) {
  return Boolean(isRawVolumeCatalogEntry(item) && Array.isArray(item.raw_volumes) && item.raw_volumes.length);
}

function recordHasRawVolume(item, record, keys = rawVolumeKeySet(item)) {
  return !isRawVolumeCatalogEntry(item) || keys.has(rawVolumeKey(record.pulse, record.time));
}

function isPlotVariableQuantity(quantity) {
  const upper = String(quantity || "").toUpperCase();
  return Boolean(upper) && !upper.includes("NOISE");
}

function plotReadyPulsesForItem(item) {
  if (!item) return [];
  if (isRawVolumeCatalogEntry(item)) return rawVolumeItemHasFiles(item) ? uniqueSorted(item.raw_volumes.map((volume) => volume.pulse)) : [];
  return uniqueSorted(item.pulses || []);
}

function plotReadyQuantitiesForItem(item, pulse = "") {
  if (!item) return [];
  const records = Array.isArray(item.quantity_records) ? item.quantity_records : [];
  if (records.length) {
    const keys = rawVolumeKeySet(item);
    return uniqueSorted(records
      .filter((record) => (
        (!pulse || record.pulse === pulse)
        && isPlotVariableQuantity(record.quantity)
        && recordHasRawVolume(item, record, keys)
      ))
      .map((record) => record.quantity));
  }
  return uniqueSorted((item.quantities || []).filter(isPlotVariableQuantity));
}

function refreshVariableControls(item) {
  const select = el("quantitySelect");
  const selectedQuantityValue = select.value || DEFAULT_VARIABLE;
  const pulse = el("pulseSelect").value;
  const quantityOptions = plotReadyQuantitiesForItem(item, pulse);
  const options = quantityOptions.length ? quantityOptions : [DEFAULT_VARIABLE];
  select.innerHTML = options.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  if (options.includes(selectedQuantityValue)) {
    select.value = selectedQuantityValue;
  } else if (options.includes(DEFAULT_VARIABLE)) {
    select.value = DEFAULT_VARIABLE;
  } else {
    select.value = options[0];
  }
}

function availableTimesForSelection(item, pulse = selectedPulse(item), quantity = el("quantitySelect").value) {
  if (!item) return [];
  const records = Array.isArray(item.quantity_records) ? item.quantity_records : [];
  if (isRawVolumeCatalogEntry(item)) {
    if (!rawVolumeItemHasFiles(item)) return [];
    const keys = rawVolumeKeySet(item);
    if (records.length) {
      const matches = records
        .filter((record) => (
          (!pulse || record.pulse === pulse)
          && (!quantity || record.quantity === quantity)
          && isPlotVariableQuantity(record.quantity)
          && recordHasRawVolume(item, record, keys)
        ))
        .map((record) => record.time);
      return uniqueSorted(matches);
    }
    return uniqueSorted(item.raw_volumes
      .filter((volume) => !pulse || volume.pulse === pulse)
      .map((volume) => volume.time));
  }
  if (records.length) {
    const matches = records
      .filter((record) => (
        (!pulse || record.pulse === pulse)
        && (!quantity || record.quantity === quantity)
        && isPlotVariableQuantity(record.quantity)
      ))
      .map((record) => record.time);
    return uniqueSorted(matches);
  }
  if (pulse && item.times_by_pulse && Array.isArray(item.times_by_pulse[pulse])) {
    return uniqueSorted(item.times_by_pulse[pulse]);
  }
  return uniqueSorted(item.times || []);
}

function availableElevationRecordsForSelection(
  item,
  pulse = selectedPulse(item),
  time = el("timeSelect").value,
  quantity = selectedQuantity(item, pulse, time),
) {
  if (!item || !pulse || !time || !quantity) return [];
  const records = Array.isArray(item.quantity_records) ? item.quantity_records : [];
  const keys = rawVolumeKeySet(item);
  const matches = records.filter((record) => (
    record.dataset
    && (!pulse || record.pulse === pulse)
    && (!time || record.time === time)
    && (!quantity || record.quantity === quantity)
    && isPlotVariableQuantity(record.quantity)
    && recordHasRawVolume(item, record, keys)
  ));
  const byDataset = new Map();
  matches.forEach((record) => {
    if (!byDataset.has(record.dataset)) byDataset.set(record.dataset, record);
  });
  return [...byDataset.values()].sort((left, right) => {
    const leftElevation = Number(left.elevation_deg);
    const rightElevation = Number(right.elevation_deg);
    if (Number.isFinite(leftElevation) && Number.isFinite(rightElevation) && leftElevation !== rightElevation) {
      return leftElevation - rightElevation;
    }
    return String(left.dataset).localeCompare(String(right.dataset));
  });
}

function elevationOptionLabel(record) {
  const elevation = Number(record.elevation_deg);
  const elevationText = Number.isFinite(elevation) ? `${elevation.toFixed(2)} deg` : "elevation n/a";
  return `${elevationText} (${record.dataset})`;
}

function sweepLabel(metadata) {
  const dataset = metadata?.dataset ? `sweep ${metadata.dataset}` : "sweep n/a";
  return `${dataset}, ${elevationLabel(metadata?.elevation_deg)}`;
}

function refreshElevationControls(preferredValue = optionalInputValue("datasetInput")) {
  const select = el("datasetInput");
  if (!select) return;
  const records = availableElevationRecordsForSelection(state.activeItem);
  if (!records.length) {
    select.innerHTML = '<option value="">Auto / first available elevation</option>';
    select.value = "";
    select.disabled = true;
    return;
  }
  select.innerHTML = records
    .map((record) => `<option value="${escapeHtml(record.dataset)}">${escapeHtml(elevationOptionLabel(record))}</option>`)
    .join("");
  const values = records.map((record) => String(record.dataset));
  select.value = values.includes(String(preferredValue || "")) ? String(preferredValue) : values[0];
  select.disabled = records.length < 2;
}

function availablePanelVariables(item, pulse = selectedPulseForItem(item)) {
  return plotReadyQuantitiesForItem(item, pulse);
}

function availablePanelElevations(item, pulse, time, quantity) {
  return availableElevationRecordsForSelection(item, pulse, time, quantity);
}

function panelSelection(index) {
  const selection = state.panelSelections[index] || {};
  let item = itemByKey(selection.itemKey);
  if (!item && index === 0) item = state.activeItem;
  if (!item && state.items.length) item = state.items[index % state.items.length];
  const pulse = selectedPulseForItem(item, selection.quantity || DEFAULT_VARIABLE);
  const quantityOptions = availablePanelVariables(item, pulse);
  const quantity = quantityOptions.includes(selection.quantity)
    ? selection.quantity
    : quantityOptions.includes(DEFAULT_VARIABLE)
      ? DEFAULT_VARIABLE
      : quantityOptions[0] || DEFAULT_VARIABLE;
  const times = availableTimesForSelection(item, pulse, quantity);
  const time = state.comparisonLinks.time
    ? el("timeSelect").value || times[0] || ""
    : times.includes(selection.time)
      ? selection.time
      : times[0] || "";
  return {
    item,
    itemKey: itemKey(item),
    quantity,
    dataset: selection.dataset || "",
    time,
  };
}

function setPanelSelection(index, patch) {
  state.panelSelections[index] = {
    ...(state.panelSelections[index] || {}),
    ...patch,
  };
}

function syncLinkedPanelSelection(sourceIndex, patch) {
  if (state.panelCount !== 4) return;
  const linkedPatch = {};
  if (Object.hasOwn(patch, "quantity") && state.comparisonLinks.variable) linkedPatch.quantity = patch.quantity;
  if (Object.hasOwn(patch, "dataset") && state.comparisonLinks.elevation) linkedPatch.dataset = patch.dataset;
  if (Object.hasOwn(patch, "time") && state.comparisonLinks.time) linkedPatch.time = patch.time;
  if (!Object.keys(linkedPatch).length) return;
  visiblePanelIndices().forEach((index) => {
    if (index !== sourceIndex) setPanelSelection(index, linkedPatch);
  });
}

function initializePanelSelections() {
  panels().forEach((_panel, index) => {
    const current = state.panelSelections[index] || {};
    let item = itemByKey(current.itemKey);
    if (index === 0) item = state.activeItem || item || state.items[0] || null;
    if (!item && state.items.length) item = state.items[index % state.items.length];
    const quantity = index === 0 ? (el("quantitySelect").value || current.quantity || DEFAULT_VARIABLE) : (current.quantity || DEFAULT_VARIABLE);
    const dataset = index === 0 ? (optionalInputValue("datasetInput") || current.dataset || "") : (current.dataset || "");
    const pulse = selectedPulseForItem(item, quantity);
    const times = availableTimesForSelection(item, pulse, quantity);
    const time = current.time && times.includes(current.time)
      ? current.time
      : el("timeSelect").value && times.includes(el("timeSelect").value)
        ? el("timeSelect").value
        : times[0] || "";
    setPanelSelection(index, {itemKey: itemKey(item), quantity, dataset, time});
  });
}

function selectedPanelItems() {
  return panels()
    .slice(0, state.panelCount === 4 ? 4 : 1)
    .map((_panel, index) => panelSelection(index).item)
    .filter(Boolean);
}

function linkedComparisonTimes() {
  if (state.panelCount !== 4) return [];
  const times = [];
  panels().forEach((_panel, index) => {
    const selection = panelSelection(index);
    const pulse = selectedPulseForItem(selection.item, selection.quantity);
    times.push(...availableTimesForSelection(selection.item, pulse, selection.quantity));
  });
  return uniqueSorted(times);
}

function refreshPanelControls(index) {
  const panel = panels()[index];
  if (!panel) return;
  const itemSelect = panel.querySelector(".panel-item-select");
  const variableSelect = panel.querySelector(".panel-variable-select");
  const timeSelect = panel.querySelector(".panel-time-select");
  const elevationSelect = panel.querySelector(".panel-elevation-select");
  if (!itemSelect || !variableSelect || !timeSelect || !elevationSelect) return;

  const selection = panelSelection(index);
  itemSelect.innerHTML = state.items
    .map((item) => `<option value="${escapeHtml(itemKey(item))}">${escapeHtml(itemLabel(item))}</option>`)
    .join("");
  itemSelect.disabled = state.items.length === 0;
  if (selection.itemKey) itemSelect.value = selection.itemKey;

  const pulse = selectedPulseForItem(selection.item, selection.quantity);
  const variables = availablePanelVariables(selection.item, pulse);
  const variableOptions = variables.length ? variables : [DEFAULT_VARIABLE];
  const quantity = variableOptions.includes(selection.quantity)
    ? selection.quantity
    : variableOptions.includes(DEFAULT_VARIABLE)
      ? DEFAULT_VARIABLE
      : variableOptions[0];
  variableSelect.innerHTML = variableOptions.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  variableSelect.value = quantity;
  variableSelect.disabled = variableOptions.length < 2;

  const times = availableTimesForSelection(selection.item, pulse, quantity);
  const linkedTime = el("timeSelect").value;
  let time = state.comparisonLinks.time ? linkedTime : selection.time;
  if (!times.length) {
    timeSelect.innerHTML = '<option value="">No times</option>';
    timeSelect.value = "";
    timeSelect.disabled = true;
    elevationSelect.innerHTML = '<option value="">No elevation</option>';
    elevationSelect.value = "";
    elevationSelect.disabled = true;
    setPanelSelection(index, {itemKey: selection.itemKey, quantity, time: "", dataset: ""});
    return;
  }
  if (!times.includes(time)) time = state.comparisonLinks.time ? linkedTime : times[0];
  const missingLinkedTime = state.comparisonLinks.time && time && !times.includes(time);
  timeSelect.innerHTML = [
    ...(missingLinkedTime ? [`<option value="${escapeHtml(time)}">${escapeHtml(time)} unavailable</option>`] : []),
    ...times.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(timeOptionLabel(selection.item, pulse, value))}</option>`),
  ].join("");
  timeSelect.value = time;
  timeSelect.disabled = state.comparisonLinks.time || times.length < 2;
  if (!state.comparisonLinks.time) setPanelSelection(index, {itemKey: selection.itemKey, quantity, time});

  const elevations = availablePanelElevations(selection.item, pulse, time, quantity);
  if (!elevations.length) {
    elevationSelect.innerHTML = '<option value="">No elevation for time</option>';
    elevationSelect.value = "";
    elevationSelect.disabled = true;
    setPanelSelection(index, {itemKey: selection.itemKey, quantity, time, dataset: ""});
    return;
  }
  elevationSelect.innerHTML = elevations
    .map((record) => `<option value="${escapeHtml(record.dataset)}">${escapeHtml(elevationOptionLabel(record))}</option>`)
    .join("");
  const datasets = elevations.map((record) => String(record.dataset));
  const dataset = datasets.includes(String(selection.dataset || "")) ? String(selection.dataset) : datasets[0];
  elevationSelect.value = dataset;
  elevationSelect.disabled = datasets.length < 2;
  setPanelSelection(index, {itemKey: selection.itemKey, quantity, time, dataset});
}

function refreshAllPanelControls() {
  panels().forEach((_panel, index) => refreshPanelControls(index));
}

function visiblePanelIndices() {
  return state.panelCount === 4 ? [0, 1, 2, 3] : [0];
}

function scheduleVisiblePreviews(delayMs = 250, options = {}) {
  visiblePanelIndices().forEach((index) => schedulePreview(index, delayMs, options));
}

async function loadVisiblePpisNow(options = {}) {
  cancelPendingPreviews();
  const results = await Promise.allSettled(visiblePanelIndices().map((index) => loadPpi(index, null, "", options)));
  const rejected = results.find((result) => result.status === "rejected");
  if (rejected) throw rejected.reason;
}

function itemHasTimeMetadata(item) {
  if (!item) return false;
  if (isRawVolumeCatalogEntry(item)) return rawVolumeItemHasFiles(item);
  if (Array.isArray(item.quantity_records) && item.quantity_records.length) return true;
  if (Array.isArray(item.times) && item.times.length) return true;
  return Object.values(item.times_by_pulse || {}).some((times) => Array.isArray(times) && times.length);
}

function rawCacheTimeKey(pulse, time) {
  return `${pulse || ""}:${time || ""}`;
}

function timeOptionLabel(item, pulse, time) {
  const cached = state.rawCacheByItem.get(itemKey(item));
  return cached && cached.has(rawCacheTimeKey(pulse, time)) ? `${time} cached` : time;
}

async function refreshRawCacheStatus(item) {
  if (!rawVolumeItemHasFiles(item)) return;
  const response = await api(`/api/raw-cache/day/${item.radar}/${item.date}`);
  const payload = await response.json();
  const cached = new Set();
  (payload.files || []).forEach((file) => {
    if (file.cached) cached.add(rawCacheTimeKey(file.pulse, file.time));
  });
  state.rawCacheByItem.set(itemKey(item), cached);
  setActivityStage(
    cached.size ? "Raw cache ready" : "Raw cache checked",
    `${cached.size} cached file${cached.size === 1 ? "" : "s"} for ${itemLabel(item)}`
  );
  refreshTimeControls();
}

function refreshTimeControls() {
  const item = state.activeItem;
  const selected = el("timeSelect").value;
  const pulse = selectedPulse(item);
  const times = state.panelCount === 4 && state.comparisonLinks.time ? linkedComparisonTimes() : availableTimesForSelection(item);
  el("timeSelect").innerHTML = times
    .map((time) => `<option value="${escapeHtml(time)}">${escapeHtml(timeOptionLabel(item, pulse, time))}</option>`)
    .join("");
  if (times.includes(selected)) {
    el("timeSelect").value = selected;
  } else if (times.length) {
    el("timeSelect").value = times[0];
  }
  el("timeSelect").disabled = times.length === 0 || (state.panelCount === 4 && !state.comparisonLinks.time);
  updateTimeStepOutput();
  refreshElevationControls();
  refreshAllPanelControls();
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
  const quantities = item.quantities && item.quantities.length ? item.quantities.join(", ") : "no variables";
  const timeSummary = times.length ? `${times.length} time(s), ${times[0]} to ${times[times.length - 1]}` : "no times";
  return `${timeSummary}; ${pulses}; ${quantities}`;
}

async function hydrateItemDetails(item) {
  if (!item || itemHasTimeMetadata(item)) return item;
  const key = itemKey(item);
  if (state.hydratingItems.has(key)) return state.hydratingItems.get(key);
  const task = (async () => {
    setStatus(`Catalog day found for ${itemLabel(item)}. Looking for its raw-volume time and field index...`);
    setActivityStage("Field index loading", itemLabel(item));
    panels().forEach((panel) => setPanelMessage(panel, `Loading ${itemLabel(item)} time and field index...`));
    let updated;
    try {
      const response = await api(`/api/item/${item.radar}/${item.date}/hydrate`);
      updated = replaceCatalogItem(await response.json());
    } catch (err) {
      const message = `Catalog day ${itemLabel(item)} exists, but it is not plot-ready yet: ${err.message}`;
      setStatus(message, true);
      setActivityStage("Field index unavailable", err.message, true, () => hydrateItemDetails(item));
      panels().forEach((panel) => setPanelMessage(panel, message, true));
      return item;
    }
    refreshFacetControls(state.items);
    refreshVariableControls(updated);
    refreshTimeControls();
    refreshElevationControls();
    if (itemHasTimeMetadata(updated)) {
      setStatus(`Plot-ready index loaded for ${itemLabel(updated)}: ${describeItemMetadata(updated)}.`);
      setActivityStage("Field index loaded", `${itemLabel(updated)}: ${describeItemMetadata(updated)}`);
      refreshRawCacheStatus(updated).catch((_err) => {
        // Cache badges are optional; plotting still works if the cache status request fails.
      });
    } else {
      setStatus(`Catalog day ${itemLabel(updated)} exists, but no pulse/time/variable metadata was found.`, true);
      setActivityStage("Field index empty", itemLabel(updated), true, () => hydrateItemDetails(updated));
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
  refreshElevationControls();
  if (!availableTimesForSelection(item).length) {
    setStatus(`No plot-ready radar times for ${itemLabel(item)} with the selected pulse and variable. Choose Any, another variable, or another available day.`, true);
  }
  return item;
}

async function searchCatalog() {
  const searchRequestId = ++state.searchRequestSeq;
  cancelPendingPreviews();
  normalizeDateInput("startInput");
  normalizeDateInput("endInput");
  const params = new URLSearchParams();
  const radar = el("radarSelect").value;
  const start = yyyymmdd(el("startInput").value);
  const end = yyyymmdd(el("endInput").value);
  const pulse = el("pulseSelect").value;
  if (radar) params.set("radar", radar);
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  if (pulse) params.set("pulse", pulse);

  setActivityStage("Catalog search", dateRangeLabel(start, end));
  const response = await api(`/api/catalog?${params.toString()}`);
  const data = await response.json();
  if (searchRequestId !== state.searchRequestSeq) return;
  state.items = data.items;
  refreshFacetControls(state.items);
  refreshItemControls(state.items);
  if (state.items.length) {
    const radars = [...new Set(state.items.map((item) => item.radar))].sort();
    const dates = state.items.map((item) => item.date).sort();
    const radarText = radars.map(radarLabelFromSlug).join(", ");
    setStatus(`Catalog search: ${state.items.length} item(s), ${radarText}, ${formatDate(dates[0])} to ${formatDate(dates[dates.length - 1])}.`);
    setActivityStage("Catalog search complete", `${state.items.length} item(s) found`);
    await prepareActiveItemForDisplay();
    if (searchRequestId !== state.searchRequestSeq) return;
    if (state.panelCount === 4) {
      initializePanelSelections();
      refreshTimeControls();
      refreshAllPanelControls();
    }
    scheduleVisiblePreviews();
  } else {
    const summary = await catalogSummary();
    const requestedDates = start && end ? `${formatDate(start)} to ${formatDate(end)}` : start ? `from ${formatDate(start)}` : end ? `to ${formatDate(end)}` : "all dates";
    const selectedRadar = radar ? el("radarSelect").selectedOptions[0]?.textContent || radar : "any radar";
    const catalogRange = summary.start_date && summary.end_date
      ? `The loaded catalog currently covers ${formatDate(summary.start_date)} to ${formatDate(summary.end_date)}.`
      : "The loaded catalog currently has no dated items.";
    const radarSummary = radar && summary.by_radar && summary.by_radar[radar]
      ? ` ${selectedRadar} covers ${formatDate(summary.by_radar[radar].start_date)} to ${formatDate(summary.by_radar[radar].end_date)}.`
      : "";
    const availableForRange = availableRadarsForDateRange();
    const radarList = availableForRange.length
      ? ` Available radars for ${requestedDates}: ${summarizeRadarList(availableForRange)}.`
      : ` No radars in the loaded catalog overlap ${requestedDates}.`;
    const facetSummary = [pulse ? `pulse ${pulse}` : ""].filter(Boolean).join(", ");
    const message = `No catalog data for ${selectedRadar}, ${requestedDates}${facetSummary ? `, ${facetSummary}` : ""}. ${catalogRange}${radarSummary}${radarList} Choose a date and radar inside the published catalog range, or press Refresh if the catalog endpoint has changed.`;
    setStatus(message, true);
    setActivityStage("Catalog search found no data", requestedDates, true, refreshCatalogAndSearch);
    panels().forEach((panel) => {
      clearPanel(panel, true);
      setPanelMessage(panel, message, true);
    });
  }
}

async function refreshCatalogAndSearch() {
  state.catalogSummary = null;
  const ok = await loadStatus();
  if (!ok) return;
  await searchCatalog();
}

function selectedQuantity(item = state.activeItem, pulse = selectedPulse(item), time = el("timeSelect").value) {
  const explicit = el("quantitySelect").value;
  if (explicit) return explicit;
  if (!item) return "";
  const records = Array.isArray(item.quantity_records) ? item.quantity_records : [];
  const match = records.find((record) => (!pulse || record.pulse === pulse) && (!time || record.time === time));
  if (match) return match.quantity;
  return item.quantities && item.quantities.length ? item.quantities[0] : DEFAULT_VARIABLE;
}

function selectedPulseForItem(item = state.activeItem, quantity = el("quantitySelect").value || DEFAULT_VARIABLE) {
  const explicit = el("pulseSelect").value;
  if (explicit) return explicit;
  if (!item) return "";
  const preferred = plotReadyPulsesForItem(item).find((pulse) => availableTimesForSelection(item, pulse, quantity).length);
  return preferred || (item.pulses && item.pulses.length ? item.pulses[0] : "");
}

function selectedPulse(item = state.activeItem) {
  return selectedPulseForItem(item);
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
  if (el("noiseFloorInput").checked) {
    params.noise_floor_enabled = true;
    params.noise_floor_method = el("noiseFloorMethodSelect").value || "estimated";
    params.noise_floor_margin_db = Number(el("noiseFloorMarginInput").value || DEFAULT_CLEANUP_MARGIN_DB);
    params.noise_floor_operation = "mask";
    params.noise_floor_percentile = 10;
    params.noise_floor_window_bins = 11;
    params.noise_floor_texture_enabled = true;
    params.noise_floor_texture_db = 10;
    params.noise_floor_texture_near_margin_db = 14;
    params.noise_floor_texture_support_db = 6;
    params.noise_floor_texture_max_db = 30;
    params.noise_floor_texture_min_similar_neighbors = 1;
    params.qc_mode = DEFAULT_QC_MODE;
    params.qc_companion_enabled = true;
    params.qc_static_clutter_enabled = true;
  }
  const backgroundModelPath = el("backgroundModelPathInput").value.trim();
  if (el("noiseFloorInput").checked || backgroundModelPath) {
    params.qc_background_model_enabled = true;
    if (backgroundModelPath) params.qc_background_model_path = backgroundModelPath;
    params.qc_background_persistent_frequency_min = 0.60;
    params.qc_background_min_samples = 20;
    params.qc_background_static_vrad_frequency_min = 0.40;
    params.qc_background_low_sqi_frequency_min = 0.40;
    params.qc_background_dbzh_excess_max_db = 12;
    params.qc_background_evidence_score_threshold = 1;
  }
  return params;
}

function appendFilterParams(params) {
  Object.entries(filterParams()).forEach(([key, value]) => params.set(key, String(value)));
  const displayMin = optionalInputValue("displayMinInput");
  const displayMax = optionalInputValue("displayMaxInput");
  if (displayMin !== "") params.set("display_min", String(Number(displayMin)));
  if (displayMax !== "") params.set("display_max", String(Number(displayMax)));
  return params;
}

function fieldParams(dataset = optionalInputValue("datasetInput")) {
  const params = new URLSearchParams({
    palette: el("paletteSelect").value,
    max_rays: "360",
    max_bins: "360",
  });
  if (dataset) params.set("dataset", dataset);
  appendFilterParams(params);
  return params;
}

function ppiUrl(item, time, pulse = selectedPulse(item), quantity = selectedQuantity(item, pulse, time), dataset = optionalInputValue("datasetInput")) {
  const encodedQuantity = encodeURIComponent(quantity);
  const encodedPulse = encodeURIComponent(pulse);
  return `/api/ppi/${item.radar}/${item.date}/${encodedPulse}/${time}/${encodedQuantity}?${fieldParams(dataset).toString()}`;
}

function ppiFrameKey(item, time, pulse, quantity, dataset) {
  return ppiUrl(item, time, pulse, quantity, dataset);
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
  const selection = state.panelCount === 4
    ? panelSelection(panelIndex)
    : {
      item: state.activeItem,
      quantity: el("quantitySelect").value || DEFAULT_VARIABLE,
      dataset: optionalInputValue("datasetInput"),
    };
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
    setPanelSelection(panelIndex, {itemKey: itemKey(item), quantity, time, dataset: panel.dataset.fieldDataset});
    refreshPanelControls(panelIndex);
  }
  const stats = ppi.stats || {};
  const quality = qcDisplaySummary(ppi);
  const title = `${itemLabel(item)} ${pulse} ${time} ${quantity} ${elevationLabel(meta.elevation_deg)}`;
  const detail = `${ppi.source_shape[0]} rays x ${ppi.source_shape[1]} gates, ${sweepLabel(meta)}, ${ppi.palette}, display=${fmtNumber(stats.scale_min, 1)} to ${fmtNumber(stats.scale_max, 1)}, ${quality.detail}`;
  const titleNode = panel.querySelector(".panel-title");
  titleNode.textContent = title;
  titleNode.title = `${title}\n${detail}`;
  setPanelMessage(
    panel,
    `${ppi.source_shape[0]} x ${ppi.source_shape[1]} gates | ${sweepLabel(meta)} | ${quality.short}`,
    false,
    detail,
  );
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

async function loadPpi(panelIndex = 0, selectionOverride = null, timeOverride = "", options = {}) {
  const loadStart = performance.now();
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
  let item = selection.item;
  if (!item) return;
  item = await hydrateItemDetails(item);
  refreshRawCacheStatus(item).catch((_err) => {
    // Cache status is an optimization; do not interrupt plotting if it is unavailable.
  });
  const quantity = selection.quantity || selectedQuantity(item);
  const pulse = selectedPulseForItem(item, quantity);
  const availableTimes = availableTimesForSelection(item, pulse, quantity);
  const requestedTime = timeOverride || (state.panelCount === 4 ? selection.time || el("timeSelect").value : el("timeSelect").value) || availableTimes[0] || "";
  const time = state.panelCount === 4 && state.comparisonLinks.time
    ? requestedTime
    : (availableTimes.includes(requestedTime) ? requestedTime : availableTimes[0]);
  const panel = panels()[panelIndex];
  const hasPreviousFrame = Boolean(state.panelMeta.get(panelIndex));
  const keepPrevious = options.keepPrevious !== false && hasPreviousFrame;
  if (state.panelCount === 4 && state.comparisonLinks.time && requestedTime && !availableTimes.includes(requestedTime)) {
    if (!keepPrevious) clearPanel(panel);
    panel.querySelector(".panel-title").textContent = `${itemLabel(item)} ${pulse || ""} ${requestedTime} ${quantity || ""}`.trim();
    setPanelMessage(panel, `Linked time ${requestedTime} is not available for ${itemLabel(item)} ${quantity}. Choose another linked time or panel item.`, true);
    return;
  }
  if (!time || !pulse || !quantity) {
    if (!keepPrevious) clearPanel(panel);
    panel.querySelector(".panel-title").textContent = itemLabel(item);
    setPanelMessage(panel, `No available time for ${itemLabel(item)} with the selected pulse and variable.`, true);
    setStatus(`No available radar time for ${itemLabel(item)} with the selected pulse and variable.`, true);
    return;
  }
  const elevations = availablePanelElevations(item, pulse, time, quantity);
  const elevationDatasets = elevations.map((record) => String(record.dataset));
  let dataset = selection.dataset || "";
  if (dataset && elevationDatasets.length && !elevationDatasets.includes(String(dataset))) dataset = "";
  if (!dataset && elevationDatasets.length) dataset = elevationDatasets[0];
  if (state.panelCount === 4) {
    setPanelSelection(panelIndex, {itemKey: itemKey(item), quantity, time, dataset});
    refreshPanelControls(panelIndex);
  }

  const requestId = String(++state.previewRequestSeq);
  panel.dataset.previewRequestId = requestId;
  const preserveView = shouldPreservePanelView(panel, item, options);
  panel.dataset.radar = item.radar;
  panel.dataset.date = item.date;
  panel.dataset.time = time;
  panel.dataset.pulse = pulse;
  panel.dataset.quantity = quantity;
  panel.dataset.fieldDataset = dataset;
  panel.querySelector(".panel-title").textContent = `${itemLabel(item)} ${pulse} ${time} ${quantity}`;
  const frameKey = ppiFrameKey(item, time, pulse, quantity, dataset);
  const url = ppiUrl(item, time, pulse, quantity, dataset);
  const cached = cachedPpiFrame(frameKey);
  if (cached) {
    state.panelMeta.set(panelIndex, cached);
    renderPanel(panel, cached, {preserveView});
    updatePanelAfterPpiLoad(panelIndex, panel, item, pulse, time, quantity, cached);
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

  try {
    const ppi = await fetchPpiFrame(frameKey, url);
    if (panel.dataset.previewRequestId !== requestId) return;
    state.panelMeta.set(panelIndex, ppi);
    renderPanel(panel, ppi, {preserveView});
    updatePanelAfterPpiLoad(panelIndex, panel, item, pulse, time, quantity, ppi);
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
    if (!keepPrevious) clearPanel(panel);
    setPanelMessage(panel, `Frame failed: ${err.message}. ${keepPrevious ? "Keeping previous frame visible." : ""}`.trim(), true);
    setStatus(`Plot failed: ${err.message}`, true);
    setActivityStage("Frame failed", err.message, true, () => loadPpi(panelIndex, selectionOverride, timeOverride, options));
    throw err;
  } finally {
    setPanelLoading(panel, "", false);
  }
}

function clearPanel(panel, resetMetadata = false) {
  setPanelLoading(panel, "", false);
  panel.querySelector(".tile-layer").innerHTML = "";
  panel.querySelector(".tile-layer").dataset.tileSignature = "";
  const legend = panel.querySelector(".colour-legend");
  if (legend) legend.hidden = true;
  if (resetMetadata) {
    panel.querySelector(".panel-title").textContent = "";
    delete panel.dataset.radar;
    delete panel.dataset.date;
    delete panel.dataset.time;
    delete panel.dataset.pulse;
    delete panel.dataset.quantity;
    delete panel.dataset.fieldDataset;
    delete panel.dataset.previewRequestId;
    state.panelMeta.delete(panels().indexOf(panel));
  }
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
  const width = Math.max(1, panel.clientWidth);
  const height = Math.max(1, panel.clientHeight);
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
  const sourceTransform = sourcePanel._mapTransform;
  const center = pixelToLonLat(sourceTransform.width / 2, sourceTransform.height / 2, sourceTransform);
  visiblePanelIndices().forEach((index) => {
    const panel = panels()[index];
    if (!panel || panel === sourcePanel) return;
    const ppi = state.panelMeta.get(index);
    if (!ppi) return;
    const width = Math.max(1, panel.clientWidth);
    const height = Math.max(1, panel.clientHeight);
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
  await prepareActiveItemForDisplay();
  if (state.panelCount === 4) {
    setPanelSelection(0, {itemKey: itemKey(state.activeItem), dataset: optionalInputValue("datasetInput")});
    refreshAllPanelControls();
  }
  scheduleVisiblePreviews(0);
}

function resetPanelView(panel) {
  const index = Number(panel.dataset.panel);
  const ppi = state.panelMeta.get(index);
  if (!ppi) return;
  delete panel._mapTransform;
  renderPanel(panel, ppi, {preserveView: false});
  syncLinkedViewFromPanel(panel);
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
  if (count === 4 && state.items.length) {
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
  const output = composePanelScreenshot(panel, false);
  if (!output) return;
  const capture = document.createElement("img");
  capture.src = output.toDataURL("image/png");
  capture.alt = "Captured radar PPI";
  el("captures").prepend(capture);
}

function composePanelScreenshot(panel, includeTiles = true) {
  const source = panel?.querySelector(".ppi-canvas");
  if (!source || !source.width || !source.height) return null;
  const output = document.createElement("canvas");
  output.width = source.width;
  output.height = source.height;
  const ctx = output.getContext("2d");
  ctx.fillStyle = el("basemapSelect").value === "dark" ? "#1d2730" : "#dfe6ec";
  ctx.fillRect(0, 0, output.width, output.height);
  if (includeTiles && el("basemapSelect").value === "osm") {
    panel.querySelectorAll(".tile-layer img").forEach((image) => {
      if (!image.complete || image.naturalWidth <= 0) return;
      ctx.drawImage(image, parseFloat(image.style.left) || 0, parseFloat(image.style.top) || 0, parseFloat(image.style.width) || image.width, parseFloat(image.style.height) || image.height);
    });
  }
  ctx.drawImage(source, 0, 0);
  ctx.drawImage(panel.querySelector(".map-overlay-canvas"), 0, 0);
  return output;
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

function currentPrimaryExportSelection(format) {
  const panel = panels()[0];
  const panelHasField = Boolean(panel?.dataset.radar && panel.dataset.date);
  const item = state.activeItem;
  if (!item && !panelHasField) throw new Error("Search the catalog and select a source object before exporting.");

  const request = {
    radar: panel.dataset.radar || item.radar,
    date: panel.dataset.date || item.date,
    format,
    palette: el("paletteSelect").value,
    filters: filterParams(),
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
      request.times = times.length ? times : [time];
      request.frame_delay_ms = Number(el("delayInput").value || 600);
    }
    if (el("paletteSelect").value === "custom") {
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
    y: event.clientY - rect.top,
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
  panel._mapTransform = updateTileTransform({
    ...transform,
    zoom,
    width: Math.max(1, panel.clientWidth),
    height: Math.max(1, panel.clientHeight),
    left: world.x - x,
    top: world.y - y,
  });
  renderPanel(panel, ppi);
  syncLinkedViewFromPanel(panel);
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

function touchPoint(panel, touch) {
  const rect = panel.getBoundingClientRect();
  return {
    x: touch.clientX - rect.left,
    y: touch.clientY - rect.top,
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
}

function applyComparisonLinkState() {
  [
    ["linkViewInput", "view"],
    ["linkTimeInput", "time"],
    ["linkVariableInput", "variable"],
    ["linkElevationInput", "elevation"],
  ].forEach(([id, key]) => {
    const node = el(id);
    if (node) node.checked = state.comparisonLinks[key] !== false;
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

function attachEvents() {
  applyPointerFieldState();
  applyComparisonLinkState();
  el("refreshButton").addEventListener("click", () => refreshCatalogAndSearch().catch((err) => reportLoadError(err, "Refresh failed")));
  el("retryLoadButton").addEventListener("click", () => retryLastLoad().catch((err) => reportLoadError(err, "Retry failed")));
  el("searchButton").addEventListener("click", () => searchCatalog().catch((err) => reportLoadError(err, "Catalog search failed")));
  el("radarSelect").addEventListener("change", () => refreshAvailability().catch((err) => setStatus(err.message, true)));
  el("helpToggle").addEventListener("change", () => {
    document.body.classList.toggle("help-tooltips", el("helpToggle").checked);
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
          setPanelSelection(0, {quantity: el("quantitySelect").value || DEFAULT_VARIABLE, dataset: ""});
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
        setPanelSelection(0, {dataset: optionalInputValue("datasetInput")});
      }
      scheduleVisiblePreviews();
    });
  });
  el("opacityInput").addEventListener("input", applyOpacity);
  el("paletteSelect").addEventListener("change", () => scheduleVisiblePreviews());
  el("basemapSelect").addEventListener("change", () => setBasemap(el("basemapSelect").value));
  ["linkViewInput", "linkTimeInput", "linkVariableInput", "linkElevationInput"].forEach((id) => {
    el(id).addEventListener("change", () => {
      updateComparisonLinkState();
      if (id === "linkTimeInput") refreshTimeControls();
      if (id === "linkVariableInput" || id === "linkElevationInput") refreshAllPanelControls();
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
  el("fitViewButton").addEventListener("click", () => visiblePanelIndices().forEach((index) => resetPanelView(panels()[index])));
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
    if (panelItemSelect) {
      panelItemSelect.addEventListener("change", async () => {
        setPanelSelection(panelIndex, {itemKey: panelItemSelect.value, quantity: DEFAULT_VARIABLE, dataset: ""});
        const item = itemByKey(panelItemSelect.value);
        if (item) await hydrateItemDetails(item);
        refreshPanelControls(panelIndex);
        refreshTimeControls();
        scheduleVisiblePreviews(0);
      });
    }
    if (panelVariableSelect) {
      panelVariableSelect.addEventListener("change", () => {
        setPanelSelection(panelIndex, {quantity: panelVariableSelect.value || DEFAULT_VARIABLE, dataset: ""});
        syncLinkedPanelSelection(panelIndex, {quantity: panelVariableSelect.value || DEFAULT_VARIABLE, dataset: ""});
        refreshPanelControls(panelIndex);
        refreshTimeControls();
        scheduleVisiblePreviews(0);
      });
    }
    if (panelTimeSelect) {
      panelTimeSelect.addEventListener("change", () => {
        setPanelSelection(panelIndex, {time: panelTimeSelect.value || "", dataset: ""});
        syncLinkedPanelSelection(panelIndex, {time: panelTimeSelect.value || "", dataset: ""});
        refreshAllPanelControls();
        updateTimeStepOutput();
        scheduleVisiblePreviews(0);
      });
    }
    if (panelElevationSelect) {
      panelElevationSelect.addEventListener("change", () => {
        setPanelSelection(panelIndex, {dataset: panelElevationSelect.value || ""});
        syncLinkedPanelSelection(panelIndex, {dataset: panelElevationSelect.value || ""});
        refreshAllPanelControls();
        scheduleVisiblePreviews(0);
      });
    }
    panel.addEventListener("wheel", (event) => {
      if (!state.panelMeta.has(Number(panel.dataset.panel))) return;
      event.preventDefault();
      const point = panelPoint(panel, event);
      const delta = event.deltaY < 0 ? 0.35 : -0.35;
      zoomPanelAt(panel, point.x, point.y, delta);
    }, {passive: false});
    panel.addEventListener("mousedown", (event) => {
      if (event.button !== 0 || !state.panelMeta.has(Number(panel.dataset.panel))) return;
      panel._dragState = {
        startX: event.clientX,
        startY: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        moved: false,
      };
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
      if (event.touches.length === 1) {
        const point = touchPoint(panel, event.touches[0]);
        panel._touchState = {mode: "pan", lastX: point.x, lastY: point.y};
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
        panPanel(panel, point.x - stateForTouch.lastX, point.y - stateForTouch.lastY);
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
        panPanel(panel, dx, dy);
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
      delete panel._dragState;
      panel.classList.remove("is-panning");
    });
  });
  window.addEventListener("keydown", handleKeyboardNavigation);
}

async function init() {
  attachEvents();
  setActivityStage("Server ready", "initialising catalog...");
  const statusOk = await loadStatus();
  if (!statusOk) return;
  await loadRadars();
  await loadRecentSelections();
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
