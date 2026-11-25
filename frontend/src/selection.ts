import type { School, TimetableRecord, TimetableResponse } from './api';

export type SelectionState = { school: School | null; grade: number; classroom: number; week: string };

export function createSelectionState(initial: SelectionState, onChange: (state: SelectionState) => void) {
  let state = { ...initial };
  const update = (change: Partial<SelectionState>) => {
    state = { ...state, ...change };
    onChange({ ...state });
  };
  return {
    update,
    validClass(value: number, available: number[]) {
      return Number.isInteger(value) && value >= 1 && value <= 99 && (!available.length || available.includes(value));
    },
    commitClass(value: number) { update({ classroom: value }); },
    prepareSchool(school: School, keepClass: boolean, deferGradeAdjustment = false) {
      const reset = state.school?.id !== school.id && !keepClass;
      if (reset) update({ grade: 1, classroom: 1 });
      if (!deferGradeAdjustment && /(?:중학교|고등학교)/.test(school.name) && state.grade > 3) update({ grade: 1 });
      return reset;
    },
    reconcile(records: TimetableRecord[], maxGrade: number) {
      const previousGrade = Number(state.grade);
      const previousClassroom = Number(state.classroom);
      update(reconcileClassSelection(records, maxGrade, state.grade, state.classroom));
      return previousGrade !== Number(state.grade) || previousClassroom !== Number(state.classroom);
    },
    resolveShared(pending: PendingSharedClass, timetable: TimetableResponse | null, fromDevice: boolean, maxGrade: number) {
      const outcome = resolveSharedClass(pending, timetable, fromDevice, maxGrade);
      if (outcome.status === 'committed') update({ grade: outcome.grade, classroom: outcome.classroom });
      else if (outcome.fallback.school) update({ grade: outcome.fallback.grade, classroom: outcome.fallback.classroom });
      return outcome;
    },
  };
}

/** A shared link may select only a fresh search result with matching identity. */
export function verifiedSharedSchool(shared: School, results: School[], stale: boolean): School | undefined {
  if (stale) return undefined;
  return results.find((candidate) => candidate.id === shared.id && candidate.name === shared.name && candidate.region === shared.region);
}

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

export function validateSharedClass(timetable: TimetableResponse | null, fromDevice: boolean, maxGrade: number, grade: number, classroom: number): 'valid' | 'missing' | 'unavailable' {
  const records: TimetableRecord[] = timetable?.records ?? [];
  if (!timetable || timetable.stale || fromDevice || !records.length) return 'unavailable';
  if (grade < 1 || grade > maxGrade || !records.some((record) => Number(record.grade) === grade && Number(record.class) === classroom)) return 'missing';
  return 'valid';
}

export function validateSharedCandidate(timetable: TimetableResponse | null, school: School, week: string, grade: number, classroom: number): boolean {
  const maxGrade = /(?:중학교|고등학교)/.test(school.name) ? 3 : 6;
  return timetable?.schoolId === school.id && timetable.weekStart === week &&
    validateSharedClass(timetable, false, maxGrade, grade, classroom) === 'valid';
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
  const session = {
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
    async verifySchool(
      shared: { school: School; grade: number; classroom: number },
      fallback: PendingSharedClass['fallback'],
      currentSchoolId: () => string | undefined,
      search: (name: string, signal: AbortSignal) => Promise<{ schools: School[]; stale: boolean }>,
      apply: (school: School, signal: AbortSignal) => void | Promise<void>,
      fail: () => void,
    ) {
      const signal = session.begin();
      try {
        const result = await search(shared.school.name, signal);
        if (signal.aborted) return;
        const verified = verifiedSharedSchool(shared.school, result.schools, result.stale);
        if (!verified) { fail(); return; }
        if (currentSchoolId() !== fallback.school?.id) return;
        session.setPending({ schoolId: verified.id, grade: shared.grade, classroom: shared.classroom, fallback });
        await apply(verified, signal);
      } catch {
        if (!signal.aborted) fail();
      } finally {
        session.finish(signal);
      }
    },
  };
  return session;
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
