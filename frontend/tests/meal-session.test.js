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
