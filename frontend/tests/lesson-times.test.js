import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/lesson-times.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const exports = {};
runInNewContext(compiled, { exports, Intl });
const { dailyLessonOverview, parseLessonTimes, koreaClockMinutes, calculateLessonTimes, lessonTimesForDate, applySourceLessonStarts, parseSourceLessonPreference } = exports;

test('원본 시작 시각은 유효한 빈 교시에만 기본 적용하고 교체 가능한 자동값만 갱신한다', () => {
  const manual = { 1: { start: '08:50', end: '09:40' }, 2: { start: '09:50', end: '' } };
  const result = applySourceLessonStarts(manual, { 1: '09:00', 2: '10:00', 3: '25:00', 4: '10:30' }, [1, 2, 3, 4]);
  assert.equal(result[1].start, '08:50');
  assert.equal(result[2].start, '09:50');
  assert.deepEqual(JSON.parse(JSON.stringify(result[4])), { start: '10:30', end: '' });
  const refreshed = applySourceLessonStarts({ 1: { start: '09:00', end: '' } }, { 1: '09:10' }, [1], [1]);
  assert.deepEqual(JSON.parse(JSON.stringify(refreshed[1])), { start: '09:10', end: '' });
  assert.equal(parseSourceLessonPreference({ enabled: false, applied: { 1: '09:10', 21: '09:20', 2: '25:00' } }).enabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(parseSourceLessonPreference({ enabled: false, applied: { 1: '09:10', 21: '09:20', 2: '25:00' } }).applied)), { 1: '09:10' });
  const previous = parseSourceLessonPreference({ applied: { 1: '09:10' }, previous: { 1: { start: '08:30', end: '09:20' }, 2: { start: '08:30', end: '' } } }).previous;
  assert.deepEqual(JSON.parse(JSON.stringify(previous)), { 1: { start: '08:30', end: '09:20' } });
  assert.deepEqual(JSON.parse(JSON.stringify(parseSourceLessonPreference({ applied: { 1: '09:10' } }).previous)), {});
  assert.equal(parseSourceLessonPreference(null).enabled, true);
});

test('draft validation identifies missing, reversed and overlapping times including weekday overrides', () => {
  const validate = exports.validateLessonTimeDrafts;
  const common = { 1: { start: '09:00', end: '09:50' }, 2: { start: '10:00', end: '10:50' } };
  assert.equal(validate(common, {}), null);
  assert.match(validate({ 1: { start: '09:00', end: '' } }, {}).message, /모두 입력/);
  assert.match(validate({ 1: { start: '10:00', end: '09:00' } }, {}).message, /늦어야/);
  assert.equal(validate({ ...common, 2: { start: '09:40', end: '10:50' } }, {}).period, 2);
  const error = validate(common, { 2: { 1: { start: '09:30', end: '10:10' } } });
  assert.equal(error.day, 2);
  assert.equal(error.period, 1);
  assert.match(error.message, /화요일.*겹치/);
});

const records = [
  { date: '2026-11-16', grade: 1, class: 1, period: 1, subject: '국어', isChanged: false },
  { date: '2026-11-16', grade: 1, class: 1, period: 2, subject: '수학', isChanged: true },
  { date: '2026-11-16', grade: 1, class: 1, period: 2, subject: '과학', isChanged: true },
  { date: '2026-11-16', grade: 1, class: 1, period: 3, subject: '영어', isChanged: false },
];
const times = { 1: { start: '09:00', end: '09:50' }, 2: { start: '10:00', end: '10:50' }, 3: { start: '13:00', end: '13:50' } };

test('completed periods are distinct, boundary-aware, and unavailable without verified times', () => {
  assert.deepEqual(Array.from(dailyLessonOverview(records, times, 10 * 60 + 20, true).completed), [1]);
  assert.deepEqual(Array.from(dailyLessonOverview(records, times, 10 * 60 + 50, true).completed), [1, 2]);
  assert.deepEqual(Array.from(dailyLessonOverview(records, times, 14 * 60, true).completed), [1, 2, 3]);
  assert.equal(dailyLessonOverview(records, { 1: times[1] }, 14 * 60, true).completed.length, 0);
  assert.equal(dailyLessonOverview(records, times, 14 * 60, false).completed.length, 0);
});

