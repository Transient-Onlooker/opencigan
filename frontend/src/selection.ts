import type { School } from './api';

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
