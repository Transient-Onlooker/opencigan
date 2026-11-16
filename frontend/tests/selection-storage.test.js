import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/selection.ts', import.meta.url), 'utf8');
const exports = {};
runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports, AbortController });

test('selection owners publish independent snapshots without losing unrelated selection fields', () => {
  const initial = { school: null, grade: 1, classroom: 1, week: '2026-11-09' };
  let first;
  let second;
  const owner = exports.createSelectionState(initial, (state) => { first = state; });
  const other = exports.createSelectionState(initial, (state) => { second = state; });
  owner.update({ grade: 2, classroom: 3 });
  first.grade = 6;
  owner.update({ week: '2026-11-16' });
  other.update({ classroom: 4 });
  assert.equal(first.grade, 2);
  assert.equal(first.classroom, 3);
  assert.equal(first.week, '2026-11-16');
  assert.equal(second.grade, 1);
  assert.equal(second.classroom, 4);
});

test('school preparation and timetable reconciliation use the same selection owner', () => {
  const school = { id: 'old', name: '초등학교' };
  let current;
  const owner = exports.createSelectionState({ school, grade: 5, classroom: 8, week: '2026-11-09' }, (state) => { current = state; });
  assert.equal(owner.prepareSchool({ id: 'new', name: '고등학교' }, true), false);
  assert.equal(current.grade, 1);
  assert.equal(current.classroom, 8);
  owner.update({ school: { id: 'new', name: '고등학교' } });
  assert.equal(owner.reconcile([{ grade: 2, class: 3 }], 3), true);
  assert.equal(current.grade, 2);
  assert.equal(current.classroom, 3);
  assert.equal(current.week, '2026-11-09');
  assert.equal(owner.reconcile([{ grade: 2, class: 3 }], 3), false);
  assert.equal(owner.prepareSchool({ id: 'another', name: '초등학교' }, false), true);
  assert.equal(current.grade, 1);
  assert.equal(current.classroom, 1);
});

test('class draft validation and commit preserve the selected class until a valid value is committed', () => {
  let current;
  const owner = exports.createSelectionState({ school: null, grade: 1, classroom: 2, week: '2026-11-09' }, (state) => { current = state; });
  for (const value of [NaN, 0, 1.5, 100, 7]) assert.equal(owner.validClass(value, [2, 3]), false);
  assert.equal(current, undefined);
  assert.equal(owner.validClass(7, []), true);
  assert.equal(owner.validClass(3, [2, 3]), true);
  owner.commitClass(3);
  assert.equal(current.classroom, 3);
  assert.equal(current.grade, 1);
  assert.equal(current.week, '2026-11-09');
});

test('selection persistence preserves keys, values and write order', () => {
  const writes = [];
  const storage = { setItem: (key, value) => writes.push([key, value]) };
  const school = { id: '2:학교', name: '학교', region: '서울' };
  exports.saveSelection(storage, { school, grade: 2, classroom: 3 });
  exports.saveSelection(storage, { grade: 3, classroom: 4 });
  exports.saveSelection(storage, { classroom: 5 });
  assert.deepEqual(writes, [
    ['opensigan-school', JSON.stringify(school)], ['opensigan-grade', '2'], ['opensigan-class', '3'],
    ['opensigan-grade', '3'], ['opensigan-class', '4'], ['opensigan-class', '5'],
  ]);
});

test('selection persistence tolerates blocked storage and stops subsequent writes', () => {
  const attempted = [];
  const storage = { setItem: (key) => { attempted.push(key); throw new Error('blocked'); } };
  assert.doesNotThrow(() => exports.saveSelection(storage, { grade: 1, classroom: 2 }));
  assert.deepEqual(attempted, ['opensigan-grade']);
  assert.doesNotThrow(() => exports.saveSelection(storage, { classroom: 2 }));
  const partial = [];
  const failsOnGrade = { setItem: (key) => { partial.push(key); if (key === 'opensigan-grade') throw new Error('blocked'); } };
  exports.saveSelection(failsOnGrade, { school: { id: 'school' }, grade: 1, classroom: 2 });
  assert.deepEqual(partial, ['opensigan-school', 'opensigan-grade']);
});

