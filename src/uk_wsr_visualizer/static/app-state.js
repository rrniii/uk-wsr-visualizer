const TILE_SIZE = 256;
const EARTH_RADIUS_M = 6371000;
const DEFAULT_VARIABLE = "DBZH";
const DEFAULT_CLEANUP_ENABLED = true;
const DEFAULT_CLEANUP_MARGIN_DB = 0;
const DEFAULT_QC_MODE = "signal_preserving";

// Shared state for the ordered desktop scripts; no frontend build is required.
const state = {
  items: [],
  panelItemOptionsVersion: 0,
  activeItem: null,
  panelCount: 1,
  panelSelections: [{}, {}, {}, {}],
  panelDisplays: [{}, {}, {}, {}],
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
  catalogSources: [],
  catalogSourceId: "dual-pol",
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
    colour: false,
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

function parseDateInput(value, boundary = "start") {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const yearMatch = raw.match(/^(\d{4})$/);
  if (yearMatch) return `${yearMatch[1]}${boundary === "end" ? "1231" : "0101"}`;
  const monthMatch = raw.match(/^(\d{4})[-/](\d{1,2})$/);
  if (monthMatch) {
    const year = Number(monthMatch[1]);
    const month = Number(monthMatch[2]);
    if (month < 1 || month > 12) return "";
    const day = boundary === "end" ? new Date(Date.UTC(year, month, 0)).getUTCDate() : 1;
    return `${year}${String(month).padStart(2, "0")}${String(day).padStart(2, "0")}`;
  }
  const match = raw.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/)
    || raw.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (!match) return "";
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return "";
  return `${year}${String(month).padStart(2, "0")}${String(day).padStart(2, "0")}`;
}

function yyyymmdd(value) {
  return parseDateInput(value, "start");
}

function formatDate(value) {
  const compact = parseDateInput(value, "start");
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
    start: parseDateInput(el("startInput").value, "start"),
    end: parseDateInput(el("endInput").value, "end"),
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
  const raw = node.value.trim();
  const formatted = /^\d{4}[-/]\d{1,2}[-/]\d{1,2}$/.test(raw) || /^\d{8}$/.test(raw) ? formatDate(raw) : raw;
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
  const node = panel.querySelector(".panel-status");
  if (!node) return;
  node.textContent = message;
  node.title = detail || message;
  node.classList.toggle("error", isError);
  node.hidden = !message;
}

function clearPanelMessage(panel) {
  const node = panel.querySelector(".panel-status");
  if (!node) return;
  node.textContent = "";
  node.title = "";
  node.classList.remove("error");
  node.hidden = true;
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
