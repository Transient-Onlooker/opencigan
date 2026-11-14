import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';
import { personalizationVm } from './helpers/personalization-vm.js';
import { lessonTimesVm } from './helpers/lesson-times-vm.js';

const source = await readFile(new URL('../src/sharing.ts', import.meta.url), 'utf8');
const context = { exports: {}, URL, URLSearchParams };
runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), context);
const { shareClassUrl, readSharedClass, findLessons } = context.exports;

test('shared class restores Korean names and keeps identifiers in the URL fragment', () => {
  const school = { id: '123:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  const url = new URL(shareClassUrl('https://opencigan.mcv.kr/?old=value#old', school, 2, 7));
  assert.equal(url.search, '');
  assert.deepEqual(JSON.parse(JSON.stringify(readSharedClass(url.hash))), { school, grade: 2, classroom: 7 });
});

test('malformed, duplicated and out-of-range shared class values are ignored', () => {
  const good = 'school=123%3ASchool&name=School&region=Seoul&grade=2&class=7';
  for (const hash of ['', good + '&grade=3', good.replace('class=7', 'class=0'), good.replace('grade=2', 'grade=7'), good.replace('123%3ASchool', 'invalid'), 'x'.repeat(4097)]) {
    assert.equal(readSharedClass(hash), null);
  }
});

test('lesson search matches subject or teacher, combines weekday and preserves source order', () => {
  const records = [
    { date: '2026-11-10', period: 2, subject: 'Math', teacher: 'Kim' },
    { date: '2026-11-09', period: 3, subject: '국어', teacher: '박선생' },
    { date: '2026-11-09', period: 1, subject: '수학', teacher: null },
  ];
  assert.equal(findLessons(records, 'math', '').length, 1);
  assert.equal(findLessons(records, '선생', '1')[0].subject, '국어');
  assert.equal(findLessons(records, 'Kim', '1').length, 0);
  assert.equal(findLessons(records, '', '1')[0].period, 1);
  assert.equal(records[0].date, '2026-11-10');
});

test('shared class takes precedence at startup even when browser storage is blocked', async () => {
  const component = await readFile(new URL('../src/App.svelte', import.meta.url), 'utf8');
  const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^\s*import .*;\s*$/gm, '');
  const school = { id: '123:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  const hash = new URL(shareClassUrl('https://opencigan.mcv.kr/', school, 2, 7)).hash;
  let mount;
  const requests = [];
  const javascript = ts.transpile(`(function(){${script}\nreturn { state: () => ({ school, grade, classroom, classError, sharedClassState }), changeTypeText };})()`, { target: ts.ScriptTarget.ES2022 });
  const app = runInNewContext(javascript, {
    ...personalizationVm,
    ...lessonTimesVm,
    ...context.exports, onMount: (callback) => { mount = callback; },
    currentKoreaDate: () => '2026-11-14', monday: () => '2026-11-09',
    addDays: () => '2026-11-15', clampWeek: (week) => week,
    isAnalyticsEnabled: () => false,
    window: { location: { hash }, addEventListener() {}, removeEventListener() {} },
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    localStorage: { getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); } },
    searchSchools: async () => ({ schools: [school], stale: false }),
    getTimetable: (id) => {
      requests.push(id);
      return Promise.resolve({ schoolId: id, weekStart: '2026-11-09', records: [{ grade: 2, class: 7 }], sourceUpdatedAt: null, fetchedAt: '2026-11-14T00:00:00.000Z', stale: false });
    },
    searchNeisSchools: () => new Promise(() => {}),
    setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout, AbortController,
  });
  const cleanup = mount();
  await new Promise(setImmediate);
  assert.equal(app.state().school.id, school.id);
  assert.equal(app.state().grade, 2);
  assert.equal(app.state().classroom, 7);
  assert.equal(app.state().classError, false);
  assert.equal(app.state().sharedClassState, '');
  assert.deepEqual(requests, [school.id]);
  assert.equal(app.changeTypeText('deleted'), '삭제');
  cleanup();
});

test('검증되지 않은 공유 학교는 저장하지 않고 이전 학교 선택을 유지한다', async () => {
  const component = await readFile(new URL('../src/App.svelte', import.meta.url), 'utf8');
  const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^\s*import .*;\s*$/gm, '');
  const savedSchool = { id: '123:기존고등학교', name: '기존고등학교', region: '서울' };
  const sharedSchool = { id: '99999999:없는학교', name: '없는학교', region: '서울' };
  const hash = new URL(shareClassUrl('https://opencigan.mcv.kr/', sharedSchool, 2, 7)).hash;
  const values = new Map([
    ['opensigan-school', JSON.stringify(savedSchool)],
    ['opensigan-grade', '3'],
    ['opensigan-class', '4'],
  ]);
  const requests = [];
  let mount;
  const javascript = ts.transpile(`(function(){${script}\nreturn { state: () => ({ school, grade, classroom, sharedClassState }) };})()`, { target: ts.ScriptTarget.ES2022 });
  const app = runInNewContext(javascript, {
    ...personalizationVm,
    ...lessonTimesVm,
    ...context.exports, onMount: (callback) => { mount = callback; },
    currentKoreaDate: () => '2026-11-14', monday: () => '2026-11-09',
    addDays: () => '2026-11-15', clampWeek: (week) => week,
    isAnalyticsEnabled: () => false,
    window: { location: { hash }, addEventListener() {}, removeEventListener() {} },
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    localStorage: {
      getItem(key) { return values.get(key) ?? null; },
      setItem(key, value) { values.set(key, value); },
      removeItem(key) { values.delete(key); },
    },
    searchSchools: async () => ({ schools: [savedSchool], stale: false }),
    getTimetable: (id) => { requests.push(id); return new Promise(() => {}); },
    searchNeisSchools: () => new Promise(() => {}),
    setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout, AbortController,
  });
  const cleanup = mount();
  await new Promise(setImmediate);
  assert.equal(app.state().school.id, savedSchool.id);
  assert.equal(app.state().grade, 3);
  assert.equal(app.state().classroom, 4);
  assert.equal(JSON.parse(values.get('opensigan-school')).id, savedSchool.id);
  assert.deepEqual(requests, [savedSchool.id]);
  assert.match(app.state().sharedClassState, /확인하지 못해 이전 학교를 유지/);
  cleanup();
});

