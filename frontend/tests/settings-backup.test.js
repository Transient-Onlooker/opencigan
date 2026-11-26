import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

async function loadModule(filename, imports = {}) {
  const source = await readFile(new URL(`../src/${filename}`, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  runInNewContext(compiled, { exports, require: (path) => imports[path], TextEncoder });
  return exports;
}

const personalization = await loadModule('personalization.ts');
const lessonTimes = await loadModule('lesson-times.ts');
const { createSettingsBackup, parseSettingsBackup, saveSchoolSettingsBackup, saveLessonTimePreferences, MAX_SETTINGS_BACKUP_BYTES } = await loadModule('settings-backup.ts', {
  './personalization': personalization,
  './lesson-times': lessonTimes,
});

const schoolId = 'test-school-123';
const display = { ...personalization.defaultDisplaySettings(), showTeachers: false, density: 'compact', colorMode: 'custom', subjectAliases: { math: 'M', science: 'S' }, subjectColors: { math: '#123456', science: '#abcdef' } };
const times = { 1: { start: '09:00', end: '09:50' }, 2: { start: '10:00', end: '10:50' } };

test('school settings import restores prior values if the second write fails', () => {
  const values = new Map([['opensigan-display:' + schoolId, 'old-display'], ['opensigan-lesson-times:' + schoolId, 'old-times']]);
  let failed = false;
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      if (key.startsWith('opensigan-lesson-times:') && !failed) { failed = true; throw new Error('blocked'); }
      values.set(key, value);
    },
    removeItem: (key) => values.delete(key),
  };
  assert.throws(() => saveSchoolSettingsBackup(storage, schoolId, display, times), /저장하지 못했어요/);
  assert.equal(values.get('opensigan-display:' + schoolId), 'old-display');
  assert.equal(values.get('opensigan-lesson-times:' + schoolId), 'old-times');
});

test('failed import preserves another writer and does not revert unwritten keys', () => {
  const displayKey = 'opensigan-display:' + schoolId, timesKey = 'opensigan-lesson-times:' + schoolId;
  const values = new Map([[displayKey, 'old-display'], [timesKey, 'old-times']]);
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => {
      if (key === timesKey) {
        values.set(displayKey, 'newer-display');
        values.set(timesKey, 'newer-times');
        throw new Error('blocked');
      }
      values.set(key, value);
    },
    removeItem: (key) => values.delete(key),
  };
  assert.throws(() => saveSchoolSettingsBackup(storage, schoolId, display, times), /저장하지 못했어요/);
  assert.equal(values.get(displayKey), 'newer-display');
  assert.equal(values.get(timesKey), 'newer-times');
});

test('failed lesson preference save preserves a newer value', () => {
  const key = 'opensigan-lesson-times:' + schoolId, weekdayKey = 'opensigan-weekday-lesson-times:' + schoolId;
  const values = new Map([[key, 'old-times'], [weekdayKey, 'old-weekdays']]);
  const storage = {
    getItem: (name) => values.get(name) ?? null,
    setItem: (name, value) => {
      if (name === weekdayKey) { values.set(key, 'newer-times'); throw new Error('blocked'); }
      values.set(name, value);
    },
    removeItem: (name) => values.delete(name),
  };
  assert.throws(() => saveLessonTimePreferences(storage, schoolId, times, {}), /복구하지 못했어요/);
  assert.equal(values.get(key), 'newer-times');
});

test('요일별 저장 실패 시 공통 시각과 요일별 시각을 이전 값으로 되돌린다', () => {
  const key = 'opensigan-lesson-times:' + schoolId, weekdayKey = 'opensigan-weekday-lesson-times:' + schoolId;
  const values = new Map([[key, 'old-times'], [weekdayKey, 'old-weekdays']]);
  let failed = false;
  const storage = { getItem: (k) => values.get(k) ?? null, removeItem: (k) => values.delete(k), setItem: (k, v) => {
    if (k === weekdayKey && !failed) { failed = true; throw new Error('blocked'); }
    values.set(k, v);
  } };
  assert.throws(() => saveLessonTimePreferences(storage, schoolId, times, { 2: { 1: times[1] } }), /저장하지 못했어요/);
  assert.equal(values.get(key), 'old-times');
  assert.equal(values.get(weekdayKey), 'old-weekdays');
});

test('원본 적용 기록 저장 실패 시 교시 시각도 함께 이전 값으로 되돌린다', () => {
  const key = 'opensigan-lesson-times:' + schoolId;
  const weekdayKey = 'opensigan-weekday-lesson-times:' + schoolId;
  const preferenceKey = 'opensigan-source-lesson-preference:' + schoolId;
  const values = new Map([[key, 'old-times'], [weekdayKey, 'old-weekdays'], [preferenceKey, 'old-source-preference']]);
  let failed = false;
  const storage = {
    getItem: (storageKey) => values.get(storageKey) ?? null,
    removeItem: (storageKey) => values.delete(storageKey),
    setItem: (storageKey, value) => {
      if (storageKey === preferenceKey && !failed) { failed = true; throw new Error('blocked'); }
      values.set(storageKey, value);
    },
  };
  assert.throws(
    () => saveLessonTimePreferences(storage, schoolId, times, { 2: { 1: times[1] } }, { enabled: true, applied: { 1: '09:00' }, previous: {} }),
    /이전 저장값은 유지했어요/,
  );
  assert.equal(values.get(key), 'old-times');
  assert.equal(values.get(weekdayKey), 'old-weekdays');
  assert.equal(values.get(preferenceKey), 'old-source-preference');
});

