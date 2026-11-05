async function loadStatus() {
  setActivityStage("Server ready", "checking catalog status...");
  const response = await api("/api/status");
  const data = await response.json();
  const source = data.remote_catalog ? "remote object-store catalog" : "local catalog";
  state.catalogSourceId = data.catalog_source_id || state.catalogSourceId;
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
  const era = state.catalogSources.find((candidate) => candidate.id === state.catalogSourceId)?.label || "selected data era";
  setStatus(`Catalog loaded: ${data.item_count} item(s), ${summary.radars.length} radar(s)${range} from ${era} (${source}${detail}).`);
  setActivityStage("Catalog loaded", `${data.item_count} item(s), ${summary.radars.length} radar(s)${range}`);
  refreshRadarOptions();
  updateAvailabilityPanel();
  return true;
}

function updateCatalogSourceControl() {
  const select = el("catalogSourceSelect");
  const help = el("catalogSourceHelp");
  if (!select || !help) return;
  const current = state.catalogSourceId;
  select.innerHTML = state.catalogSources
    .map((source) => `<option value="${escapeHtml(source.id)}"${source.configured ? "" : " disabled"}>${escapeHtml(source.label)}</option>`)
    .join("");
  if ([...select.options].some((option) => option.value === current && !option.disabled)) select.value = current;
  const selected = state.catalogSources.find((source) => source.id === select.value);
  help.textContent = selected
    ? `${selected.description}${selected.configured ? "" : " No catalog URL has been configured for this archive."}`
    : "No archive era is available.";
}

async function loadCatalogSources() {
  const response = await api("/api/catalog-sources");
  const data = await response.json();
  state.catalogSources = Array.isArray(data.sources) ? data.sources : [];
  state.catalogSourceId = data.selected || "dual-pol";
  updateCatalogSourceControl();
}

function clearSourceSelectionState() {
  cancelPendingPreviews();
  state.catalogSummary = null;
  state.catalogAvailability = null;
  state.items = [];
  state.panelItemOptionsVersion += 1;
  state.activeItem = null;
  state.radarRecords = [];
  state.panelSelections = [{}, {}, {}, {}];
  state.panelMeta.clear();
  state.ppiFrameCache.clear();
  state.ppiFrameCacheOrder = [];
  el("pulseSelect").innerHTML = '<option value="">Any available scan type</option>';
  el("itemSelect").innerHTML = "";
  el("timeSelect").innerHTML = "";
  el("datasetInput").innerHTML = "";
  panels().forEach((panel) => clearPanel(panel, true));
}

async function selectCatalogSource() {
  const source = el("catalogSourceSelect").value;
  if (!source || source === state.catalogSourceId) return;
  setActivityStage("Switching data era", "clearing catalog metadata...");
  const response = await api("/api/catalog-sources/select", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({source}),
  });
  const data = await response.json();
  state.catalogSourceId = data.selected;
  clearSourceSelectionState();
  updateCatalogSourceControl();
  const ok = await loadStatus();
  if (!ok) return;
  await loadRadars();
  await searchCatalog();
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
  updateComparisonSidebarControlMode();
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
    updateComparisonSidebarControlMode();
    return;
  }
  select.innerHTML = records
    .map((record) => `<option value="${escapeHtml(record.dataset)}">${escapeHtml(elevationOptionLabel(record))}</option>`)
    .join("");
  const values = records.map((record) => String(record.dataset));
  select.value = values.includes(String(preferredValue || "")) ? String(preferredValue) : values[0];
  select.disabled = records.length < 2;
  updateComparisonSidebarControlMode();
}

function availablePanelVariables(item, pulse = selectedPulseForItem(item)) {
  return plotReadyQuantitiesForItem(item, pulse);
}

function availablePanelElevations(item, pulse, time, quantity) {
  return availableElevationRecordsForSelection(item, pulse, time, quantity);
}

function elevationDegForDataset(elevations, dataset) {
  const record = elevations.find((candidate) => String(candidate.dataset) === String(dataset || ""));
  const elevation = Number(record?.elevation_deg);
  return Number.isFinite(elevation) ? elevation : null;
}

