import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

async function loadModule(path, dependencies = {}) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  runInNewContext(compiled, {
    exports,
    require: (name) => {
      if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
      return dependencies[name];
    },
  });
  return exports;
}

const allergens = await loadModule('../src/allergens.ts');
const { filterDishes } = await loadModule('../src/meal-filter.ts', { './allergens': allergens });

test('search is trimmed, NFC-normalized and case-insensitive', () => {
  const dishes = ['김치볶음밥(5.6)', '계란말이(1.2)', '우유(2)'];
  assert.deepEqual(Array.from(filterDishes(dishes, '  김치  ', [], 'all')), ['김치볶음밥(5.6)']);
  assert.deepEqual(Array.from(filterDishes(['Café 라떼(2)'], 'CAFÉ', [], 'all')), ['Café 라떼(2)']);
});

test('allergy filters use selected NEIS markers and do not infer safety', () => {
  const dishes = ['계란말이(1.2)', '김치볶음밥(5.6)', '흰밥'];
  assert.deepEqual(Array.from(filterDishes(dishes, '', [1], 'marked')), ['계란말이(1.2)']);
  assert.deepEqual(Array.from(filterDishes(dishes, '', [1], 'unmarked')), ['김치볶음밥(5.6)', '흰밥']);
  assert.deepEqual(Array.from(filterDishes(dishes, '', [], 'marked')), []);
  assert.deepEqual(Array.from(filterDishes(dishes, '', [], 'unmarked')), dishes);
});

test('search and allergy filters are applied together', () => {
  const dishes = ['계란말이(1.2)', '계란국(1.5)', '김치볶음밥(5.6)'];
  assert.deepEqual(Array.from(filterDishes(dishes, '계란', [1], 'marked')), ['계란말이(1.2)', '계란국(1.5)']);
  assert.deepEqual(Array.from(filterDishes(dishes, '계란', [1], 'unmarked')), []);
});
