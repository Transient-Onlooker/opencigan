import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/selection.ts', import.meta.url), 'utf8');
const exports = {};
runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports });

test('selection persistence preserves keys, values and write order', () => {
  const writes = [];
  const storage = { setItem: (key, value) => writes.push([key, value]) };
  const school = { id: '2:학교', name: '학교', region: '서울' };
  exports.saveSelection(storage, school, 2, 3);
  exports.saveGradeAndClass(storage, 3, 4);
  exports.saveClassToStorage(storage, 5);
  assert.deepEqual(writes, [
    ['opensigan-school', JSON.stringify(school)], ['opensigan-grade', '2'], ['opensigan-class', '3'],
    ['opensigan-grade', '3'], ['opensigan-class', '4'], ['opensigan-class', '5'],
  ]);
});

test('selection persistence tolerates blocked storage and stops subsequent writes', () => {
  const attempted = [];
  const storage = { setItem: (key) => { attempted.push(key); throw new Error('blocked'); } };
  assert.doesNotThrow(() => exports.saveGradeAndClass(storage, 1, 2));
  assert.deepEqual(attempted, ['opensigan-grade']);
  assert.doesNotThrow(() => exports.saveClassToStorage(storage, 2));
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
