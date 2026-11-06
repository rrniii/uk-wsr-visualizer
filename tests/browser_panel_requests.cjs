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

function viewer() {
  const title = {textContent: 'original'};
  const summary = {textContent: ''};
  const panel = {
    dataset: {radar: 'original', date: '20261104', time: '0000'},
    querySelector: selector => selector === '.panel-title' ? title : summary,
  };
  const state = {panelCount: 1, panelMeta: new Map([[0, {id: 'original'}]]), previewRequestSeq: 0};
  const requests = new Map();
  const hydration = new Map();
  const events = [];
  const context = vm.createContext({state, performance, console});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/uk_wsr_visualizer/static/app-render.js'), 'utf8'), context);
  Object.assign(context, {
    panels: () => [panel],
    el: () => ({value: '0000'}),
    hydrateItemDetails: item => hydration.get(item.radar)?.promise ?? Promise.resolve(item),
    refreshRawCacheStatus: () => Promise.resolve(),
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
    updatePanelAfterPpiLoad: () => {},
    setPanelLoading: (_panel, _text, active) => { panel.loading = active; },
    setPanelMessage: (_panel, text) => { panel.message = text; },
    setStatus: text => events.push(['status', text]),
    setActivityStage: text => events.push(['activity', text]),
    pushPerformanceEvent: () => {},
    clearPanel: () => {},
    invalidatePanelRadar: index => state.panelMeta.delete(index),
  });
  const load = name => context.loadPpi(0, {item: {radar: name, date: '20261104'}, quantity: 'DBZH'});
  return {context, panel, state, requests, hydration, events, load};
}

const tick = () => new Promise(resolve => setImmediate(resolve));

test('late failure cannot clear a newer request or restore an old identity', async () => {
  const v = viewer();
  const first = v.load('first'); await tick();
  const second = v.load('second'); await tick();
  v.requests.get('first').reject(new Error('old download failed'));
  await first;
  assert.equal(v.panel.dataset.radar, 'second');
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
