import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const dateSource = await readFile(new URL('../src/date.ts', import.meta.url), 'utf8');
const dateContext = { exports: {} };
runInNewContext(ts.transpile(dateSource, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), dateContext);
const { addDays, monday, clampWeek } = dateContext.exports;

const navSource = await readFile(new URL('../src/navigation.ts', import.meta.url), 'utf8');
const navContext = {
  exports: {},
  require: (id) => {
    if (id === './date') return { addDays, monday, clampWeek };
    if (id === './api') return {};
    throw new Error('Unknown module ' + id);
  }
};
runInNewContext(ts.transpile(navSource, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), navContext);
const {
  parseNavigationState,
  areNavigationStatesEqual,
  getNavigationFromHistory,
  replaceNavigationState,
  pushNavigationState,
  subscribeNavigation
} = navContext.exports;

function createFakeWindow(initialHistoryState = null) {
  const listeners = { popstate: [] };
  const history = {
    state: initialHistoryState,
    pushCount: 0,
    replaceCount: 0,
    pushState(data) {
      this.pushCount++;
      this.state = JSON.parse(JSON.stringify(data));
    },
    replaceState(data) {
      this.replaceCount++;
      this.state = JSON.parse(JSON.stringify(data));
    }
  };
  return {
    history,
    addEventListener(type, fn) {
      if (!listeners[type]) listeners[type] = [];
      listeners[type].push(fn);
    },
    removeEventListener(type, fn) {
      if (!listeners[type]) return;
      listeners[type] = listeners[type].filter(l => l !== fn);
    },
    dispatchPopState(state) {
      if (state !== undefined) {
        history.state = state;
      }
      for (const fn of [...(listeners.popstate || [])]) {
        fn({ state: history.state });
      }
    }
  };
}

const currentMonday = '2026-11-09';
const validSchool = { id: '123:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
const validState = {
  version: 1,
  view: 'timetable',
  timetableView: 'week',
  school: validSchool,
  grade: 2,
  classroom: 7,
  week: '2026-11-09',
  selectedDay: '2026-11-10',
  mealDate: '2026-11-10'
};

test('teacher selection is restored and edits replace the current history entry', () => {
  const win = createFakeWindow();
  const first = { ...validState, timetableView: 'teacher', teacherQuery: '김교사' };
  replaceNavigationState(first, win);
  assert.equal(getNavigationFromHistory(currentMonday, win).teacherQuery, '김교사');
  pushNavigationState({ ...first, teacherQuery: '이교사' }, currentMonday, win);
  assert.equal(win.history.pushCount, 0);
  assert.equal(win.history.state.opensigan.teacherQuery, '이교사');
  assert.equal(parseNavigationState({ ...first, teacherQuery: 'x'.repeat(101) }, currentMonday), null);
});

test('parseNavigationState parses valid navigation state', () => {
  const parsed = parseNavigationState(validState, currentMonday);
  assert.deepEqual(JSON.parse(JSON.stringify(parsed)), validState);

  const withoutSchool = { ...validState, school: null };
  assert.deepEqual(JSON.parse(JSON.stringify(parseNavigationState(withoutSchool, currentMonday))), withoutSchool);
});

test('parseNavigationState validates version, view, timetableView, grade, and classroom', () => {
  assert.equal(parseNavigationState({ ...validState, version: 2 }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, view: 'other' }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, timetableView: 'month' }, currentMonday), null);

  assert.equal(parseNavigationState({ ...validState, grade: 0 }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, grade: 7 }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, grade: 1.5 }, currentMonday), null);

  assert.equal(parseNavigationState({ ...validState, classroom: 0 }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, classroom: 100 }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, classroom: '7' }, currentMonday), null);
});

