import { test } from 'node:test';
import assert from 'node:assert/strict';
import { personalizationVm as prefs } from './helpers/personalization-vm.js';

test('meal preferences preserve valid stored values and keep meal types ordered', () => {
  const values = new Map([
    ['opensigan-allergies', '[11,1,11,20,"2"]'],
    ['opensigan-meal-preferences', '{"view":"week","types":["석식","중식","unknown"],"showAllergenNumbers":false}'],
  ]);
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  const types = ['조식', '중식', '석식'];
  assert.deepEqual(Array.from(prefs.readAllergies(storage)), [1, 11]);
  const result = prefs.readMealPreferences(storage, types, { view: 'day', types, showAllergenNumbers: true });
  assert.equal(result.view, 'week');
  assert.deepEqual(Array.from(result.types), ['중식', '석식']);
  assert.equal(result.showAllergenNumbers, false);
  prefs.saveAllergies(storage, [1, 11]);
  prefs.saveMealPreferences(storage, result);
  assert.equal(values.get('opensigan-allergies'), '[1,11]');
  assert.equal(JSON.parse(values.get('opensigan-meal-preferences')).view, 'week');
});

test('school preferences isolate keys and recover malformed stored data', () => {
  const values = new Map([['pref:a', '{"value":4}'], ['pref:b', '{bad']]);
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  const parse = (value) => value ?? { value: 0 };
  assert.equal(prefs.readSchoolPreference(storage, 'pref:', 'a', parse, () => ({ value: -1 })).value, 4);
  assert.equal(prefs.readSchoolPreference(storage, 'pref:', 'b', parse, () => ({ value: -1 })).value, -1);
  prefs.writeSchoolPreference(storage, 'pref:', 'a', { value: 5 });
  assert.equal(values.get('pref:a'), '{"value":5}');
  assert.equal(values.get('pref:b'), '{bad');
});
