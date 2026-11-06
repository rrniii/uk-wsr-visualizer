// Run the real panel loader with controllable network completions.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function viewer({actualHydration = false, panelCount = 1} = {}) {
  const panelList = Array.from({length: panelCount}, (_, index) => {
    const title = {textContent: `original ${index}`};
    const summary = {textContent: `original summary ${index}`};
    return {
      dataset: {radar: 'original', date: '20261104', time: '0000', pulse: 'lp', quantity: 'DBZH', fieldDataset: '1'},
      querySelector: selector => selector === '.panel-title' ? title : summary,
    };
  });
  const panel = panelList[0];
  const state = {
    panelCount, panelMeta: new Map(panelList.map((_, index) => [index, {id: 'original'}])),
    previewRequestSeq: 0, previewTimers: new Map(), searchRequestSeq: 0,
    catalogSourceId: 'dual-pol', items: [], activeItem: null, hydratingItems: new Map(),
    comparisonLinks: {time: false}, panelSelections: [{}, {}, {}, {}], rawCacheByItem: new Map(),
  };
  const requests = new Map();
  const hydration = new Map();
  const apiRequests = new Map();
  const apiCalls = [];
  const events = [];
  const controls = {variables: '', time: ''};
  const nodes = {
    itemSelect: {options: []}, timeSelect: {value: '0000'}, quantitySelect: {value: 'DBZH'},
    pulseSelect: {value: ''}, datasetInput: {value: ''},
  };
  const context = vm.createContext({state, performance, console, setTimeout, clearTimeout, DEFAULT_VARIABLE: 'DBZH'});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/uk_wsr_visualizer/static/app-catalog.js'), 'utf8'), context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/uk_wsr_visualizer/static/app-render.js'), 'utf8'), context);
  Object.assign(context, {
    panels: () => panelList,
    el: id => nodes[id],
    api: url => {
      const key = `${state.catalogSourceId}:${url}`;
      const task = deferred(); apiRequests.set(key, task); apiCalls.push(key); return task.promise;
    },
    uniqueSorted: values => [...new Set(values)].sort(),
    refreshFacetControls: () => events.push(['facets']),
    refreshVariableControls: item => { controls.variables = item.radar; events.push(['variables', item.radar]); },
    refreshTimeControls: () => { controls.time = state.activeItem?.radar; events.push(['times']); },
    refreshElevationControls: () => events.push(['elevations']),
    refreshPanelControls: index => events.push(['panel-controls', index]),
    setPanelSelection: (index, values) => Object.assign(state.panelSelections[index], values),
    panelDisplay: () => ({}),
    selectedQuantity: () => 'DBZH',
    selectedPulseForItem: () => 'lp',
    availableTimesForSelection: () => ['0000'],
    availablePanelElevations: () => [],
    resolveElevationSelection: () => ({dataset: '1'}),
    shouldPreservePanelView: () => true,
    itemLabel: item => item.radar,
    ppiFrameKey: item => item.radar,
    ppiUrl: item => item.radar,
    cachedPpiFrame: () => null,
    fetchPpiFrame: key => {
      const task = deferred(); requests.set(key, task); return task.promise;
    },
    renderPanel: (_panel, frame) => events.push(['render', frame.id]),
    updatePanelAfterPpiLoad: (_index, target, item) => {
      target.querySelector('.panel-title').textContent = item.radar;
      target.querySelector('.panel-summary').textContent = `${item.radar} summary`;
      target.message = '';
    },
    setPanelLoading: (target, _text, active) => { target.loading = active; },
    setPanelMessage: (target, text) => { target.message = text; events.push(['message', panelList.indexOf(target), text]); },
    setStatus: text => events.push(['status', text]),
    setActivityStage: text => events.push(['activity', text]),
    pushPerformanceEvent: () => {},
    clearPanel: target => state.panelMeta.delete(panelList.indexOf(target)),
    invalidatePanelRadar: index => state.panelMeta.delete(index),
  });
  if (!actualHydration) {
    context.hydrateItemDetails = item => hydration.get(item.radar)?.promise ?? Promise.resolve(item);
  }
  const readyItem = name => ({radar: name, date: '20261104', pulses: ['lp'], times: ['0000'], quantities: ['DBZH']});
  function addItem(name, ready = !actualHydration) {
    let item = state.items.find(candidate => candidate.radar === name);
    if (!item) {
      item = ready ? readyItem(name) : {radar: name, date: '20261104'};
      state.items.push(item); nodes.itemSelect.options.push({textContent: name});
    }
    return item;
  }
  const load = (name, index = 0) => {
    const item = addItem(name);
    if (index === 0) state.activeItem = item;
    return context.loadPpi(index, {item, quantity: 'DBZH'});
  };
  const hydrationRequest = (name, source = state.catalogSourceId) => apiRequests.get(`${source}:/api/item/${name}/20261104/hydrate`);
  const finishHydration = (name, source) => hydrationRequest(name, source).resolve({json: async () => readyItem(name)});
  return {context, panel, panelList, state, requests, hydration, apiRequests, apiCalls, events, controls, nodes, load, addItem, readyItem, hydrationRequest, finishHydration};
}

