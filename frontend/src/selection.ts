import type { School, TimetableRecord, TimetableResponse } from './api';

/** A shared link may select only a fresh search result with matching identity. */
export function verifiedSharedSchool(shared: School, results: School[], stale: boolean): School | undefined {
  if (stale) return undefined;
  return results.find((candidate) => candidate.id === shared.id && candidate.name === shared.name && candidate.region === shared.region);
}

export function saveSelection(storage: Pick<Storage, 'setItem'>, school: School, grade: number, classroom: number): void {
  try {
    storage.setItem('opensigan-school', JSON.stringify(school));
    storage.setItem('opensigan-grade', String(grade));
    storage.setItem('opensigan-class', String(classroom));
  } catch { /* Storage may be unavailable; the current selection remains usable. */ }
}

export function saveGradeAndClass(storage: Pick<Storage, 'setItem'>, grade: number, classroom: number): void {
  try {
    storage.setItem('opensigan-grade', String(grade));
    storage.setItem('opensigan-class', String(classroom));
  } catch { /* Keep the current in-memory selection if storage is unavailable. */ }
}

export function saveClassToStorage(storage: Pick<Storage, 'setItem'>, classroom: number): void {
  try { storage.setItem('opensigan-class', String(classroom)); }
  catch { /* Keep the current in-memory selection if storage is unavailable. */ }
}

export function validateSharedClass(timetable: TimetableResponse | null, fromDevice: boolean, maxGrade: number, grade: number, classroom: number): 'valid' | 'missing' | 'unavailable' {
  const records: TimetableRecord[] = timetable?.records ?? [];
  if (!timetable || timetable.stale || fromDevice || !records.length) return 'unavailable';
  if (grade < 1 || grade > maxGrade || !records.some((record) => Number(record.grade) === grade && Number(record.class) === classroom)) return 'missing';
  return 'valid';
}

export type PendingSharedClass = {
  schoolId: string;
  grade: number;
  classroom: number;
  fallback: { school: School | null; grade: number; classroom: number };
};

export function createSharedSelectionSession(onChange: (state: { checking: boolean; pending: PendingSharedClass | null }) => void) {
  let request: AbortController | undefined;
  let checking = false;
  let pending: PendingSharedClass | null = null;
  const publish = () => onChange({ checking, pending });
  return {
    begin() {
      request?.abort();
      request = new AbortController();
      checking = true;
      pending = null;
      publish();
      return request.signal;
    },
    setPending(value: PendingSharedClass) { pending = value; publish(); },
    consume() { const value = pending; pending = null; publish(); return value; },
    finish(signal: AbortSignal) {
      if (request?.signal !== signal || signal.aborted) return;
      checking = false;
      publish();
    },
    cancel() {
      request?.abort();
      request = undefined;
      checking = false;
      pending = null;
      publish();
    },
  };
}

export function resolveSharedClass(pending: PendingSharedClass, timetable: TimetableResponse | null, fromDevice: boolean, maxGrade: number) {
  const validation = validateSharedClass(timetable, fromDevice, maxGrade, pending.grade, pending.classroom);
  if (validation === 'valid') return { status: 'committed' as const, grade: pending.grade, classroom: pending.classroom };
  return { status: 'rolled-back' as const, reason: validation, fallback: pending.fallback };
}

export function gradesInTimetable(records: TimetableRecord[], maxGrade: number): number[] {
  return [...new Set(records.map((record) => Number(record.grade))
    .filter((value) => Number.isInteger(value) && value >= 1 && value <= maxGrade))].sort((a, b) => a - b);
}

export function classesInGrade(records: TimetableRecord[], grade: number): number[] {
  return [...new Set(records.filter((record) => Number(record.grade) === Number(grade))
    .map((record) => Number(record.class)).filter((value) => Number.isInteger(value) && value > 0))].sort((a, b) => a - b);
}

export function reconcileClassSelection(records: TimetableRecord[], maxGrade: number, grade: number, classroom: number) {
  const grades = gradesInTimetable(records, maxGrade);
  const nextGrade = grades.length && !grades.includes(Number(grade)) ? grades[0] : grade;
  const classes = classesInGrade(records, nextGrade);
  const nextClassroom = classes.length && !classes.includes(Number(classroom)) ? classes[0] : classroom;
  return { grade: nextGrade, classroom: nextClassroom };
}