test('교시별 수업 시각은 형식·선후·중복을 검증해 로드한다', () => {
  assert.equal(Object.keys(parseLessonTimes({ ...times, 4: { start: '25:00', end: '26:00' } })).length, 3);
  assert.equal(Object.keys(parseLessonTimes({ ...times, 2: { start: '09:30', end: '10:00' } })).length, 0);
  assert.equal(Object.keys(parseLessonTimes({ 1: { start: '10:00', end: '10:50' }, 2: { start: '09:00', end: '09:50' } })).length, 0);
  assert.equal(Object.keys(parseLessonTimes({ 1: { start: '09:50', end: '09:00' } })).length, 0);
  assert.equal(Object.keys(parseLessonTimes(null)).length, 0);
});

test('진행 중, 쉬는 시간, 수업 종료 시 다음 교시와 잔여 교시를 올바르게 계산한다', () => {
  const during = dailyLessonOverview(records, times, 10 * 60 + 20, true);
  assert.equal(during.current.period, 2);
  assert.equal(during.current.lessons.length, 2);
  assert.equal(during.next.period, 3);
  assert.equal(during.changed, 1);
  assert.equal(during.remaining, 2);
  const breakTime = dailyLessonOverview(records, times, 12 * 60, true);
  assert.equal(breakTime.current, null);
  assert.equal(breakTime.next.period, 3);
  assert.equal(breakTime.remaining, 1);
  const after = dailyLessonOverview(records, times, 14 * 60, true);
  assert.equal(after.next, null);
  assert.equal(after.remaining, 0);
});

test('설정이 없거나 오늘이 아닌 경우 현재 수업을 추정하지 않는다', () => {
  const partial = dailyLessonOverview(records, { 1: times[1] }, 10 * 60, true);
  assert.equal(partial.timed, false);
  assert.equal(partial.total, 3);
  assert.equal(partial.remaining, null);
  assert.equal(dailyLessonOverview(records, times, 10 * 60, false).current, null);
});

test('한국 시간대의 시각으로 현재 교시를 계산한다', () => {
  assert.equal(koreaClockMinutes(new Date('2026-11-16T01:20:00Z')), 10 * 60 + 20);
});

test('요일별 예외는 해당 날짜에만 공통 교시 시각보다 우선한다', () => {
  const weekdays = { 2: { 1: { start: '08:30', end: '09:20' } } };
  assert.equal(lessonTimesForDate(times, weekdays, '2026-11-09')[1].start, '09:00');
  assert.equal(lessonTimesForDate(times, weekdays, '2026-11-10')[1].start, '08:30');
  assert.equal(lessonTimesForDate(times, weekdays, '2026-11-10')[2].start, '10:00');
});

test('원본 시작 시각은 날짜별 실제 표시 기본값으로 쓰되 종료 시각이 없으면 계산하지 않는다', () => {
  const sourceOnly = lessonTimesForDate({}, {}, '2026-11-09', { 1: '09:00', 2: '10:00' });
  assert.equal(sourceOnly[1].start, '09:00');
  assert.equal(sourceOnly[1].end, '');
  assert.equal(dailyLessonOverview(records, sourceOnly, 10 * 60, true).timed, false);
  const overridden = lessonTimesForDate({ 1: times[1] }, { 2: { 1: { start: '08:30', end: '09:20' } } }, '2026-11-10', { 1: '09:00', 2: '10:00' });
  assert.equal(overridden[1].start, '08:30');
  assert.equal(overridden[2].start, '10:00');
});

test('교시 규칙은 점심에 기본 쉬는 시간을 더하지 않고 입력과 하루 범위를 검증한다', () => {
  const result = calculateLessonTimes('08:15', '50', '10', '4', '60', 6);
  assert.equal(result[4].end, '12:05');
  assert.equal(result[5].start, '13:05');
  assert.equal(result[6].start, '14:05');
  assert.equal(calculateLessonTimes('08:15', '50', '10', '', '', 2)[2].start, '09:15');
  for (const values of [
    ['', '50', '10', '', '', 8], ['08:15', '', '10', '', '', 8],
    ['08:15', '50', '-1', '', '', 8], ['08:15', '50', '10', '4', '', 8],
    ['08:15', '50', '10', '8', '60', 8], ['23:00', '60', '0', '', '', 1],
    ['08:15', '50', '10', '', '', 21],
  ]) assert.equal(calculateLessonTimes(...values), null);
});
