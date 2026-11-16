import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';
import { personalizationVm } from './helpers/personalization-vm.js';
import { lessonTimesVm } from './helpers/lesson-times-vm.js';

const component = await readFile(new URL('../src/App.svelte', import.meta.url), 'utf8');
const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^\s*import .*;\s*$/gm, '');
const source = ts.transpile(`(function () { ${script}
  return { chooseSchool, updateClass,
    setAvailableClasses: (values) => { availableClasses = values; },
    state: () => ({ school, grade, classroom, classError }) };
})()`, { target: ts.ScriptTarget.ES2022 });

test('학교 변경은 유효한 학급을 선택하고 이전 즐겨찾기 데이터는 보존한다', async () => {
  const first = { id: '1:첫학교', name: '첫학교', region: '서울' };
  const second = { id: '2:둘째학교', name: '둘째학교', region: '경기' };
  const legacy = '[{"legacy":true}]';
  const store = new Map([['opensigan-favorites', legacy]]);
  const records = {
    [first.id]: [{ grade: 2, class: 3, period: 1, date: '2026-11-09', subject: '국어' }],
    [second.id]: [{ grade: 1, class: 2, period: 1, date: '2026-11-09', subject: '수학' }],
  };
  const app = runInNewContext(source, {
    ...personalizationVm, ...lessonTimesVm,
    onMount() {}, currentKoreaDate: () => '2026-11-14', monday: () => '2026-11-09',
    addDays: () => '2026-11-15', clampWeek: (week) => week,
    localStorage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) },
    getTimetable: (id, weekStart) => Promise.resolve({ schoolId: id, weekStart, records: records[id] ?? [] }),
    searchNeisSchools: () => new Promise(() => {}), AbortController, setTimeout, clearTimeout,
  });
  app.chooseSchool(first);
  await new Promise(setImmediate);
  assert.equal(app.state().grade, 2);
  assert.equal(app.state().classroom, 3);
  app.setAvailableClasses([3]);
  app.updateClass({ currentTarget: { valueAsNumber: 9 } });
  assert.equal(app.state().classError, true);
  assert.equal(app.state().classroom, 3);
  app.chooseSchool(second);
  await new Promise(setImmediate);
  assert.equal(app.state().grade, 1);
  assert.equal(app.state().classroom, 2);
  assert.equal(store.get('opensigan-class'), '2');
  assert.equal(store.get('opensigan-favorites'), legacy);
});