test('selection restoration preserves read order and applies valid values before a later failure', () => {
  const reads = [];
  const changes = [];
  const values = new Map([['opensigan-grade', '2'], ['opensigan-class', '7'], ['opensigan-school', '{bad']]);
  const storage = { getItem: (key) => { reads.push(key); return values.get(key) ?? null; } };
  assert.throws(() => exports.readSelection(storage, (change) => changes.push({ ...change })));
  assert.deepEqual(reads, ['opensigan-grade', 'opensigan-class', 'opensigan-school']);
  assert.deepEqual(changes, [{ grade: 2 }, { classroom: 7 }]);
  values.set('opensigan-school', '{"id":"2:school","name":"school","region":"r"}');
  assert.equal(exports.readSelection(storage, () => {}).id, '2:school');
});

test('shared classroom requires fresh matching data and valid school grade', () => {
  const data = { stale: false, records: [{ grade: 1, class: '3' }, { grade: 4, class: 3 }] };
  assert.equal(exports.validateSharedClass(data, false, 3, 1, 3), 'valid');
  assert.equal(exports.validateSharedClass(data, false, 3, 4, 3), 'missing');
  assert.equal(exports.validateSharedClass(data, false, 6, 1, 4), 'missing');
  assert.equal(exports.validateSharedClass({ ...data, stale: true }, false, 3, 1, 3), 'unavailable');
  assert.equal(exports.validateSharedClass(data, true, 3, 1, 3), 'unavailable');
  assert.equal(exports.validateSharedClass({ ...data, records: [] }, false, 3, 1, 3), 'unavailable');
  assert.equal(exports.validateSharedClass(null, false, 3, 1, 3), 'unavailable');
});

test('shared selection commits only verified classes and otherwise returns the original fallback', () => {
  const fallback = { school: { id: 'previous' }, grade: 2, classroom: 3 };
  const pending = { schoolId: 'next', grade: 1, classroom: 7, fallback };
  const data = { stale: false, records: [{ grade: 1, class: 7 }] };
  const committed = exports.resolveSharedClass(pending, data, false, 3);
  assert.equal(committed.status, 'committed');
  assert.equal(committed.grade, 1);
  assert.equal(committed.classroom, 7);
  for (const [table, fromDevice, reason] of [[data, true, 'unavailable'], [{ ...data, records: [{ grade: 1, class: 1 }] }, false, 'missing']]) {
    const result = exports.resolveSharedClass(pending, table, fromDevice, 3);
    assert.equal(result.status, 'rolled-back');
    assert.equal(result.reason, reason);
    assert.equal(result.fallback, fallback);
  }
});

test('selection owner commits verified shared classes and restores the previous class on rollback', () => {
  const school = { id: 'shared' };
  const fallback = { school: { id: 'old' }, grade: 2, classroom: 3 };
  const pending = { schoolId: school.id, grade: 1, classroom: 7, fallback };
  let current;
  const owner = exports.createSelectionState({ school, grade: 1, classroom: 7, week: '2026-11-09' }, (state) => { current = state; });
  assert.equal(owner.resolveShared(pending, { stale: false, records: [{ grade: 1, class: 7 }] }, false, 3).status, 'committed');
  assert.equal(current.classroom, 7);
  assert.equal(owner.resolveShared(pending, { stale: false, records: [{ grade: 1, class: 1 }] }, false, 3).status, 'rolled-back');
  assert.equal(current.grade, 2);
  assert.equal(current.classroom, 3);
  assert.equal(current.school, school);
  assert.equal(current.week, '2026-11-09');
});

