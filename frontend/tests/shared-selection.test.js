import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';
import { personalizationVm } from './helpers/personalization-vm.js';
import { lessonTimesVm } from './helpers/lesson-times-vm.js';

const selectionSource = await readFile(new URL('../src/selection.ts', import.meta.url), 'utf8');
const selectionExports = {};
runInNewContext(ts.transpileModule(selectionSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: selectionExports, AbortController });

const component = await readFile(new URL('../src/App.svelte', import.meta.url), 'utf8');
const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^\s*import .*;\s*$/gm, '');
const source = ts.transpile(`(function(){${script}
  return { chooseSchool, switchToFavorite, saveGrade, saveClassFromSelect, updateClass, saveClass, addFavorite, shareClass, subscribeTimetable,
    setClass: (value) => { selectionState.update({ classroom: value }); },
    state: () => ({ school, grade, classroom, classroomDraft, timetable, classError, schoolEditorOpen, tableLoading, sharedClassState, pendingSharedClass, favorites, shareUrl, subscriptionUrl }) };
})()`, { target: ts.ScriptTarget.ES2022 });
const savedSchool = { id: '1:기존고등학교', name: '기존고등학교', region: '서울' };
const sharedSchool = { id: '2:공유고등학교', name: '공유고등학교', region: '경기' };
const flush = () => new Promise(setImmediate);
const data = (school, records = [{ grade: 1, class: 1 }], stale = false) => ({
  schoolId: school.id, weekStart: '2026-11-09', records, stale,
  fetchedAt: '2026-11-09T01:00:00Z', sourceUpdatedAt: null,
});

function setup({ fallback = savedSchool, shared = sharedSchool, sharedGrade = 1 } = {}) {
  const store = new Map(fallback ? [
    ['opensigan-school', JSON.stringify(fallback)], ['opensigan-grade', '1'], ['opensigan-class', '1'],
  ] : []);
  const requests = [];
  let mount;
  let search;
  const app = runInNewContext(source, {
    ...personalizationVm, ...lessonTimesVm, ...selectionExports,
    onMount(callback) { mount = callback; },
    readSharedClass: () => ({ school: shared, grade: sharedGrade, classroom: 7 }),
    currentKoreaDate: () => '2026-11-09', monday: () => '2026-11-09',
    addDays: () => '2026-11-15', clampWeek: (value) => value,
    window: { location: { hash: '#shared' }, addEventListener() {}, removeEventListener() {} },
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    navigator: { onLine: true },
    localStorage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) },
    searchSchools: (query, signal) => new Promise((resolve) => { search = { resolve, signal }; }),
    getTimetable: (id, week, signal) => new Promise((resolve, reject) => requests.push({ id, week, signal, resolve, reject })),
    searchNeisSchools: () => new Promise(() => {}),
    setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout, AbortController,
  });
  const cleanup = mount();
  return { app, store, requests, search, cleanup, shared };
}

test('같은 학교의 반을 수동 변경하면 늦은 공유 학교 검색도 선택을 덮지 못한다', async () => {
  const { app, requests, search, cleanup } = setup({ shared: savedSchool });
  requests[0].resolve(data(savedSchool, [{ grade: 1, class: 1 }, { grade: 1, class: 2 }]));
  await flush();
  app.setClass(2);
  app.saveClassFromSelect();
  assert.equal(search.signal.aborted, true);
  search.resolve({ schools: [savedSchool], stale: false });
  await flush();
  assert.equal(app.state().classroom, 2);
  assert.equal(app.state().pendingSharedClass, null);
  cleanup();
});

test('공유 학급은 시간표 검증이 끝나기 전까지 선택과 저장에 확정되지 않는다', async () => {
  const { app, requests, search, store, cleanup } = setup();
  requests[0].resolve(data(savedSchool));
  await flush();
  search.resolve({ schools: [sharedSchool], stale: false });
  await flush();
  assert.equal(app.state().pendingSharedClass.classroom, 7);
  assert.equal(app.state().classroom, 1);
  assert.equal(store.get('opensigan-class'), '1');
  requests[1].resolve(data(sharedSchool, [{ grade: 1, class: 7 }]));
  await flush();
  assert.equal(app.state().pendingSharedClass, null);
  assert.equal(app.state().classroom, 7);
  assert.equal(store.get('opensigan-class'), '7');
  cleanup();
});

