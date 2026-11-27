import type { School } from './api';
import type { SelectionState } from './selection';

export function saveSelection(storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>, selection: { school?: School; grade?: number; classroom: number }): void {
  const entries: [string, string][] = [];
  if (selection.school) entries.push(['opensigan-school', JSON.stringify(selection.school)]);
  if (selection.grade !== undefined) entries.push(['opensigan-grade', String(selection.grade)]);
  entries.push(['opensigan-class', String(selection.classroom)]);
  const previous: [string, string | null][] = [];
  let written = 0;
  try {
    for (const [key] of entries) previous.push([key, storage.getItem(key)]);
    for (const [key, value] of entries) { storage.setItem(key, value); written += 1; }
  } catch {
    // A different tab may have completed a selection using the same school value.
    // Avoid restoring any part of our snapshot if another field has changed.
    try {
      if (previous.length === entries.length && entries.some(([key, value], index) =>
        storage.getItem(key) !== (index < written ? value : previous[index][1]))) return;
    } catch { return; }
    for (let index = written - 1; index >= 0; index -= 1) {
      const [key, value] = previous[index];
      try {
        if (storage.getItem(key) !== entries[index][1]) continue;
        if (value === null) storage.removeItem(key); else storage.setItem(key, value);
      }
      catch { /* Storage can reject the rollback too. */ }
    }
  }
}

export function readSelection(storage: Pick<Storage, 'getItem'>, update: (change: Partial<SelectionState>) => void): School | null {
  const grade = Number(storage.getItem('opensigan-grade'));
  if (Number.isInteger(grade) && grade >= 1 && grade <= 6) update({ grade });
  const classroom = Number(storage.getItem('opensigan-class'));
  if (Number.isInteger(classroom) && classroom >= 1 && classroom <= 99) update({ classroom });
  const rawSchool = storage.getItem('opensigan-school');
  if (!rawSchool) return null;
  const parsed: unknown = JSON.parse(rawSchool);
  if (typeof parsed !== 'object' || parsed === null) return null;
  const { id, name, region } = parsed as Record<string, unknown>;
  // Match the school identity contract used by history and shared links.
  if (typeof id !== 'string' || !/^[0-9]+:[^:]{1,50}$/.test(id) || id.length > 100 ||
      typeof name !== 'string' || !name.trim() || name.length > 50 ||
      typeof region !== 'string' || region.length > 100) return null;
  return { id, name, region };
}
