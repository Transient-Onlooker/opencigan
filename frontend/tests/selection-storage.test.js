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

test('grade and class options are unique, sorted and limited by school level', () => {
  const records = [{ grade: 2, class: '11' }, { grade: 2, class: 3 }, { grade: 2, class: 3 },
    { grade: 4, class: 1 }, { grade: 0, class: 1 }, { grade: 2, class: 'bad' }];
  assert.deepEqual(Array.from(exports.gradesInTimetable(records, 3)), [2]);
  assert.deepEqual(Array.from(exports.gradesInTimetable(records, 6)), [2, 4]);
  assert.deepEqual(Array.from(exports.classesInGrade(records, 2)), [3, 11]);
  assert.deepEqual(Array.from(exports.classesInGrade([], 1)), []);
});
