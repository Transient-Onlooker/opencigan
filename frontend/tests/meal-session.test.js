import { test } from 'node:test';
import assert from 'node:assert/strict';
import { personalizationVm } from './helpers/personalization-vm.js';

test('meal session coalesces same-week requests and ignores a cancelled week', async () => {
  let state;
  let now = 1000;
  const requests = [];
  const session = personalizationVm.createMealSession((next) => { state = next; });
  const fetch = (school, from, to, signal) => new Promise((resolve) => requests.push({ school, from, signal, resolve }));
  const load = (from, preserve = false) => session.load('neis', from, from, preserve, () => now, 100, fetch, String);
  load('week1');
  load('week1');
  assert.equal(requests.length, 1);
  load('week2');
  assert.equal(requests[0].signal.aborted, true);
  requests[0].resolve({ meals: [{ date: 'old' }], stale: false });
  requests[1].resolve({ meals: [{ date: 'new' }], stale: false });
  await new Promise(setImmediate);
  assert.equal(state.meals[0].date, 'new');
  load('week2');
  assert.equal(requests.length, 2);
  now = 1100;
  load('week2');
  assert.equal(requests.length, 3);
  session.cancel();
});

test('meal school connection ignores a late response after switching schools', async () => {
  let state;
  let current = 'a';
  let resolve;
  let chosen = false;
  const session = personalizationVm.createMealSession((next) => { state = next; });
  const pending = session.connect({ id: 'a', name: 'school', region: '서울' }, () => current,
    () => new Promise((done) => { resolve = done; }), () => ({ id: 'neis' }), () => [], () => { chosen = true; }, String);
  current = 'b';
  session.reset();
  resolve({ schools: [], stale: false });
  await pending;
  assert.equal(chosen, false);
  assert.equal(state.neis, null);
  assert.equal(state.neisLoading, false);
});

test('a cancelled meal request cannot replace the new request state when it fails late', async () => {
  let state;
  const requests = [];
  const session = personalizationVm.createMealSession((next) => { state = next; });
  const fetch = (school, from, to, signal) => new Promise((resolve, reject) => requests.push({ signal, resolve, reject }));
  const load = (school) => session.load(school, 'week', 'week', false, () => 1000, 100, fetch, String);
  load('old');
  load('new');
  assert.equal(requests[0].signal.aborted, true);
  requests[0].reject(new Error('old request failed'));
  await new Promise(setImmediate);
  assert.equal(state.loading, true);
  assert.equal(state.error, '');
  requests[1].resolve({ meals: [{ date: 'new' }], stale: false });
  await new Promise(setImmediate);
  assert.equal(state.loading, false);
  assert.equal(state.error, '');
  assert.equal(state.meals[0].date, 'new');
});

test('choosing a meal school cancels search and loads meals even when storage is blocked', async () => {
  let state;
  let resolve;
  let loads = 0;
  const session = personalizationVm.createMealSession((next) => { state = next; });
  const pending = session.connect({ id: 'a', name: 'school', region: '서울' }, () => 'a',
    () => new Promise((done) => { resolve = done; }), () => null, () => [], () => {}, String);
  const school = { id: 'neis', name: 'school', region: '서울', address: '서울' };
  session.choose(school, () => { throw new Error('blocked'); }, () => { loads++; });
  resolve({ schools: [], stale: false });
  await pending;
  assert.equal(state.neis, school);
  assert.equal(state.neisLoading, false);
  assert.equal(state.searchState, '급식도 school로 연결했어요.');
  assert.equal(loads, 1);
});