test('export and import round trip preserves school settings without allergy preferences', () => {
  const exported = createSettingsBackup(schoolId, display, times);
  const parsed = JSON.parse(exported);
  assert.equal(parsed.version, 1);
  assert.equal(parsed.schoolId, schoolId);
  assert.equal(parsed.allergySelection, undefined);
  const restored = parseSettingsBackup(exported, schoolId);
  assert.equal(restored.displaySettings.showTeachers, false);
  assert.equal(restored.displaySettings.density, 'compact');
  assert.equal(restored.displaySettings.subjectAliases.math, 'M');
  assert.equal(restored.displaySettings.subjectAliases.science, 'S');
  assert.equal(restored.displaySettings.subjectColors.math, '#123456');
  assert.equal(restored.displaySettings.subjectColors.science, '#abcdef');
  assert.equal(restored.lessonTimes[2].start, '10:00');
});

test('rejects malformed, foreign-school, obsolete and oversized backup files', () => {
  const original = JSON.parse(createSettingsBackup(schoolId, display, times));
  assert.throws(() => parseSettingsBackup('{', schoolId), /JSON/);
  assert.throws(() => parseSettingsBackup(JSON.stringify(original), 'other-school'), /학교/);
  assert.throws(() => parseSettingsBackup(JSON.stringify({ ...original, version: 100 }), schoolId));
  assert.throws(() => parseSettingsBackup(' '.repeat(MAX_SETTINGS_BACKUP_BYTES + 1), schoolId), /64KB/);
  assert.throws(() => parseSettingsBackup(JSON.stringify({ ...original, lessonTimes: null }), schoolId));
});

test('rejects invalid period numbers and overlapping class times instead of silently dropping them', () => {
  const original = JSON.parse(createSettingsBackup(schoolId, display, times));
  assert.throws(() => parseSettingsBackup(JSON.stringify({ ...original, lessonTimes: { ...times, 21: times[1] } }), schoolId));
  assert.throws(() => parseSettingsBackup(JSON.stringify({ ...original, lessonTimes: { ...times, 2: { start: '09:30', end: '10:10' } } }), schoolId));
  assert.throws(() => parseSettingsBackup(JSON.stringify({ ...original, lessonTimes: { 1: { start: '25:00', end: '26:00' } } }), schoolId));
});

test('classroom backups restore only into the matching class and omit school bell times', () => {
  const scope = { grade: 1, classroom: 2 };
  const exported = createSettingsBackup(schoolId, display, times, scope);
  assert.equal(JSON.parse(exported).lessonTimes, undefined);
  assert.equal(parseSettingsBackup(exported, schoolId, scope).scoped, true);
  assert.equal(parseSettingsBackup(exported, schoolId, scope).displaySettings.density, 'compact');
  assert.equal(parseSettingsBackup(exported, schoolId, scope).displaySettings.subjectColors.science, '#abcdef');
  assert.throws(() => parseSettingsBackup(exported, schoolId, { ...scope, classroom: 3 }), /학급/);
  assert.throws(() => parseSettingsBackup(exported, schoolId), /학급/);
});

test('weekday overrides use version 2 and validate against the full day without changing version 1', () => {
  const overrides = { 2: { 1: { start: '08:30', end: '09:20' } } };
  const text = createSettingsBackup(schoolId, display, times, undefined, overrides);
  assert.equal(JSON.parse(text).version, 2);
  const restored = parseSettingsBackup(text, schoolId);
  assert.equal(restored.lessonTimes[1].start, '09:00');
  assert.equal(restored.weekdayLessonTimes[2][1].start, '08:30');
  assert.equal(JSON.parse(createSettingsBackup(schoolId, display, times)).version, 1);
  assert.equal(parseSettingsBackup(createSettingsBackup(schoolId, display, times), schoolId).weekdayLessonTimes, undefined);
  const original = JSON.parse(text);
  for (const invalid of [
    { 8: overrides[2] }, { 2: { 1: { start: '09:30', end: '10:10' } } },
    { 2: { 1: { start: '25:00', end: '26:00' } } }, { 2: { 21: times[1] } },
  ]) assert.throws(() => parseSettingsBackup(JSON.stringify({ ...original, weekdayLessonTimes: invalid }), schoolId));
  assert.throws(() => parseSettingsBackup(JSON.stringify({ ...original, weekdayLessonTimes: null }), schoolId));
  assert.throws(() => createSettingsBackup(schoolId, display, times, undefined, { 2: { 1: { start: '09:30', end: '10:10' } } }));
});
