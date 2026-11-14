import type { School } from './api';
import { addDays, clampWeek, monday } from './date';

export type NavigationView = 'timetable' | 'meals' | 'settings';
export type TimetableViewMode = 'today' | 'week' | 'grade' | 'teacher';

export interface NavigationState {
  version: 1;
  view: NavigationView;
  timetableView: TimetableViewMode;
  school: School | null;
  grade: number;
  classroom: number;
  week: string;
  selectedDay: string;
  mealDate: string;
}

export interface NavigationHistoryWindow {
  history: {
    state: unknown;
    pushState(data: any, unused: string, url?: string | URL | null): void;
    replaceState(data: any, unused: string, url?: string | URL | null): void;
  };
  addEventListener(type: string, listener: (event: any) => void): void;
  removeEventListener(type: string, listener: (event: any) => void): void;
}

const STATE_KEY = 'opensigan';

function isValidIsoDate(value: string, minYear = 1900, maxYear = 9999): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (year < minYear || year > maxYear) return false;
  const date = new Date(0);
  date.setUTCHours(0, 0, 0, 0);
  date.setUTCFullYear(year, month - 1, day);
  return (
    date.getUTCFullYear() === year &&
    date.getUTCMonth() === month - 1 &&
    date.getUTCDate() === day
  );
}

function isValidSchool(value: unknown): value is School {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.id !== 'string' ||
    typeof candidate.name !== 'string' ||
    typeof candidate.region !== 'string'
  ) {
    return false;
  }
  if (!/^[0-9]+:[^:]{1,50}$/.test(candidate.id) || candidate.id.length > 100) return false;
  if (!candidate.name.trim() || candidate.name.length > 50) return false;
  if (candidate.region.length > 100) return false;
  return true;
}

export function parseNavigationState(
  value: unknown,
  currentMonday: string
): NavigationState | null {
  if (typeof value !== 'object' || value === null) return null;
  const obj = value as Record<string, unknown>;

  if (obj.version !== 1) return null;

  if (obj.view !== 'timetable' && obj.view !== 'meals' && obj.view !== 'settings') {
    return null;
  }

  if (
    obj.timetableView !== 'today' &&
    obj.timetableView !== 'week' &&
    obj.timetableView !== 'grade' &&
    obj.timetableView !== 'teacher'
  ) {
    return null;
  }

  let school: School | null = null;
  if (obj.school !== null) {
    if (!isValidSchool(obj.school)) return null;
    school = {
      id: obj.school.id,
      name: obj.school.name,
      region: obj.school.region,
    };
  }

  if (
    typeof obj.grade !== 'number' ||
    !Number.isInteger(obj.grade) ||
    obj.grade < 1 ||
    obj.grade > 6
  ) {
    return null;
  }

  if (
    typeof obj.classroom !== 'number' ||
    !Number.isInteger(obj.classroom) ||
    obj.classroom < 1 ||
    obj.classroom > 99
  ) {
    return null;
  }

  if (typeof obj.week !== 'string' || !isValidIsoDate(obj.week)) return null;
  if (monday(obj.week) !== obj.week) return null;
  if (clampWeek(obj.week, currentMonday) !== obj.week) return null;

  if (typeof obj.selectedDay !== 'string' || !isValidIsoDate(obj.selectedDay)) return null;
  const weekStart = obj.week;
  const weekEnd = addDays(weekStart, 6);
  if (obj.selectedDay < weekStart || obj.selectedDay > weekEnd) return null;

  if (typeof obj.mealDate !== 'string' || !isValidIsoDate(obj.mealDate, 1900, 9999)) {
    return null;
  }

  return {
    version: 1,
    view: obj.view,
    timetableView: obj.timetableView,
    school,
    grade: obj.grade,
    classroom: obj.classroom,
    week: obj.week,
    selectedDay: obj.selectedDay,
    mealDate: obj.mealDate,
  };
}

