import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/timetable-cache.ts', import.meta.url), 'utf8');
const exports = {};
runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports, AbortController });

test('week cache isolates instances, expires at the deadline and evicts oldest writes', () => {
  const cache = exports.createTimetableCache();
  const other = exports.createTimetableCache();
  for (let i = 1; i <= 4; i++) cache.put(`school\0week${i}`, { id: i }, 100);
  assert.equal(cache.get('school\0week1', 99).data.id, 1);
  assert.equal(cache.get('school\0week1', 100), undefined);
  cache.put('school\0week1', { id: 10 }, 200);
  cache.put('other\0week1', { id: 5 }, 200);
  assert.equal(cache.get('school\0week2', 99), undefined);
  assert.equal(cache.get('school\0week1', 101).data.id, 10);
  assert.equal(other.get('school\0week1', 1), undefined);
});

test('cache reads do not change eviction order and replacement moves a week to the end', () => {
  const cache = exports.createTimetableCache(2);
  cache.put('a', { id: 1 }, 100);
  cache.put('b', { id: 2 }, 100);
  cache.get('a', 1);
  cache.put('c', { id: 3 }, 100);
  assert.equal(cache.get('a', 1), undefined);
  cache.put('b', { id: 20 }, 100);
  cache.put('d', { id: 4 }, 100);
  assert.equal(cache.get('c', 1), undefined);
  assert.equal(cache.get('b', 1).data.id, 20);
});

test('a new timetable request cancels only the previous request in the same session', () => {
  const session = exports.createTimetableSession();
  const other = exports.createTimetableSession();
  const first = session.begin();
  const independent = other.begin();
  const next = session.begin();
  assert.equal(first.signal.aborted, true);
  assert.equal(next.signal.aborted, false);
  assert.equal(independent.signal.aborted, false);
  session.cancel();
  assert.equal(next.signal.aborted, true);
  assert.equal(independent.signal.aborted, false);
});

test('timetable session publishes independent state snapshots', () => {
  let first;
  let second;
  const session = exports.createTimetableSession((state) => { first = state; });
  const other = exports.createTimetableSession((state) => { second = state; });
  session.update({ loading: true, refreshAt: 100 });
  first.loading = false;
  session.update({ error: 'offline' });
  other.update({ fromDevice: true });
  assert.equal(first.loading, true);
  assert.equal(first.refreshAt, 100);
  assert.equal(first.error, 'offline');
  assert.equal(second.loading, false);
  assert.equal(second.fromDevice, true);
});

test('timetable session rejects mismatched responses and ignores cancelled requests', async () => {
  const session = exports.createTimetableSession();
  let resolve;
  let accepted = 0;
  const current = () => ({ schoolId: 'a', week: '2026-11-09' });
  const load = () => new Promise((done) => { resolve = done; });
  const first = session.fetch('a', '2026-11-09', current, load, () => { accepted++; });
  session.cancel();
  resolve({ schoolId: 'a', weekStart: '2026-11-09' });
  await first.result;
  assert.equal(accepted, 0);
  const second = session.fetch('a', '2026-11-09', current, load, () => { accepted++; });
  resolve({ schoolId: 'b', weekStart: '2026-11-09' });
  await assert.rejects(second.result, /다른 시간표/);
  const third = session.fetch('a', '2026-11-09', current, load, () => { accepted++; });
  resolve({ schoolId: 'a', weekStart: '2026-11-09' });
  await third.result;
  assert.equal(accepted, 1);
});

test('offline data is restored only for the matching school and week and stale data is not saved', () => {
  const session = exports.createTimetableSession();
  const values = new Map();
  const storage = () => ({ getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value) });
  const fresh = { schoolId: 'a', weekStart: '2026-11-09', records: [], stale: false };
  session.saveFresh('a-week', fresh, 100, storage);
  assert.equal(session.restoreOffline('a', '2026-11-09', storage).schoolId, 'a');
  assert.equal(session.restoreOffline('b', '2026-11-09', storage), null);
  assert.equal(session.restoreOffline('a', '2026-11-16', storage), null);
  session.saveFresh('b-week', { ...fresh, schoolId: 'b', stale: true }, 100, storage);
  assert.equal(session.restoreOffline('a', '2026-11-09', storage).schoolId, 'a');
  assert.equal(session.cache.get('b-week', 1), undefined);
  const unavailable = () => { throw new Error('storage unavailable'); };
  session.saveFresh('memory', fresh, 100, unavailable);
  assert.equal(session.cache.get('memory', 1).data.schoolId, 'a');
  assert.equal(session.restoreOffline('a', '2026-11-09', unavailable), null);
  values.set('opensigan-offline-timetable', '{broken');
  assert.equal(session.restoreOffline('a', '2026-11-09', storage), null);
});