test('공유 링크의 학급이 실제 시간표에 없으면 이전 학교와 학급을 유지한다', async () => {
  const component = await readFile(new URL('../src/App.svelte', import.meta.url), 'utf8');
  const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^\s*import .*;\s*$/gm, '');
  const savedSchool = { id: '123:기존고등학교', name: '기존고등학교', region: '서울' };
  const sharedSchool = { id: '456:공유고등학교', name: '공유고등학교', region: '경기' };
  const hash = new URL(shareClassUrl('https://opencigan.mcv.kr/', sharedSchool, 2, 7)).hash;
  const values = new Map([
    ['opensigan-school', JSON.stringify(savedSchool)],
    ['opensigan-grade', '3'],
    ['opensigan-class', '4'],
  ]);
  let mount;
  const javascript = ts.transpile(`(function(){${script}\nreturn { state: () => ({ school, grade, classroom, classError, sharedClassState }) };})()`, { target: ts.ScriptTarget.ES2022 });
  const app = runInNewContext(javascript, {
    ...personalizationVm,
    ...lessonTimesVm,
    ...context.exports, onMount: (callback) => { mount = callback; },
    currentKoreaDate: () => '2026-11-14', monday: () => '2026-11-09',
    addDays: () => '2026-11-15', clampWeek: (week) => week,
    isAnalyticsEnabled: () => false,
    window: { location: { hash }, addEventListener() {}, removeEventListener() {} },
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    localStorage: {
      getItem(key) { return values.get(key) ?? null; },
      setItem(key, value) { values.set(key, value); },
      removeItem(key) { values.delete(key); },
    },
    searchSchools: async () => ({ schools: [sharedSchool], stale: false }),
    getTimetable: async (id) => ({
      schoolId: id, weekStart: '2026-11-09',
      records: id === sharedSchool.id ? [{ grade: 2, class: 1 }] : [{ grade: 3, class: 4 }],
      sourceUpdatedAt: null, fetchedAt: '2026-11-14T00:00:00.000Z', stale: false,
    }),
    searchNeisSchools: () => new Promise(() => {}),
    setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout, AbortController,
  });
  const cleanup = mount();
  await new Promise(setImmediate);
  await new Promise(setImmediate);
  assert.equal(app.state().school.id, savedSchool.id);
  assert.equal(app.state().grade, 3);
  assert.equal(app.state().classroom, 4);
  assert.equal(app.state().classError, false);
  assert.match(app.state().sharedClassState, /이전 학교와 학급을 유지/);
  assert.equal(JSON.parse(values.get('opensigan-school')).id, savedSchool.id);
  cleanup();
});

test('저장된 학교가 없어도 존재하지 않는 공유 학급을 자동으로 다른 반으로 바꾸지 않는다', async () => {
  const component = await readFile(new URL('../src/App.svelte', import.meta.url), 'utf8');
  const script = component.match(/<script lang="ts">([\s\S]*?)<\/script>/)[1].replace(/^\s*import .*;\s*$/gm, '');
  const school = { id: '456:공유고등학교', name: '공유고등학교', region: '경기' };
  const hash = new URL(shareClassUrl('https://opencigan.mcv.kr/', school, 2, 7)).hash;
  let mount;
  const javascript = ts.transpile(`(function(){${script}\nreturn { state: () => ({ school, grade, classroom, classError, sharedClassState }) };})()`, { target: ts.ScriptTarget.ES2022 });
  const app = runInNewContext(javascript, {
    ...personalizationVm,
    ...lessonTimesVm,
    ...context.exports, onMount: (callback) => { mount = callback; },
    currentKoreaDate: () => '2026-11-14', monday: () => '2026-11-09',
    addDays: () => '2026-11-15', clampWeek: (week) => week,
    isAnalyticsEnabled: () => false,
    window: { location: { hash }, addEventListener() {}, removeEventListener() {} },
    document: { visibilityState: 'visible', addEventListener() {}, removeEventListener() {} },
    localStorage: { getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); } },
    searchSchools: async () => ({ schools: [school], stale: false }),
    getTimetable: async (id) => ({ schoolId: id, weekStart: '2026-11-09', records: [{ grade: 2, class: 1 }], sourceUpdatedAt: null, fetchedAt: '2026-11-14T00:00:00.000Z', stale: false }),
    searchNeisSchools: () => new Promise(() => {}),
    setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout, AbortController,
  });
  const cleanup = mount();
  await new Promise(setImmediate);
  await new Promise(setImmediate);
  assert.equal(app.state().school.id, school.id);
  assert.equal(app.state().grade, 2);
  assert.equal(app.state().classroom, 7);
  assert.equal(app.state().classError, true);
  assert.match(app.state().sharedClassState, /시간표 데이터에 없어 적용하지 않았어요/);
  cleanup();
});