test('공유 학급 검증 중 같은 학교 즐겨찾기를 선택하면 공유 반을 적용하지 않는다', async () => {
  const { app, search, requests, store, cleanup } = setup({ fallback: null });
  search.resolve({ schools: [sharedSchool], stale: false });
  await flush();
  app.addFavorite();
  await app.shareClass();
  app.subscribeTimetable();
  assert.equal(app.state().favorites.length, 0);
  assert.equal(app.state().shareUrl, '');
  assert.equal(app.state().subscriptionUrl, '');
  app.switchToFavorite({ school: sharedSchool, grade: 1, classroom: 2 });
  requests[0].resolve(data(sharedSchool, [{ grade: 1, class: 2 }, { grade: 1, class: 7 }]));
  await flush();
  assert.equal(app.state().classroom, 2);
  assert.equal(app.state().classroomDraft, '2');
  assert.equal(store.get('opensigan-class'), '2');
  cleanup();
});

for (const outcome of ['network', 'stale', 'empty', 'missing']) {
  test(`공유 시간표 ${outcome} 이후 이전 선택과 오프라인 캐시를 보존한다`, async () => {
    const { app, search, requests, store, cleanup } = setup();
    requests[0].resolve(data(savedSchool));
    await flush();
    search.resolve({ schools: [sharedSchool], stale: false });
    await flush();
    if (outcome === 'network') requests[1].reject(new Error('network failed'));
    else requests[1].resolve(data(sharedSchool, outcome === 'empty' ? [] : [{ grade: 1, class: outcome === 'missing' ? 1 : 7 }], outcome === 'stale'));
    await flush();
    assert.equal(app.state().school.id, savedSchool.id);
    assert.equal(app.state().timetable.schoolId, savedSchool.id);
    assert.equal(app.state().classroom, 1);
    assert.equal(app.state().pendingSharedClass, null);
    assert.equal(app.state().tableLoading, false);
    assert.equal(JSON.parse(store.get('opensigan-school')).id, savedSchool.id);
    assert.equal(JSON.parse(store.get('opensigan-offline-timetable')).schoolId, savedSchool.id);
    cleanup();
  });
}

test('공유 학교에 없는 학급은 선택기를 열고 저장하지 않으며 직접 고칠 수 있다', async () => {
  const { app, search, requests, store, cleanup } = setup({ fallback: null });
  search.resolve({ schools: [sharedSchool], stale: false });
  await flush();
  requests[0].resolve(data(sharedSchool));
  await flush();
  assert.equal(app.state().classError, true);
  assert.equal(app.state().schoolEditorOpen, true);
  assert.equal(store.has('opensigan-school'), false);
  app.setClass(1);
  app.saveClassFromSelect();
  assert.equal(app.state().classError, false);
  assert.equal(app.state().sharedClassState, '');
  assert.equal(JSON.parse(store.get('opensigan-school')).id, sharedSchool.id);
  cleanup();
});

test('고교의 4학년 공유는 1학년으로 저장되지 않는다', async () => {
  const { app, search, requests, store, cleanup } = setup({ fallback: null, sharedGrade: 4 });
  search.resolve({ schools: [sharedSchool], stale: false });
  await flush();
  requests[0].resolve(data(sharedSchool, [{ grade: 4, class: 7 }, { grade: 1, class: 7 }]));
  await flush();
  assert.equal(app.state().classError, true);
  assert.match(app.state().sharedClassState, /4학년 7반/);
  assert.equal(store.has('opensigan-school'), false);
  cleanup();
});

for (const mismatch of [{ id: '99:공유고등학교' }, { name: '다른학교' }, { region: '서울' }]) {
  test(`공유 학교의 ${Object.keys(mismatch)[0]} 불일치는 저장된 학교를 바꾸지 않는다`, async () => {
    const { app, requests, search, store, cleanup } = setup();
    requests[0].resolve(data(savedSchool));
    await flush();
    search.resolve({ schools: [{ ...sharedSchool, ...mismatch }], stale: false });
    await flush();
    assert.equal(app.state().school.id, savedSchool.id);
    assert.equal(app.state().timetable.schoolId, savedSchool.id);
    assert.equal(JSON.parse(store.get('opensigan-school')).id, savedSchool.id);
    assert.equal(requests.length, 1);
    cleanup();
  });
}