export function areNavigationStatesEqual(
  a: NavigationState | null | undefined,
  b: NavigationState | null | undefined
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (
    a.version !== b.version ||
    a.view !== b.view ||
    a.timetableView !== b.timetableView ||
    a.grade !== b.grade ||
    a.classroom !== b.classroom ||
    a.week !== b.week ||
    a.selectedDay !== b.selectedDay ||
    a.mealDate !== b.mealDate
  ) {
    return false;
  }
  if (a.school === b.school) return true;
  if (!a.school || !b.school) return false;
  return (
    a.school.id === b.school.id &&
    a.school.name === b.school.name &&
    a.school.region === b.school.region
  );
}

function resolveWindow(win?: NavigationHistoryWindow): NavigationHistoryWindow | undefined {
  if (win) return win;
  if (typeof window !== 'undefined') {
    return window as unknown as NavigationHistoryWindow;
  }
  return undefined;
}

export function getNavigationFromHistory(
  currentMonday: string,
  win?: NavigationHistoryWindow
): NavigationState | null {
  const target = resolveWindow(win);
  if (!target || !target.history) return null;
  const historyState = target.history.state;
  if (typeof historyState !== 'object' || historyState === null) return null;
  const rawOpensigan = (historyState as Record<string, unknown>)[STATE_KEY];
  return parseNavigationState(rawOpensigan, currentMonday);
}

function prepareHistoryStateObject(
  currentHistoryState: unknown,
  navState: NavigationState
): Record<string, unknown> {
  const base =
    typeof currentHistoryState === 'object' && currentHistoryState !== null
      ? { ...(currentHistoryState as Record<string, unknown>) }
      : {};
  base[STATE_KEY] = {
    version: 1,
    view: navState.view,
    timetableView: navState.timetableView,
    school: navState.school
      ? {
          id: navState.school.id,
          name: navState.school.name,
          region: navState.school.region,
        }
      : null,
    grade: navState.grade,
    classroom: navState.classroom,
    week: navState.week,
    selectedDay: navState.selectedDay,
    mealDate: navState.mealDate,
  };
  return base;
}

export function replaceNavigationState(
  state: NavigationState,
  win?: NavigationHistoryWindow
): boolean {
  const target = resolveWindow(win);
  if (!target || !target.history) return false;
  const nextHistoryState = prepareHistoryStateObject(target.history.state, state);
  target.history.replaceState(nextHistoryState, '');
  return true;
}

export function pushNavigationState(
  state: NavigationState,
  currentMonday: string,
  win?: NavigationHistoryWindow
): boolean {
  const target = resolveWindow(win);
  if (!target || !target.history) return false;

  const currentNav = getNavigationFromHistory(currentMonday, target);
  if (areNavigationStatesEqual(currentNav, state)) {
    return false;
  }

  const nextHistoryState = prepareHistoryStateObject(target.history.state, state);
  target.history.pushState(nextHistoryState, '');
  return true;
}

export function subscribeNavigation(
  currentMonday: string,
  callback: (state: NavigationState | null) => void,
  win?: NavigationHistoryWindow
): () => void {
  const target = resolveWindow(win);
  if (!target || typeof target.addEventListener !== 'function') {
    return () => {};
  }

  const listener = (event: any) => {
    let rawOpensigan: unknown = null;
    const evState = event?.state;
    if (typeof evState === 'object' && evState !== null && STATE_KEY in evState) {
      rawOpensigan = evState[STATE_KEY];
    } else if (
      typeof target.history?.state === 'object' &&
      target.history.state !== null &&
      STATE_KEY in (target.history.state as Record<string, unknown>)
    ) {
      rawOpensigan = (target.history.state as Record<string, unknown>)[STATE_KEY];
    }
    const parsed = parseNavigationState(rawOpensigan, currentMonday);
    callback(parsed);
  };

  target.addEventListener('popstate', listener);
  return () => {
    target.removeEventListener('popstate', listener);
  };
}

