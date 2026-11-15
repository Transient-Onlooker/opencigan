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