test('shared selection session cancels obsolete checks and publishes pending and cleared states', () => {
  let state;
  const session = exports.createSharedSelectionSession((next) => { state = next; });
  const first = session.begin();
  const second = session.begin();
  assert.equal(first.aborted, true);
  session.finish(first);
  assert.equal(state.checking, true);
  const pending = { schoolId: 'next', grade: 1, classroom: 7, fallback: { school: null, grade: 1, classroom: 1 } };
  session.setPending(pending);
  session.finish(second);
  assert.equal(state.checking, false);
  assert.equal(state.pending, pending);
  assert.equal(session.consume(), pending);
  assert.equal(state.pending, null);
  const third = session.begin();
  session.cancel();
  assert.equal(third.aborted, true);
  assert.equal(state.checking, false);
  assert.equal(state.pending, null);
});

test('a newer shared school verification wins when an aborted search resolves late', async () => {
  let latest;
  const session = exports.createSharedSelectionSession((state) => { latest = state; });
  const fallback = { school: { id: 'old' }, grade: 1, classroom: 1 };
  const firstSchool = { id: 'first', name: '첫 학교', region: '서울' };
  const secondSchool = { id: 'second', name: '다음 학교', region: '서울' };
  let release;
  const delayed = new Promise((resolve) => { release = resolve; });
  const applied = [];
  const failures = [];
  const first = session.verifySchool({ school: firstSchool, grade: 1, classroom: 2 }, fallback, () => 'old', () => delayed, (value) => applied.push(value.id), () => failures.push('first'));
  const second = session.verifySchool({ school: secondSchool, grade: 2, classroom: 3 }, fallback, () => 'old', async () => ({ schools: [secondSchool], stale: false }), (value) => applied.push(value.id), () => failures.push('second'));
  await second;
  release({ schools: [firstSchool], stale: false });
  await first;
  assert.deepEqual(applied, ['second']);
  assert.deepEqual(failures, []);
  assert.equal(latest.pending.schoolId, 'second');
  assert.equal(latest.pending.classroom, 3);
  assert.equal(latest.checking, false);
});

test('shared verification rejects stale results and ignores results after the active school changes', async () => {
  let latest;
  const session = exports.createSharedSelectionSession((state) => { latest = state; });
  const school = { id: 'shared', name: '공유 학교', region: '서울' };
  const fallback = { school: { id: 'old' }, grade: 1, classroom: 1 };
  let applied = 0;
  let failed = 0;
  const shared = { school, grade: 1, classroom: 1 };
  await session.verifySchool(shared, fallback, () => 'old', async () => ({ schools: [school], stale: true }), () => applied++, () => failed++);
  assert.equal(failed, 1);
  assert.equal(latest.pending, null);
  await session.verifySchool(shared, fallback, () => 'another', async () => ({ schools: [school], stale: false }), () => applied++, () => failed++);
  assert.equal(applied, 0);
  assert.equal(failed, 1);
  assert.equal(latest.pending, null);
  assert.equal(latest.checking, false);
});

test('grade and class options are unique, sorted and limited by school level', () => {
  const records = [{ grade: 2, class: '11' }, { grade: 2, class: 3 }, { grade: 2, class: 3 },
    { grade: 4, class: 1 }, { grade: 0, class: 1 }, { grade: 2, class: 'bad' }];
  assert.deepEqual(Array.from(exports.gradesInTimetable(records, 3)), [2]);
  assert.deepEqual(Array.from(exports.gradesInTimetable(records, 6)), [2, 4]);
  assert.deepEqual(Array.from(exports.classesInGrade(records, 2)), [3, 11]);
  assert.deepEqual(Array.from(exports.classesInGrade([], 1)), []);
});

test('class reconciliation preserves a valid choice and falls back only when options exist', () => {
  const records = [{ grade: 2, class: 4 }, { grade: 2, class: 2 }, { grade: 3, class: 1 }];
  const reconcile = (grade, classroom, values = records) => JSON.parse(JSON.stringify(exports.reconcileClassSelection(values, 3, grade, classroom)));
  assert.deepEqual(reconcile(2, 4), { grade: 2, classroom: 4 });
  assert.deepEqual(reconcile(2, 9), { grade: 2, classroom: 2 });
  assert.deepEqual(reconcile(1, 9), { grade: 2, classroom: 2 });
  assert.deepEqual(reconcile(1, 9, []), { grade: 1, classroom: 9 });
});
