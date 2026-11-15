import type { TimetableRecord } from './api';
import { addDays, monday } from './date';

export interface PersonalTimetableEntry {
  id: string;
  weekday: number; // 1 (월) ~ 5 (금)
  period: number;  // 1 ~ 20
  subject: string; // 1 ~ 100자
  teacher?: string; // 최대 60자 (선택)
  date?: string;   // YYYY-MM-DD (선택, 특정 일자 지정 오버라이드)
}

export interface PersonalEvent {
  id: string;
  date: string;    // YYYY-MM-DD
  time?: string;    // HH:MM (선택)
  title: string;   // 1 ~ 100자
  type?: 'event' | 'exam' | 'reminder';
}

export interface PersonalTimetableStore {
  version: 1;
  entries: PersonalTimetableEntry[];
  events: PersonalEvent[];
  updatedAt: string;
}

export const MAX_STORE_ENTRIES = 200;
export const MAX_STORE_BYTES = 256 * 1024;

export function getPersonalStorageKey(schoolId: string, grade: number, classroom: number | string): string {
  const safeSchool = (schoolId || 'unknown').trim();
  const safeGrade = Number(grade) || 1;
  const safeClass = String(classroom ?? '1').trim() || '1';
  return 'personal_timetable_v1:' + safeSchool + ':' + safeGrade + ':' + safeClass;
}

export function createEmptyPersonalStore(): PersonalTimetableStore {
  return {
    version: 1,
    entries: [],
    events: [],
    updatedAt: new Date().toISOString(),
  };
}

function isValidDateString(str: unknown): str is string {
  if (typeof str !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(str)) return false;
  const [y, m, d] = str.split('-').map(Number);
  if (y < 1900) return false;
  if (m < 1 || m > 12 || d < 1 || d > 31) return false;
  const testDate = new Date(str + 'T00:00:00Z');
  return !Number.isNaN(testDate.getTime()) && testDate.toISOString().slice(0, 10) === str;
}

function isValidTimeString(str: unknown): str is string {
  if (typeof str !== 'string' || !/^([01]\d|2[0-3]):[0-5]\d$/.test(str)) return false;
  return true;
}

export function validatePersonalEntry(raw: unknown): PersonalTimetableEntry | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const item = raw as Record<string, unknown>;

  const id = typeof item.id === 'string' && item.id.trim() ? item.id.trim().slice(0, 50) : 'entry_' + Math.random().toString(36).slice(2, 10);
  const weekday = Number(item.weekday);
  if (!Number.isInteger(weekday) || weekday < 1 || weekday > 5) return null;

  const period = Number(item.period);
  if (!Number.isInteger(period) || period < 1 || period > 20) return null;

  if (typeof item.subject !== 'string') return null;
  const subject = item.subject.trim();
  if (!subject || subject.length > 100) return null;

  let teacher: string | undefined = undefined;
  if (typeof item.teacher === 'string') {
    const trimmed = item.teacher.trim();
    if (trimmed.length > 60) return null;
    if (trimmed) teacher = trimmed;
  }

  let date: string | undefined = undefined;
  if (item.date !== undefined && item.date !== null && item.date !== '') {
    if (!isValidDateString(item.date)) return null;
    date = item.date;
  }

  return { id, weekday, period, subject, ...(teacher ? { teacher } : {}), ...(date ? { date } : {}) };
}

export function validatePersonalEvent(raw: unknown): PersonalEvent | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const item = raw as Record<string, unknown>;

  const id = typeof item.id === 'string' && item.id.trim() ? item.id.trim().slice(0, 50) : 'event_' + Math.random().toString(36).slice(2, 10);

  if (!isValidDateString(item.date)) return null;
  const date = item.date;

  let time: string | undefined = undefined;
  if (item.time !== undefined && item.time !== null && item.time !== '') {
    if (!isValidTimeString(item.time)) return null;
    time = item.time;
  }

  if (typeof item.title !== 'string') return null;
  const title = item.title.trim();
  if (!title || title.length > 100) return null;

  let type: "event" | "exam" | "reminder" | undefined = undefined;
  if (item.type === "event" || item.type === "exam" || item.type === "reminder") {
    type = item.type;
  }

  return { id, date, ...(time ? { time } : {}), title, ...(type ? { type } : {}) };
}