const tick = () => new Promise(resolve => setImmediate(resolve));

test('late failure cannot clear a newer request or restore an old identity', async () => {
  const v = viewer();
  const first = v.load('first'); await tick();
  const second = v.load('second'); await tick();
  v.requests.get('first').reject(new Error('old download failed'));
  await first;
  assert.equal(v.panel.dataset.radar, 'original');
  assert.equal(v.panel.loading, true);
  assert.ok(!v.events.some(event => String(event[1]).includes('old download failed')));
  v.requests.get('second').resolve({id: 'second'}); await second;
  assert.equal(v.state.panelMeta.get(0).id, 'second');
  assert.equal(v.panel.loading, false);
});

test('late success cannot replace the new frame', async () => {
  const v = viewer();
  const first = v.load('first'); await tick();
  const second = v.load('second'); await tick();
  v.requests.get('second').resolve({id: 'second'}); await second;
  v.requests.get('first').resolve({id: 'first'}); await first;
  assert.equal(v.state.panelMeta.get(0).id, 'second');
  assert.equal(v.panel.dataset.radar, 'second');
  assert.deepEqual(v.events.filter(event => event[0] === 'render'), [['render', 'second']]);
});

test('older hydration does not begin a frame request after a newer selection', async () => {
  const v = viewer();
  const slow = deferred(); v.hydration.set('first', slow);
  const first = v.load('first');
  const second = v.load('second'); await tick();
  v.requests.get('second').resolve({id: 'second'}); await second;
  slow.resolve({radar: 'first', date: '20261104'}); await first;
  assert.equal(v.requests.has('first'), false);
  assert.equal(v.panel.dataset.radar, 'second');
});

test('obsolete hydration failures are ignored but current failures remain actionable', async () => {
  const v = viewer();
  const slow = deferred(); v.hydration.set('first', slow);
  const first = v.load('first');
  const second = v.load('second'); await tick();
  slow.reject(new Error('old catalogue failed')); await first;
  v.requests.get('second').reject(new Error('current download failed'));
  await assert.rejects(second, /current download failed/);
  assert.match(v.panel.message, /current download failed/);
  assert.equal(v.state.panelMeta.get(0).id, 'original');
  assert.equal(v.panel.loading, false);
});

test('clearing the selection invalidates requests already in flight', async () => {
  const v = viewer();
  const first = v.load('first'); await tick();
  v.context.panelSelection = () => ({item: null});
  v.state.panelCount = 4;
  await v.context.loadPpi(0);
  v.requests.get('first').resolve({id: 'first'}); await first;
  assert.equal(v.state.panelMeta.has(0), false);
});

test('a failed replacement restores the rendered frame, not an earlier pending selection', async () => {
  const v = viewer();
  const first = v.load('first'); await tick();
  const second = v.load('second'); await tick();
  assert.ok(v.requests.has('first'));
  v.requests.get('second').reject(new Error('replacement failed'));
  await assert.rejects(second, /replacement failed/);
  assert.equal(v.state.panelMeta.get(0).id, 'original');
  assert.equal(v.panel.dataset.radar, 'original');
  assert.equal(v.panel.querySelector('.panel-title').textContent, 'original 0');
  assert.equal(v.panel.querySelector('.panel-summary').textContent, 'original summary 0');
  v.requests.get('first').resolve({id: 'first'}); await first;
  assert.equal(v.panel.dataset.radar, 'original');
});

test('actual late hydration caches metadata without changing the newer controls or frame', async () => {
  const v = viewer({actualHydration: true});
  const first = v.load('first');
  const second = v.load('second');
  v.finishHydration('second'); await tick();
  v.requests.get('second').resolve({id: 'second'}); await second;
  const eventsBefore = [...v.events];
  v.finishHydration('first'); await first;
  assert.deepEqual(v.events, eventsBefore);
  assert.equal(v.controls.variables, 'second');
  assert.equal(v.state.activeItem.radar, 'second');
  assert.equal(v.panel.dataset.radar, 'second');
  assert.equal(v.requests.has('first'), false);
  assert.equal(v.context.itemHasFieldMetadata(v.state.items[0]), true);
  const reused = await v.context.hydrateItemDetails(v.state.items[0]);
  assert.equal(reused.radar, 'first');
  assert.equal(v.apiCalls.length, 2);
});

test('actual obsolete hydration failure is silent, while current hydration failure keeps the visible frame', async () => {
  const v = viewer({actualHydration: true, panelCount: 4});
  const first = v.load('first');
  const second = v.load('second');
  const eventsBefore = [...v.events];
  v.hydrationRequest('first').reject(new Error('obsolete hydration failed')); await first;
  assert.deepEqual(v.events, eventsBefore);
  v.hydrationRequest('second').reject(new Error('current hydration failed'));
  await assert.rejects(second, /current hydration failed/);
  assert.match(v.panel.message, /current hydration failed/);
  assert.equal(v.panel.dataset.radar, 'original');
  assert.equal(v.state.panelMeta.get(0).id, 'original');
  assert.ok(v.panelList.slice(1).every(panel => panel.message === undefined));
});

