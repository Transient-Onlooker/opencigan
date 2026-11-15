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

export function gradesInTimetable(records: TimetableRecord[], maxGrade: number): number[] {
  return [...new Set(records.map((record) => Number(record.grade))
    .filter((value) => Number.isInteger(value) && value >= 1 && value <= maxGrade))].sort((a, b) => a - b);
}

export function classesInGrade(records: TimetableRecord[], grade: number): number[] {
  return [...new Set(records.filter((record) => Number(record.grade) === Number(grade))
    .map((record) => Number(record.class)).filter((value) => Number.isInteger(value) && value > 0))].sort((a, b) => a - b);
}