function nearestElevationRecord(elevations, targetElevationDeg) {
  const target = Number(targetElevationDeg);
  if (!Number.isFinite(target) || !elevations.length) return null;
  return elevations.reduce((best, record) => {
    const elevation = Number(record.elevation_deg);
    if (!Number.isFinite(elevation)) return best;
    const distance = Math.abs(elevation - target);
    if (!best || distance < best.distance) return {record, distance};
    return best;
  }, null)?.record || null;
}

function resolveElevationSelection(elevations, selection) {
  if (!elevations.length) return {dataset: "", elevationDeg: null, matchedBy: "none"};
  const datasets = elevations.map((record) => String(record.dataset));
  const selectedDataset = String(selection?.dataset || "");
  if (selectedDataset && datasets.includes(selectedDataset)) {
    return {
      dataset: selectedDataset,
      elevationDeg: elevationDegForDataset(elevations, selectedDataset),
      matchedBy: "dataset",
    };
  }
  const matched = nearestElevationRecord(elevations, selection?.elevationDeg);
  if (matched) {
    return {
      dataset: String(matched.dataset),
      elevationDeg: elevationDegForDataset(elevations, matched.dataset),
      matchedBy: "nearest",
    };
  }
  return {
    dataset: datasets[0],
    elevationDeg: elevationDegForDataset(elevations, datasets[0]),
    matchedBy: "first",
  };
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
    elevationDeg: selection.elevationDeg,
    time,
  };
}

function setPanelSelection(index, patch) {
  state.panelSelections[index] = {
    ...(state.panelSelections[index] || {}),
    ...patch,
  };
}

function panelDisplay(index) {
  const current = state.panelDisplays[index] || {};
  return {
    palette: current.palette || el("paletteSelect").value,
    displayMin: current.displayMin ?? optionalInputValue("displayMinInput"),
    displayMax: current.displayMax ?? optionalInputValue("displayMaxInput"),
  };
}

function setPanelDisplay(index, patch) {
  state.panelDisplays[index] = {...(state.panelDisplays[index] || {}), ...patch};
  if (state.panelCount === 4 && state.comparisonLinks.colour) {
    visiblePanelIndices().forEach((other) => {
      if (other !== index) state.panelDisplays[other] = {...(state.panelDisplays[other] || {}), ...patch};
    });
  }
}

function initializePanelDisplays() {
  const display = {
    palette: el("paletteSelect").value,
    displayMin: optionalInputValue("displayMinInput"),
    displayMax: optionalInputValue("displayMaxInput"),
  };
  visiblePanelIndices().forEach((index) => {
    // Freeze the single-panel appearance into each comparison panel. The
    // sidebar controls should never later overwrite independent panel scales.
    if (!Object.keys(state.panelDisplays[index] || {}).length) {
      state.panelDisplays[index] = {...display};
    }
  });
}

function updateDisplayControlMode() {
  const comparisonMode = state.panelCount === 4;
  ["paletteSelect", "displayMinInput", "displayMaxInput"].forEach((id) => {
    const control = el(id);
    if (control) control.disabled = comparisonMode;
  });
  const hint = el("comparisonDisplayHint");
  if (hint) hint.hidden = !comparisonMode;
}

function updateComparisonSidebarControlMode() {
  const comparisonMode = state.panelCount === 4;
  const timeSelect = el("timeSelect");
  const variableSelect = el("quantitySelect");
  const elevationSelect = el("datasetInput");
  if (timeSelect) {
    timeSelect.disabled = timeSelect.options.length === 0 || (comparisonMode && !state.comparisonLinks.time);
  }
  if (variableSelect) {
    variableSelect.disabled = variableSelect.options.length === 0 || (comparisonMode && !state.comparisonLinks.variable);
  }
  if (elevationSelect) {
    elevationSelect.disabled = elevationSelect.options.length < 2 || (comparisonMode && !state.comparisonLinks.elevation);
  }
}