test('a current consumer sharing an obsolete hydration still commits its metadata', async () => {
  const v = viewer({actualHydration: true});
  const first = v.load('same');
  const second = v.load('same');
  assert.equal(v.apiCalls.length, 1);
  v.finishHydration('same'); await tick();
  await first;
  assert.equal(v.controls.variables, 'same');
  assert.equal(v.events.filter(event => event[0] === 'variables').length, 1);
  v.requests.get('same').resolve({id: 'same'}); await second;
  assert.equal(v.panel.dataset.radar, 'same');
  assert.equal(v.state.hydratingItems.size, 0);
});

test('hydrating a comparison panel does not rewrite another panel or the global variable selection', async () => {
  const v = viewer({actualHydration: true, panelCount: 4});
  v.state.activeItem = v.addItem('active', true);
  v.controls.variables = 'active';
  v.panel.message = 'active panel remains visible';
  const other = v.load('other', 1);
  assert.equal(v.panel.message, 'active panel remains visible');
  v.finishHydration('other'); await tick();
  v.requests.get('other').resolve({id: 'other'}); await other;
  assert.equal(v.controls.variables, 'active');
  assert.equal(v.panel.message, 'active panel remains visible');
  assert.equal(v.panelList[1].dataset.radar, 'other');
});

test('hydration from a different source cannot replace current metadata or share its request', async () => {
  const v = viewer({actualHydration: true});
  const first = v.load('same');
  v.state.catalogSourceId = 'pre-dual-pol';
  v.state.items = [];
  const second = v.load('same');
  assert.equal(v.apiCalls.length, 2);
  const eventsBefore = [...v.events];
  v.finishHydration('same', 'dual-pol'); await first;
  assert.deepEqual(v.events, eventsBefore);
  assert.equal(v.context.itemHasFieldMetadata(v.state.activeItem), false);
  v.finishHydration('same', 'pre-dual-pol'); await tick();
  v.requests.get('same').resolve({id: 'new-source'}); await second;
  assert.equal(v.state.panelMeta.get(0).id, 'new-source');
});

test('active-item preparation cannot publish controls after a newer active item is ready', async () => {
  const v = viewer({actualHydration: true});
  v.state.activeItem = v.addItem('first');
  const first = v.context.prepareActiveItemForDisplay();
  v.state.activeItem = v.addItem('second');
  const second = v.context.prepareActiveItemForDisplay();
  v.finishHydration('second'); await second;
  const eventsBefore = [...v.events];
  v.finishHydration('first');
  assert.equal(await first, null);
  assert.deepEqual(v.events, eventsBefore);
  assert.equal(v.controls.variables, 'second');
});

test('panel item selection cannot reinstate its old item after later hydration finishes', async () => {
  const v = viewer({actualHydration: true, panelCount: 4});
  const firstItem = v.addItem('first');
  const secondItem = v.addItem('second');
  v.context.schedulePreview = index => v.events.push(['schedule', index]);
  const first = v.context.selectPanelItem(0, v.context.itemKey(firstItem));
  const second = v.context.selectPanelItem(0, v.context.itemKey(secondItem));
  v.finishHydration('second'); await second;
  const eventsBefore = [...v.events];
  v.finishHydration('first'); await first;
  assert.deepEqual(v.events, eventsBefore);
  assert.equal(v.state.activeItem.radar, 'second');
  assert.equal(v.state.panelSelections[0].itemKey, 'second:20261104');
  assert.equal(v.context.itemHasFieldMetadata(v.state.activeItem), true);
});

test('late raw-cache badges retain reusable data without replacing newer UI status', async () => {
  const v = viewer({actualHydration: true});
  const item = {...v.readyItem('first'), source_type: 'raw_volume_day', raw_volumes: [{pulse: 'lp', time: '0000'}]};
  v.state.activeItem = item;
  const refresh = v.context.refreshRawCacheStatus(item);
  v.state.activeItem = v.addItem('second', true);
  const eventsBefore = [...v.events];
  v.apiRequests.get('dual-pol:/api/raw-cache/day/first/20261104').resolve({json: async () => ({files: [{pulse: 'lp', time: '0000', cached: true}]})});
  await refresh;
  assert.deepEqual(v.events, eventsBefore);
  assert.equal(v.state.rawCacheByItem.get('first:20261104').has('lp:0000'), true);
});

test('scheduling a replacement immediately invalidates an old request before its timer fires', async () => {
  const v = viewer();
  const first = v.load('first'); await tick();
  v.context.schedulePreview(0, 60_000);
  v.requests.get('first').resolve({id: 'first'}); await first;
  assert.equal(v.state.panelMeta.get(0).id, 'original');
  v.context.cancelPendingPreviews();
});
