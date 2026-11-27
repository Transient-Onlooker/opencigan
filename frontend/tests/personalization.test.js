import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/personalization.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const helpers = {};
runInNewContext(compiled, { exports: helpers });
const { defaultDisplaySettings, parseDisplaySettings, displaySubject, displayTeacher, subjectColor, subjectTextColor } = helpers;

test('ended lesson and other weekday visibility settings default safely and parse saved choices', () => {
  assert.equal(defaultDisplaySettings().endedLessonMode, 'dim');
  assert.equal(defaultDisplaySettings().dimOtherDays, false);
  assert.equal(parseDisplaySettings({ endedLessonMode: 'hide', dimOtherDays: true }).endedLessonMode, 'hide');
  assert.equal(parseDisplaySettings({ endedLessonMode: 'normal' }).endedLessonMode, 'normal');
  assert.equal(parseDisplaySettings({ endedLessonMode: 'invalid', dimOtherDays: 'true' }).endedLessonMode, 'dim');
  assert.equal(parseDisplaySettings({ endedLessonMode: 'invalid', dimOtherDays: 'true' }).dimOtherDays, false);
});

test('timetable display preferences load old saves and reject invalid values', () => {
  const defaults = parseDisplaySettings({ showTeachers: false });
  assert.equal(defaults.showDates, true);
  assert.equal(defaults.showChangeHighlights, true);
  assert.equal(defaults.showChangeBadges, true);
  assert.equal(defaults.showCellBorders, true);
  assert.equal(defaults.density, 'normal');

  const custom = parseDisplaySettings({ showDates: false, showChangeHighlights: false, showChangeBadges: false, showCellBorders: false, density: 'compact' });
  assert.equal(custom.showDates, false);
  assert.equal(custom.showChangeHighlights, false);
  assert.equal(custom.showChangeBadges, false);
  assert.equal(custom.showCellBorders, false);
  assert.equal(custom.density, 'compact');
  assert.equal(parseDisplaySettings({ density: 'relaxed' }).density, 'relaxed');

  const invalid = parseDisplaySettings({ showDates: 'false', showChangeHighlights: null, showChangeBadges: 0, showCellBorders: 'no', density: 'extra' });
  assert.equal(invalid.showDates, true);
  assert.equal(invalid.showChangeHighlights, true);
  assert.equal(invalid.showChangeBadges, true);
  assert.equal(invalid.showCellBorders, true);
  assert.equal(invalid.density, 'normal');
});

test('default settings keep monochrome and original labels', () => {
  const settings = defaultDisplaySettings();
  assert.equal(settings.colorMode, 'none');
  assert.equal(settings.showTeachers, true);
  assert.equal(displaySubject('수학Ⅱ', settings), '수학Ⅱ');
  assert.equal(displayTeacher('김철수', settings), '김철수');
  assert.equal(subjectColor('수학Ⅱ', settings), undefined);
});

test('custom names change only displayed labels', () => {
  const settings = parseDisplaySettings({
    subjectAliases: { '수학Ⅱ': '수2' },
    teacherAliases: { '김철수': '김T' },
    teacherPrefix: '담당 ',
    teacherSuffix: ' 선생님',
  });
  assert.equal(displaySubject('수학Ⅱ', settings), '수2');
  assert.equal(displayTeacher('김철수', settings), '담당 김T 선생님');
  assert.equal(settings.subjectAliases['수학Ⅱ'], '수2');
  assert.equal(displaySubject('물리', settings), '물리');
});

test('malformed persisted colors and values are ignored', () => {
  const settings = parseDisplaySettings({
    colorMode: 'custom',
    subjectColors: { 수학: '#123abc', 과학: 'red' },
    subjectAliases: { 국어: 23 },
    showTeachers: false,
  });
  assert.equal(settings.subjectColors['수학'], '#123abc');
  assert.equal(settings.subjectColors['과학'], undefined);
  assert.equal(settings.subjectAliases['국어'], undefined);
  assert.equal(settings.showTeachers, false);
  assert.equal(subjectColor('수학', settings), '#123abc');
  assert.equal(subjectTextColor('#000000'), '#ffffff');
  assert.equal(subjectTextColor('#ffffff'), '#111111');
  assert.equal(parseDisplaySettings({ colorMode: 'other' }).colorMode, 'none');
});