function syncComparisonSidebarFromPanels() {
  if (state.panelCount !== 4) return;
  const selection = panelSelection(0);
  if (state.comparisonLinks.variable) {
    const variableSelect = el("quantitySelect");
    const values = [...variableSelect.options].map((option) => option.value);
    if (values.includes(selection.quantity)) variableSelect.value = selection.quantity;
  }
  if (state.comparisonLinks.elevation) {
    const elevationSelect = el("datasetInput");
    const pulse = selectedPulseForItem(selection.item, selection.quantity);
    const elevations = availablePanelElevations(selection.item, pulse, selection.time, selection.quantity);
    const resolved = resolveElevationSelection(elevations, state.panelSelections[0] || selection);
    const values = [...elevationSelect.options].map((option) => option.value);
    if (values.includes(resolved.dataset)) elevationSelect.value = resolved.dataset;
  }
  updateComparisonSidebarControlMode();
}

function syncLinkedPanelSelection(sourceIndex, patch) {
  if (state.panelCount !== 4) return;
  const sourceSelection = panelSelection(sourceIndex);
  const sourcePulse = selectedPulseForItem(sourceSelection.item, sourceSelection.quantity);
  const sourceElevations = availablePanelElevations(sourceSelection.item, sourcePulse, sourceSelection.time, sourceSelection.quantity);
  const sourceElevationDeg = Object.hasOwn(patch, "elevationDeg")
    ? patch.elevationDeg
    : elevationDegForDataset(sourceElevations, patch.dataset || sourceSelection.dataset);
  const hasLinkedChange = (
    (Object.hasOwn(patch, "quantity") && state.comparisonLinks.variable)
    || (Object.hasOwn(patch, "dataset") && state.comparisonLinks.elevation)
    || (Object.hasOwn(patch, "time") && state.comparisonLinks.time)
  );
  if (!hasLinkedChange) return;
  visiblePanelIndices().forEach((index) => {
    if (index === sourceIndex) return;
    const current = panelSelection(index);
    const linkedPatch = {};
    const quantity = Object.hasOwn(patch, "quantity") && state.comparisonLinks.variable
      ? patch.quantity
      : current.quantity;
    const time = Object.hasOwn(patch, "time") && state.comparisonLinks.time
      ? patch.time
      : current.time;
    if (Object.hasOwn(patch, "quantity") && state.comparisonLinks.variable) linkedPatch.quantity = quantity;
    if (Object.hasOwn(patch, "time") && state.comparisonLinks.time) linkedPatch.time = time;
    if (Object.hasOwn(patch, "dataset") && state.comparisonLinks.elevation) {
      const pulse = selectedPulseForItem(current.item, quantity);
      const elevations = availablePanelElevations(current.item, pulse, time, quantity);
      const matched = nearestElevationRecord(elevations, sourceElevationDeg);
      if (matched) {
        linkedPatch.dataset = String(matched.dataset);
        linkedPatch.elevationDeg = elevationDegForDataset(elevations, matched.dataset);
      } else if (Number.isFinite(Number(sourceElevationDeg))) {
        setStatus(`Could not match linked elevation ${Number(sourceElevationDeg).toFixed(2)} deg for ${itemLabel(current.item)}.`, true);
      }
    }
    if (Object.keys(linkedPatch).length) setPanelSelection(index, linkedPatch);
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
    setPanelSelection(index, {itemKey: itemKey(item), quantity, dataset, elevationDeg: current.elevationDeg, time});
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
  const paletteSelect = panel.querySelector(".panel-palette-select");
  const displayMinInput = panel.querySelector(".panel-display-min-input");
  const displayMaxInput = panel.querySelector(".panel-display-max-input");
  if (!itemSelect || !variableSelect || !timeSelect || !elevationSelect) return;

  const selection = panelSelection(index);
  const itemOptionsVersion = String(state.panelItemOptionsVersion);
  if (panel.dataset.itemOptionsVersion !== itemOptionsVersion) {
    itemSelect.innerHTML = state.items
      .map((item) => `<option value="${escapeHtml(itemKey(item))}">${escapeHtml(itemLabel(item))}</option>`)
      .join("");
    panel.dataset.itemOptionsVersion = itemOptionsVersion;
  }
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
    setPanelSelection(index, {itemKey: selection.itemKey, quantity, time: "", dataset: "", elevationDeg: null});
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
    setPanelSelection(index, {itemKey: selection.itemKey, quantity, time, dataset: "", elevationDeg: null});
    return;
  }
  elevationSelect.innerHTML = elevations
    .map((record) => `<option value="${escapeHtml(record.dataset)}">${escapeHtml(elevationOptionLabel(record))}</option>`)
    .join("");
  const resolvedElevation = resolveElevationSelection(elevations, selection);
  elevationSelect.value = resolvedElevation.dataset;
  elevationSelect.disabled = elevations.length < 2;
  setPanelSelection(index, {
    itemKey: selection.itemKey,
    quantity,
    time,
    dataset: resolvedElevation.dataset,
    elevationDeg: resolvedElevation.elevationDeg,
  });
  if (paletteSelect) {
    paletteSelect.innerHTML = el("paletteSelect").innerHTML;
    paletteSelect.value = panelDisplay(index).palette;
  }
  if (displayMinInput) displayMinInput.value = panelDisplay(index).displayMin;
  if (displayMaxInput) displayMaxInput.value = panelDisplay(index).displayMax;
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

function itemHasFieldMetadata(item) {
  if (!item) return false;
  if (isRawVolumeCatalogEntry(item)) {
    return Array.isArray(item.quantity_records) && item.quantity_records.length > 0;
  }
  return itemHasTimeMetadata(item);
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
  el("timeSelect").disabled = times.length === 0;
  updateTimeStepOutput();
  refreshElevationControls();
  refreshAllPanelControls();
  updateComparisonSidebarControlMode();
  updateMp4ExportControls();
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
  if (!item || itemHasFieldMetadata(item)) return item;
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
  const startRaw = el("startInput").value.trim();
  const endRaw = el("endInput").value.trim();
  const start = parseDateInput(startRaw, "start");
  const end = parseDateInput(endRaw, "end");
  if ((startRaw && !start) || (endRaw && !end) || (start && end && start > end)) {
    const message = "Enter dates as YYYY, YYYY-MM, or YYYY-MM-DD. The start date must be no later than the end date.";
    setStatus(message, true);
    setActivityStage("Catalog search needs valid dates", message, true);
    return;
  }
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
  state.panelItemOptionsVersion += 1;
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
    params.qc_mode = DEFAULT_QC_MODE;
    params.qc_receiver_noise_enabled = true;
    params.qc_receiver_noise_margin_db = 0.25;
    params.qc_receiver_noise_min_bad_moments = 3;
    params.qc_ci_enabled = true;
    params.qc_ci_noise_min_db = 6;
    params.qc_ci_clutter_max_db = 2;
  }
  const backgroundModelPath = el("backgroundModelPathInput").value.trim();
  if (el("noiseFloorInput").checked || backgroundModelPath) {
    params.qc_background_model_enabled = true;
    if (backgroundModelPath) params.qc_background_model_path = backgroundModelPath;
    params.qc_background_persistent_frequency_min = 0.95;
    params.qc_background_min_samples = 40;
    params.qc_background_static_vrad_frequency_min = 0.80;
    params.qc_background_low_sqi_frequency_min = 0.40;
    params.qc_background_dbzh_excess_max_db = 3;
    params.qc_background_evidence_score_threshold = 3;
    params.qc_background_current_vrad_abs_max_ms = 0.5;
    params.qc_background_require_training_diversity = true;
    params.qc_background_min_training_dates = 7;
    params.qc_background_min_training_span_days = 14;
  }
  return params;
}

function appendFilterParams(params, display = null) {
  Object.entries(filterParams()).forEach(([key, value]) => params.set(key, String(value)));
  const displayMin = display?.displayMin ?? optionalInputValue("displayMinInput");
  const displayMax = display?.displayMax ?? optionalInputValue("displayMaxInput");
  if (displayMin !== "") params.set("display_min", String(Number(displayMin)));
  if (displayMax !== "") params.set("display_max", String(Number(displayMax)));
  return params;
}

function fieldParams(dataset = optionalInputValue("datasetInput"), display = null) {
  const params = new URLSearchParams({
    palette: display?.palette || el("paletteSelect").value,
    max_rays: "360",
    max_bins: "360",
  });
  if (dataset) params.set("dataset", dataset);
  appendFilterParams(params, display);
  return params;
}