test('week reuse avoids a request until expiry while manual refresh requests fresh data', async () => {
  let state;
  let now = 10;
  let calls = 0;
  const session = exports.createTimetableSession((value) => { state = value; });
  const data = { schoolId: 'a', weekStart: '2026-11-09', records: [], stale: false };
  const storage = () => ({ setItem() {}, getItem: () => null });
  const options = {
    schoolId: 'a', week: '2026-11-09', preserve: false, reuseCachedWeek: true, validateClass: false,
    refreshInterval: 100, now: () => now, storage, online: () => true,
    current: () => ({ schoolId: 'a', week: '2026-11-09' }),
    fetch: async () => { calls++; return data; }, validate() {}, classError: () => false,
    errorText: String, onSuccess() {}, onFailure() {},
  };
  const flush = () => new Promise(setImmediate);
  session.load(options);
  await flush();
  assert.equal(calls, 1);
  assert.equal(state.data, data);
  session.load(options);
  assert.equal(calls, 1);
  assert.equal(state.refreshAt, 110);
  now = 109;
  session.load({ ...options, preserve: true, reuseCachedWeek: false });
  await flush();
  assert.equal(calls, 2);
  now = 209;
  session.load(options);
  await flush();
  assert.equal(calls, 3);
});

test('server failure restores only the matching saved timetable and recovery replaces it', async () => {
  let state;
  let selected = { schoolId: 'a', week: '2026-11-09' };
  const session = exports.createTimetableSession((value) => { state = value; });
  const saved = { schoolId: 'a', weekStart: selected.week, records: [{ subject: 'saved' }], fetchedAt: '2026-11-09T01:00:00Z', stale: false };
  const fresh = { ...saved, records: [{ subject: 'fresh' }] };
  const storage = () => ({ getItem: () => JSON.stringify(saved), setItem() {} });
  let fail = true;
  const options = {
    schoolId: 'a', week: selected.week, preserve: false, reuseCachedWeek: false, validateClass: false,
    refreshInterval: 100, now: () => 10, storage, online: () => true, current: () => selected,
    fetch: async () => { if (fail) throw new Error('server unavailable'); return fresh; },
    validate() {}, classError: () => false, errorText: (error) => error.message, onSuccess() {}, onFailure() {},
  };
  const flush = () => new Promise(setImmediate);
  session.load(options);
  await flush();
  assert.equal(state.data.records[0].subject, 'saved');
  assert.equal(state.fromDevice, true);
  assert.equal(state.error, 'server unavailable');
  fail = false;
  session.load({ ...options, preserve: true });
  await flush();
  assert.equal(state.data.records[0].subject, 'fresh');
  assert.equal(state.fromDevice, false);
  assert.equal(state.error, '');
  fail = true;
  selected = { schoolId: 'a', week: '2026-11-16' };
  session.load({ ...options, week: selected.week, preserve: true });
  await flush();
  assert.equal(state.data, null);
  assert.equal(state.error, 'server unavailable');
});

test('failed refresh marks the retained timetable as stale', async () => {
  let state;
  const session = exports.createTimetableSession((value) => { state = value; });
  const data = { schoolId: 'a', weekStart: '2026-11-09', records: [], stale: false };
  session.update({ data });
  session.load({
    schoolId: 'a', week: data.weekStart, preserve: true, reuseCachedWeek: false, validateClass: false,
    refreshInterval: 100, now: () => 10, storage: () => ({ getItem: () => null }), online: () => true,
    current: () => ({ schoolId: 'a', week: data.weekStart }), fetch: async () => { throw new Error('failed'); },
    validate() {}, classError: () => false, errorText: (error) => error.message, onSuccess() {}, onFailure() {},
  });
  await new Promise(setImmediate);
  assert.equal(state.data.stale, true);
  assert.equal(state.error, 'failed');
  assert.equal(data.stale, false);
});