export function parsePersonalStore(jsonString: string | null | undefined): PersonalTimetableStore {
  const fallback = createEmptyPersonalStore();
  if (!jsonString || typeof jsonString !== 'string') return fallback;

  if (new Blob([jsonString]).size > MAX_STORE_BYTES) {
    return fallback;
  }

  try {
    const parsed = JSON.parse(jsonString);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return fallback;
    if (parsed.version !== 1) return fallback;

    const entries: PersonalTimetableEntry[] = [];
    if (Array.isArray(parsed.entries)) {
      for (const raw of parsed.entries) {
        if (entries.length >= MAX_STORE_ENTRIES) break;
        const valid = validatePersonalEntry(raw);
        if (valid) entries.push(valid);
      }
    }

    const events: PersonalEvent[] = [];
    if (Array.isArray(parsed.events)) {
      for (const raw of parsed.events) {
        if (events.length >= MAX_STORE_ENTRIES) break;
        const valid = validatePersonalEvent(raw);
        if (valid) events.push(valid);
      }
    }

    return {
      version: 1,
      entries,
      events,
      updatedAt: typeof parsed.updatedAt === 'string' ? parsed.updatedAt : new Date().toISOString(),
    };
  } catch {
    return fallback;
  }
}

export function loadPersonalStore(schoolId: string, grade: number, classroom: number | string): PersonalTimetableStore {
  try {
    if (typeof localStorage === 'undefined') return createEmptyPersonalStore();
    const key = getPersonalStorageKey(schoolId, grade, classroom);
    const data = localStorage.getItem(key);
    return parsePersonalStore(data);
  } catch {
    return createEmptyPersonalStore();
  }
}

export function savePersonalStore(
  schoolId: string,
  grade: number,
  classroom: number | string,
  store: PersonalTimetableStore
): { success: boolean; error?: string } {
  try {
    if (typeof localStorage === 'undefined') {
      return { success: false, error: '로컬 저장소를 사용할 수 없습니다.' };
    }
    const cleanStore: PersonalTimetableStore = {
      version: 1,
      entries: store.entries.slice(0, MAX_STORE_ENTRIES),
      events: store.events.slice(0, MAX_STORE_ENTRIES),
      updatedAt: new Date().toISOString(),
    };
    const serialized = JSON.stringify(cleanStore);
    if (new Blob([serialized]).size > MAX_STORE_BYTES) {
      return { success: false, error: '저장 데이터 크기가 256KB 한도를 초과했습니다.' };
    }
    const key = getPersonalStorageKey(schoolId, grade, classroom);
    localStorage.setItem(key, serialized);
    return { success: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : '저장에 실패했습니다.';
    return { success: false, error: message };
  }
}

export function personalEntriesToTimetableRecords(
  entries: PersonalTimetableEntry[],
  options: {
    week: string;
    grade: number;
    classroom: number | string;
  }
): TimetableRecord[] {
  const mon = monday(options.week);
  const weekDates = [0, 1, 2, 3, 4].map((offset) => addDays(mon, offset));

  const records: TimetableRecord[] = [];

  for (let weekdayIdx = 0; weekdayIdx < 5; weekdayIdx++) {
    const weekday = weekdayIdx + 1;
    const dateStr = weekDates[weekdayIdx];

    const specificEntries = entries.filter((e) => e.date === dateStr);
    const regularEntries = entries.filter((e) => !e.date && e.weekday === weekday);

    const byPeriod = new Map<number, PersonalTimetableEntry>();
    for (const entry of regularEntries) {
      byPeriod.set(entry.period, entry);
    }
    for (const entry of specificEntries) {
      byPeriod.set(entry.period, entry);
    }

    for (const [period, entry] of byPeriod.entries()) {
      records.push({
        grade: Number(options.grade) || 1,
        class: options.classroom ?? 1,
        date: dateStr,
        period,
        subject: entry.subject,
        teacher: entry.teacher ?? null,
        isChanged: false,
      });
    }
  }

  records.sort((a, b) => {
    if (a.date !== b.date) return a.date.localeCompare(b.date);
    return a.period - b.period;
  });

  return records;
}