test('parseNavigationState validates week, selectedDay, and mealDate bounds', () => {
  // week must be valid ISO Monday and within clampWeek (current or next monday)
  assert.equal(parseNavigationState({ ...validState, week: '2026-11-10' }, currentMonday), null); // Tuesday
  assert.equal(parseNavigationState({ ...validState, week: '2026-11-02' }, currentMonday), null); // Previous week
  assert.equal(parseNavigationState({ ...validState, week: '2026-11-23' }, currentMonday), null); // Two weeks later

  // selectedDay must be within week (Monday..Sunday)
  assert.equal(parseNavigationState({ ...validState, selectedDay: '2026-11-08' }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, selectedDay: '2026-11-16' }, currentMonday), null);
  assert.ok(parseNavigationState({ ...validState, selectedDay: '2026-11-15' }, currentMonday)); // Sunday is ok

  // mealDate must be valid ISO 1900..9999
  assert.equal(parseNavigationState({ ...validState, mealDate: '1899-12-31' }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, mealDate: '2026-02-29' }, currentMonday), null);
  assert.ok(parseNavigationState({ ...validState, mealDate: '2024-02-29' }, currentMonday));
  assert.ok(parseNavigationState({ ...validState, mealDate: '9999-12-31' }, currentMonday));
});

test('parseNavigationState validates school object structure and prevents injection', () => {
  assert.equal(parseNavigationState({ ...validState, school: 'not-an-object' }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, school: { id: 'invalid', name: 'A', region: 'B' } }, currentMonday), null);
  assert.equal(parseNavigationState({ ...validState, school: { id: '123:school', name: '   ', region: 'B' } }, currentMonday), null);
});

test('replaceNavigationState preserves unrelated history.state keys and stores opensigan namespace', () => {
  const fakeWin = createFakeWindow({ userSession: 'abc-123', unrelatedFlag: true });
  const replaced = replaceNavigationState(validState, fakeWin);
  assert.equal(replaced, true);
  assert.equal(fakeWin.history.replaceCount, 1);
  assert.equal(fakeWin.history.state.userSession, 'abc-123');
  assert.equal(fakeWin.history.state.unrelatedFlag, true);
  assert.deepEqual(fakeWin.history.state.opensigan, validState);
});

test('pushNavigationState deduplicates identical state and pushes new state', () => {
  const fakeWin = createFakeWindow({ opensigan: validState, unrelated: 'keep' });
  // Identical push should return false and not call pushState
  const pushedDuplicate = pushNavigationState(validState, currentMonday, fakeWin);
  assert.equal(pushedDuplicate, false);
  assert.equal(fakeWin.history.pushCount, 0);

  // Different state should push and preserve unrelated keys
  const modifiedState = { ...validState, view: 'meals' };
  const pushedNew = pushNavigationState(modifiedState, currentMonday, fakeWin);
  assert.equal(pushedNew, true);
  assert.equal(fakeWin.history.pushCount, 1);
  assert.equal(fakeWin.history.state.unrelated, 'keep');
  assert.deepEqual(fakeWin.history.state.opensigan, modifiedState);

  // Pushing modified again should deduplicate
  const pushedModifiedAgain = pushNavigationState(modifiedState, currentMonday, fakeWin);
  assert.equal(pushedModifiedAgain, false);
  assert.equal(fakeWin.history.pushCount, 1);
});

test('subscribeNavigation receives state on popstate without recursive pushes or mutations', () => {
  const fakeWin = createFakeWindow({ opensigan: validState });
  const received = [];
  const unsubscribe = subscribeNavigation(currentMonday, (state) => {
    received.push(state);
    // Root consumer should be able to check or not trigger push
  }, fakeWin);

  fakeWin.dispatchPopState({ opensigan: { ...validState, view: 'settings' } });
  assert.equal(received.length, 1);
  assert.equal(received[0].view, 'settings');
  assert.equal(fakeWin.history.pushCount, 0);
  assert.equal(fakeWin.history.replaceCount, 0);

  // Popstate with malformed state delivers null
  fakeWin.dispatchPopState({ opensigan: { invalid: true } });
  assert.equal(received.length, 2);
  assert.equal(received[1], null);
  assert.equal(fakeWin.history.pushCount, 0);

  // Popstate with no opensigan key delivers null
  fakeWin.dispatchPopState({});
  assert.equal(received.length, 3);
  assert.equal(received[2], null);

  // Unsubscribe cleans up listener
  unsubscribe();
  fakeWin.dispatchPopState({ opensigan: validState });
  assert.equal(received.length, 3);
});