test('automatic colors are stable for the same original subject', () => {
  const settings = parseDisplaySettings({ colorMode: 'auto', subjectAliases: { 수학: '수2' } });
  const original = subjectColor('수학', settings);
  assert.match(original, /^#[a-f0-9]{6}$/i);
  assert.equal(subjectColor('수학', settings), original);
  assert.equal(subjectColor('수학', parseDisplaySettings({ colorMode: 'auto' })), original);
});

test('class display storage key and event prefix preserve the existing format', () => {
  assert.equal(helpers.classDisplayStorageKey('school-a', 1, 2), 'opensigan-class-display:school-a:1:2');
  assert.equal(helpers.classDisplayStoragePrefix('school-a'), 'opensigan-class-display:school-a:');
  assert.equal(helpers.classDisplayStorageKey('B10:1234567', 2, 3), 'opensigan-class-display:B10:1234567:2:3');
});

test('class display preferences remain isolated by school and class when storage is blocked', () => {
  const fallback = helpers.defaultDisplaySettings();
  const custom = { ...fallback, showTeachers: false };
  const unavailable = () => { throw new Error('blocked'); };
  const prefs = helpers.createClassDisplayPreferences(unavailable);
  prefs.set('school-a:1:1', custom);
  assert.equal(prefs.read('school-a:1:1', fallback).settings.showTeachers, false);
  assert.equal(prefs.read('school-a:1:2', fallback).settings, fallback);
  assert.equal(prefs.read('school-b:1:1', fallback).settings, fallback);
  prefs.set('school-a:1:1', null);
  assert.equal(prefs.read('school-a:1:1', fallback).enabled, false);
});

test('class display storage events refresh another tab draft and removal disables only that class', () => {
  const fallback = helpers.defaultDisplaySettings();
  const values = new Map();
  const storage = () => ({
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  });
  const firstTab = helpers.createClassDisplayPreferences(storage);
  const secondTab = helpers.createClassDisplayPreferences(storage);
  const classKey = helpers.classDisplayStorageKey('school-a', 1, 2);
  firstTab.read(classKey, fallback);
  secondTab.set(classKey, { ...fallback, density: 'compact' });

  let saved = firstTab.syncFromStorage(classKey);
  assert.equal(saved.enabled, true);
  assert.equal(saved.settings.density, 'compact');

  values.delete(classKey);
  saved = firstTab.syncFromStorage(classKey);
  assert.equal(saved.enabled, false);
  assert.equal(firstTab.read(classKey, fallback).settings, fallback);
  assert.equal(firstTab.read('opensigan-class-display:school-b:1:2', fallback).enabled, false);

  secondTab.set(classKey, { ...fallback, density: 'relaxed' });
  values.clear();
  assert.equal(firstTab.syncFromStorage(classKey).enabled, false);
});

test('class display synchronization reads the latest value and preserves local fallback on storage failure', () => {
  const fallback = helpers.defaultDisplaySettings();
  const values = new Map();
  let writesBlocked = false;
  const prefs = helpers.createClassDisplayPreferences(() => ({
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { if (writesBlocked) throw new Error('blocked'); values.set(key, value); },
    removeItem: (key) => values.delete(key),
  }));
  const key = 'opensigan-class-display:school-a:1:1';
  const earlier = { ...fallback, density: 'compact' };
  const latest = { ...fallback, density: 'relaxed' };
  prefs.read(key, fallback);
  values.set(key, JSON.stringify(earlier));
  values.set(key, JSON.stringify(latest));
  assert.equal(prefs.syncFromStorage(key).settings.density, 'relaxed');

  writesBlocked = true;
  const localDraft = { ...fallback, showTeachers: false };
  prefs.set(key, localDraft);
  values.delete(key);
  assert.equal(prefs.syncFromStorage(key).settings.showTeachers, false);
  assert.equal(prefs.read(key, fallback).settings.showTeachers, false);

  writesBlocked = false;
  const restored = { ...fallback, density: 'compact' };
  prefs.restore(key, restored);
  values.set(key, JSON.stringify(latest));
  assert.equal(prefs.syncFromStorage(key).settings.density, 'relaxed');
});

test('school display preferences synchronize across tabs and retain failed local writes', () => {
  const fallback = helpers.defaultDisplaySettings();
  const values = new Map();
  let writesBlocked = false;
  const storage = () => ({
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { if (writesBlocked) throw new Error('blocked'); values.set(key, value); },
  });
  const firstTab = helpers.createSchoolDisplayPreferences(storage);
  const secondTab = helpers.createSchoolDisplayPreferences(storage);
  firstTab.read('school-a', fallback);
  secondTab.set('school-a', { ...fallback, showTeachers: false });
  assert.equal(firstTab.syncFromStorage('school-a', fallback).showTeachers, false);
  assert.equal(firstTab.syncFromStorage('school-b', fallback).showTeachers, true);

  values.clear();
  assert.equal(firstTab.syncFromStorage('school-a', fallback).showTeachers, true);

  writesBlocked = true;
  const localDraft = { ...fallback, density: 'compact' };
  firstTab.set('school-a', localDraft);
  values.clear();
  assert.equal(firstTab.syncFromStorage('school-a', fallback).density, 'compact');
  assert.equal(firstTab.read('school-a', fallback).density, 'compact');

  values.set('opensigan-display:school-a', JSON.stringify({ ...fallback, density: 'relaxed' }));
  firstTab.markSaved('school-a');
  values.clear();
  assert.equal(firstTab.syncFromStorage('school-a', fallback).density, 'normal');
});

test('missing and malformed class storage keeps the disabled default or last valid draft', () => {
  const fallback = helpers.defaultDisplaySettings();
  const values = new Map();
  const prefs = helpers.createClassDisplayPreferences(() => ({
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }));
  const missingKey = 'opensigan-class-display:school-a:1:1';
  assert.equal(prefs.read(missingKey, fallback).enabled, false);

  const saved = { ...fallback, density: 'compact' };
  prefs.set(missingKey, saved);
  values.set(missingKey, '{invalid');
  assert.equal(prefs.syncFromStorage(missingKey).settings.density, 'compact');
});

test('restoring class settings updates the draft only after persistent storage succeeds', () => {
  const fallback = helpers.defaultDisplaySettings();
  const previous = { ...fallback, showTeachers: false };
  const restored = { ...fallback, density: 'compact' };
  let blocked = true;
  const values = new Map();
  const prefs = helpers.createClassDisplayPreferences(() => ({
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { if (blocked) throw new Error('blocked'); values.set(key, value); },
    removeItem: (key) => values.delete(key),
  }));
  prefs.set('school:1:1', previous);
  assert.throws(() => prefs.restore('school:1:1', restored));
  assert.equal(prefs.read('school:1:1', fallback).settings, previous);
  blocked = false;
  prefs.restore('school:1:1', restored);
  assert.equal(prefs.read('school:1:1', fallback).settings.density, 'compact');
  assert.equal(JSON.parse(values.get('school:1:1')).density, 'compact');
});
