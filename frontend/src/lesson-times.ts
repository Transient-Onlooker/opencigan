import type { TimetableRecord } from './api';

export type LessonTimes = Record<number, { start: string; end: string }>;
export type WeekdayLessonTimes = Record<number, LessonTimes>;

export function lessonTimesForDate(common: LessonTimes, weekdays: WeekdayLessonTimes, date: string): LessonTimes {
  const weekday = new Date(`${date}T00:00:00Z`).getUTCDay() || 7;
  return { ...common, ...(weekdays[weekday] ?? {}) };
}

function minutes(value: string): number | null {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value)) return null;
  const [hours, part] = value.split(':').map(Number);
  return hours * 60 + part;
}

export function validateLessonTimeDrafts(common: LessonTimes, weekdays: WeekdayLessonTimes): { day: number; period: number; message: string } | null {
  const validate = (entries: LessonTimes, day: number, overrides?: LessonTimes) => {
    const ordered = Object.entries(entries).map(([period, entry]) => ({ period: Number(period), ...entry })).sort((a, b) => a.period - b.period);
    let previous: typeof ordered[number] | undefined;
    for (const entry of ordered) {
      if (!entry.start && !entry.end && !overrides) continue;
      if (!entry.start || !entry.end || minutes(entry.start) === null || minutes(entry.end) === null) return { day, period: entry.period, message: `${entry.period}교시 시작과 종료 시각을 모두 입력해 주세요.` };
      if (entry.start >= entry.end) return { day, period: entry.period, message: `${entry.period}교시 종료 시각은 시작 시각보다 늦어야 해요.` };
      if (previous && entry.start < previous.end) {
        const period = overrides && !overrides[entry.period] && overrides[previous.period] ? previous.period : entry.period;
        return { day, period, message: `${previous.period}교시와 ${entry.period}교시 시각이 겹치거나 순서가 맞지 않아요.` };
      }
      previous = entry;
    }
    return null;
  };
  const commonError = validate(common, 0);
  if (commonError) return commonError;
  const actual = Object.fromEntries(Object.entries(common).filter(([, entry]) => entry.start || entry.end));
  for (const [day, overrides] of Object.entries(weekdays)) {
    const error = validate({ ...actual, ...overrides }, Number(day), overrides);
    if (error) return { ...error, message: `${['', '월', '화', '수', '목', '금', '토', '일'][Number(day)]}요일 ${error.message}` };
  }
  return null;
}

export function calculateLessonTimes(start: string, duration: string, breakMinutes: string, lunchAfter: string, lunchMinutes: string, count: number): LessonTimes | null {
  const initial = minutes(start);
  if (initial === null || !/^\d+$/.test(duration) || !/^\d+$/.test(breakMinutes) || !Number.isInteger(count) || count < 1 || count > 20) return null;
  const lesson = Number(duration), pause = Number(breakMinutes);
  if (lesson < 1 || lesson > 1440 || pause > 1440) return null;
  const hasLunch = lunchAfter !== '';
  if (hasLunch && (!/^\d+$/.test(lunchAfter) || !/^\d+$/.test(lunchMinutes) || Number(lunchAfter) < 1 || Number(lunchAfter) >= count || Number(lunchMinutes) > 1440)) return null;
  const format = (value: number) => `${String(Math.floor(value / 60)).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`;
  const result: LessonTimes = {};
  let current = initial;
  for (let period = 1; period <= count; period++) {
    const end = current + lesson;
    if (end >= 1440) return null;
    result[period] = { start: format(current), end: format(end) };
    current = end + (hasLunch && period === Number(lunchAfter) ? Number(lunchMinutes) : pause);
  }
  return result;
}

export function parseLessonTimes(value: unknown): LessonTimes {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const result: LessonTimes = {};
  for (const [rawPeriod, rawEntry] of Object.entries(value)) {
    const period = Number(rawPeriod);
    if (!Number.isInteger(period) || period < 1 || period > 20 || !rawEntry || typeof rawEntry !== 'object') continue;
    const entry = rawEntry as { start?: unknown; end?: unknown };
    if (typeof entry.start !== 'string' || typeof entry.end !== 'string') continue;
    const start = minutes(entry.start);
    const end = minutes(entry.end);
    if (start === null || end === null || start >= end) continue;
    result[period] = { start: entry.start, end: entry.end };
  }
  const ordered = Object.entries(result).sort(([a], [b]) => Number(a) - Number(b)).map(([, entry]) => entry);
  if (ordered.some((entry, index) => index > 0 && entry.start < ordered[index - 1].end)) return {};
  return result;
}

export function parseWeekdayLessonTimes(value: unknown, common: LessonTimes): WeekdayLessonTimes | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const result: WeekdayLessonTimes = {};
  for (const [rawDay, rawEntries] of Object.entries(value)) {
    if (!/^[1-7]$/.test(rawDay) || !rawEntries || typeof rawEntries !== 'object' || Array.isArray(rawEntries)) return null;
    const entries = parseLessonTimes(rawEntries);
    if (Object.keys(entries).length !== Object.keys(rawEntries).length) return null;
    const combined = { ...common, ...entries };
    if (Object.keys(parseLessonTimes(combined)).length !== Object.keys(combined).length) return null;
    if (Object.keys(entries).length) result[Number(rawDay)] = entries;
  }
  return result;
}

export function koreaClockMinutes(now: Date): number {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(now);
  const getPart = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? 0);
  return getPart('hour') * 60 + getPart('minute');
}

export function dailyLessonOverview(records: TimetableRecord[], times: LessonTimes, nowMinute: number, isToday: boolean) {
  const groups = new Map<number, TimetableRecord[]>();
  for (const record of records) {
    const period = Number(record.period);
    if (!Number.isInteger(period) || period < 1) continue;
    groups.set(period, [...(groups.get(period) ?? []), record]);
  }
  const periods = [...groups.keys()].sort((a, b) => a - b);
  const changed = periods.filter((period) => groups.get(period)?.some((record) => record.isChanged)).length;
  const hasTimes = isToday && periods.length > 0 && periods.every((period) => {
    const entry = times[period];
    return entry && minutes(entry.start) !== null && minutes(entry.end) !== null;
  });
  if (!hasTimes) return { total: periods.length, changed, timed: false, current: null, next: null, remaining: null, completed: [] as number[] };
  const current = periods.find((period) => minutes(times[period].start)! <= nowMinute && nowMinute < minutes(times[period].end)!);
  const next = periods.find((period) => minutes(times[period].start)! > nowMinute);
  const remaining = periods.filter((period) => minutes(times[period].end)! > nowMinute).length;
  const completed = periods.filter((period) => minutes(times[period].end)! <= nowMinute);
  const label = (period: number | undefined) => period === undefined ? null : ({ period, lessons: groups.get(period) ?? [], time: times[period] });
  return { total: periods.length, changed, timed: true, current: label(current), next: label(next), remaining, completed };
}
