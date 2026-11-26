import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const dateSource = readFileSync(new URL('../src/date.ts', import.meta.url), 'utf8');
const ptSource = readFileSync(new URL('../src/personal-timetable.ts', import.meta.url), 'utf8');

const combined = dateSource + '\n' + ptSource.replace(/import .*;\s*/g, '');
const compiled = ts.transpileModule(combined, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function getModule(localStorageMock = {}) {
  const sandbox = {
    exports: {},
    localStorage: localStorageMock,
    Blob: globalThis.Blob,
    Array: globalThis.Array,
    Object: globalThis.Object,
    console,
  };
  runInNewContext(compiled, sandbox);
  return sandbox.exports;
}

test('getPersonalStorageKey formats key safely', () => {
  const pt = getModule();
  assert.equal(pt.PERSONAL_STORAGE_PREFIX, 'personal_timetable_v1:');
  assert.equal(pt.getPersonalStorageKey('B10:1234', 2, 3), 'personal_timetable_v1:B10:1234:2:3');
  assert.equal(pt.getPersonalStorageKey('', 0, ''), 'personal_timetable_v1:unknown:1:1');
});

test('validatePersonalEntry accepts valid entry and rejects invalid boundaries', () => {
  const pt = getModule();
  const valid = pt.validatePersonalEntry({
    weekday: 1,
    period: 3,
    subject: '수학 심화',
    teacher: '김선생',
    date: '2026-11-09',
  });
  assert.ok(valid);
  assert.equal(valid.weekday, 1);
  assert.equal(valid.period, 3);
  assert.equal(valid.subject, '수학 심화');
  assert.equal(valid.teacher, '김선생');
  assert.equal(valid.date, '2026-11-09');

  assert.equal(pt.validatePersonalEntry({ weekday: 0, period: 1, subject: '국어' }), null);
  assert.equal(pt.validatePersonalEntry({ weekday: 6, period: 1, subject: '국어' }), null);
  assert.equal(pt.validatePersonalEntry({ weekday: 1, period: 0, subject: '국어' }), null);
  assert.equal(pt.validatePersonalEntry({ weekday: 1, period: 21, subject: '국어' }), null);
  assert.equal(pt.validatePersonalEntry({ weekday: 1, period: 1, subject: '   ' }), null);
  assert.equal(pt.validatePersonalEntry({ weekday: 1, period: 1, subject: 'a'.repeat(101) }), null);
  assert.equal(pt.validatePersonalEntry({ weekday: 1, period: 1, subject: '영어', teacher: 't'.repeat(61) }), null);
  assert.equal(pt.validatePersonalEntry({ weekday: 1, period: 1, subject: '영어', date: '2026-02-30' }), null);
});

test('validatePersonalEvent accepts valid event and rejects invalid', () => {
  const pt = getModule();
  const valid = pt.validatePersonalEvent({
    date: '2026-11-10',
    time: '09:30',
    title: '수행평가 제출',
    type: 'exam',
  });
  assert.ok(valid);
  assert.equal(valid.title, '수행평가 제출');
  assert.equal(valid.type, 'exam');

  assert.equal(pt.validatePersonalEvent({ date: '2026-11-10', time: '25:00', title: '테스트' }), null);
  assert.equal(pt.validatePersonalEvent({ date: '2026-11-10', time: '9:30', title: '테스트' }), null);
  assert.equal(pt.validatePersonalEvent({ date: '2026-11-10', title: '' }), null);
});

test('parsePersonalStore handles malformed json and storage boundaries', () => {
  const pt = getModule();
  assert.deepEqual(JSON.parse(JSON.stringify(pt.parsePersonalStore(null).entries)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(pt.parsePersonalStore('invalid json').entries)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(pt.parsePersonalStore('{"version": 2}').entries)), []);

  const lots = Array.from({ length: 250 }, (_, i) => ({
    weekday: (i % 5) + 1,
    period: (i % 7) + 1,
    subject: `과목 ${i}`,
  }));
  const parsed = pt.parsePersonalStore(JSON.stringify({ version: 1, entries: lots }));
  assert.equal(parsed.entries.length, 200);

  const hugeJson = JSON.stringify({ version: 1, entries: [], filler: 'x'.repeat(300 * 1024) });
  assert.deepEqual(JSON.parse(JSON.stringify(pt.parsePersonalStore(hugeJson).entries)), []);
});

test('loadPersonalStore and savePersonalStore with localStorage integration', () => {
  const storage = {};
  const mockStorage = {
    getItem: (k) => storage[k] ?? null,
    setItem: (k, v) => { storage[k] = String(v); },
  };
  const pt = getModule(mockStorage);

  const initial = pt.loadPersonalStore('sch1', 1, 1);
  assert.equal(initial.entries.length, 0);

  const toSave = {
    version: 1,
    entries: [{ id: 'e1', weekday: 2, period: 4, subject: '물리', teacher: '박선생' }],
    events: [{ id: 'v1', date: '2026-11-12', title: '중간고사', type: 'exam' }],
    updatedAt: '2026-11-09T00:00:00.000Z',
  };
  const res = pt.savePersonalStore('sch1', 1, 1, toSave);
  assert.equal(res.success, true);

  const loaded = pt.loadPersonalStore('sch1', 1, 1);
  assert.equal(loaded.entries.length, 1);
  assert.equal(loaded.entries[0].subject, '물리');
  assert.equal(loaded.events.length, 1);
  assert.equal(loaded.events[0].title, '중간고사');
});

test('personalEntriesToTimetableRecords creates synthetic dates from week correctly', () => {
  const pt = getModule();
  const entries = [
    { id: '1', weekday: 1, period: 1, subject: '국어', teacher: '이선생' },
    { id: '2', weekday: 3, period: 2, subject: '영어' },
    { id: '3', weekday: 1, period: 1, subject: '국어 특별수업', date: '2026-11-09' },
  ];

  const records = pt.personalEntriesToTimetableRecords(entries, {
    week: '2026-11-09',
    grade: 2,
    classroom: 3,
  });

  const mon1 = records.find((r) => r.date === '2026-11-09' && r.period === 1);
  assert.ok(mon1);
  assert.equal(mon1.subject, '국어 특별수업');
  assert.equal(mon1.grade, 2);
  assert.equal(mon1.class, 3);

  const wed2 = records.find((r) => r.date === '2026-11-11' && r.period === 2);
  assert.ok(wed2);
  assert.equal(wed2.subject, '영어');
  assert.equal(wed2.teacher, null);
});

