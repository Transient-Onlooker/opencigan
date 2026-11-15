import { test } from 'node:test';
import assert from 'node:assert/strict';
import { personalizationVm } from './helpers/personalization-vm.js';

test('history session ignores cancelled weeks and appends pages for the active selection', async () => {
  let state;
  let selected = { schoolId: 'school', week: '2026-11-09' };
  const requests = [];
  const fetch = (schoolId, week, cursor, signal) => new Promise((resolve) => requests.push({ schoolId, week, cursor, signal, resolve }));
  const session = personalizationVm.createHistorySession((next) => { state = next; });
  const current = () => selected;
  const first = session.load(selected.schoolId, selected.week, false, current, fetch, String);
  session.reset();
  selected = { schoolId: 'school', week: '2026-11-16' };
  const second = session.load(selected.schoolId, selected.week, false, current, fetch, String);
  assert.equal(requests[0].signal.aborted, true);
  requests[0].resolve({ changes: [{ date: 'old' }], nextCursor: null });
  await first;
  assert.equal(state.loading, true);
  requests[1].resolve({ changes: [{ date: 'new' }], nextCursor: 'next' });
  await second;
  assert.equal(state.changes[0].date, 'new');
  const third = session.load(selected.schoolId, selected.week, true, current, fetch, String);
  assert.equal(requests[2].cursor, 'next');
  requests[2].resolve({ changes: [{ date: 'older' }], nextCursor: null });
  await third;
  assert.deepEqual(Array.from(state.changes, (change) => change.date), ['new', 'older']);
  assert.equal(state.loading, false);
});

test('disabled history stops further requests until reset', async () => {
  let state;
  let calls = 0;
  const session = personalizationVm.createHistorySession((next) => { state = next; });
  const current = () => ({ schoolId: 'school', week: 'week' });
  const fetch = async () => { calls++; throw { code: 'history_disabled' }; };
  await session.load('school', 'week', false, current, fetch, String);
  assert.equal(state.disabled, true);
  await session.load('school', 'week', false, current, fetch, String);
  assert.equal(calls, 1);
  session.reset();
  await session.load('school', 'week', false, current, fetch, String);
  assert.equal(calls, 2);
});
