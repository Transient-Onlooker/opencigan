import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/school-search-session.ts', import.meta.url), 'utf8');
const exports = {};
let scheduled;
runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, {
  exports, AbortController, setTimeout: (callback) => { scheduled = callback; return 1; }, clearTimeout: () => { scheduled = undefined; },
});

test('school search cancels an older request and does not show its late response', async () => {
  const states = [];
  const session = exports.createSchoolSearchSession((results, message) => states.push({ results, message }));
  let resolveFirst;
  let firstSignal;
  const search = (query, signal) => {
    if (query === '첫 학교') { firstSignal = signal; return new Promise((resolve) => { resolveFirst = resolve; }); }
    return Promise.resolve({ schools: [{ id: 'second' }], stale: false });
  };
  session.find(() => '첫 학교', search, String);
  const first = scheduled();
  session.find(() => '다음 학교', search, String);
  assert.equal(firstSignal.aborted, true);
  await scheduled();
  resolveFirst({ schools: [{ id: 'first' }], stale: false });
  await first;
  assert.equal(states.at(-1).results[0].id, 'second');
  assert.equal(states.at(-1).message, '');
});

test('school search validates input and clears pending searches', () => {
  let latest;
  const session = exports.createSchoolSearchSession((results, message) => { latest = { results, message }; });
  session.find(() => ' ', () => { throw new Error('unexpected search'); }, String);
  assert.match(latest.message, /두 글자/);
  assert.equal(scheduled, undefined);
  session.find(() => '학교', () => Promise.resolve({ schools: [], stale: false }), String);
  assert.equal(latest.message, '검색 중…');
  session.clear();
  assert.equal(scheduled, undefined);
  assert.equal(latest.message, '');
});

test('failed searches reuse only the same query and preserve the error notice', async () => {
  let latest;
  let query = '봄빛';
  const session = exports.createSchoolSearchSession((results, message, retryable = false) => { latest = { results, message, retryable }; });
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  session.find(() => query, async () => ({ schools: [school], stale: false }), String);
  await scheduled();
  session.find(() => query, async () => { throw new Error('서버 오류'); }, (error) => error.message);
  await scheduled();
  assert.equal(latest.results[0].id, school.id);
  assert.match(latest.message, /서버 오류.*저장된 검색 결과.*최신 정보가 아닐 수/);
  assert.equal(latest.retryable, true);
  query = '다른 학교';
  session.find(() => query, async () => { throw new Error('서버 오류'); }, (error) => error.message);
  await scheduled();
  assert.equal(latest.results.length, 0);
  assert.match(latest.message, /저장된 결과가 없어요/);
  assert.equal(latest.retryable, true);
  session.find(() => query, async () => ({ schools: [school], stale: false }), String);
  assert.equal(latest.retryable, false);
  await scheduled();
  assert.equal(latest.retryable, false);
});

test('stale search results remain selectable and offer retry until a fresh response arrives', async () => {
  let latest;
  const session = exports.createSchoolSearchSession((results, message, retryable = false) => { latest = { results, message, retryable }; });
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  session.find(() => '봄빛', async () => ({ schools: [school], stale: true }), String);
  await scheduled();
  assert.equal(latest.results[0].id, school.id);
  assert.match(latest.message, /최신 정보가 아닐 수/);
  assert.equal(latest.retryable, true);
  session.find(() => '봄빛', async () => ({ schools: [school], stale: false }), String);
  await scheduled();
  assert.equal(latest.message, '');
  assert.equal(latest.retryable, false);
});

test('an outdated query cannot publish or cache a late search result', async () => {
  let latest;
  let query = '첫 학교';
  let resolve;
  const session = exports.createSchoolSearchSession((results, message) => { latest = { results, message }; });
  session.find(() => query, () => new Promise((done) => { resolve = done; }), String);
  const pending = scheduled();
  query = '다른 학교';
  resolve({ schools: [{ id: 'old' }], stale: false });
  await pending;
  assert.equal(latest.message, '검색 중…');
  query = '첫 학교';
  session.find(() => query, async () => { throw new Error('server failed'); }, (error) => error.message);
  await scheduled();
  assert.equal(latest.results.length, 0);
  assert.match(latest.message, /저장된 결과가 없어요/);
});

test('search cache retains at most ten successful queries', async () => {
  let latest;
  let query = '';
  const session = exports.createSchoolSearchSession((results, message) => { latest = { results, message }; });
  for (let i = 0; i < 11; i++) {
    query = `학교${i}`;
    session.find(() => query, async () => ({ schools: [{ id: query }], stale: false }), String);
    await scheduled();
  }
  query = '학교0';
  session.find(() => query, async () => { throw new Error('server failed'); }, (error) => error.message);
  await scheduled();
  assert.equal(latest.results.length, 0);
  assert.match(latest.message, /저장된 결과가 없어요/);
});

test('fresh results survive a new session and are used only for the matching failed query', async () => {
  const values = new Map();
  const storage = () => ({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) });
  const school = { id: '123', name: '봄빛고등학교', region: '서울' };
  const first = exports.createSchoolSearchSession(() => {}, storage);
  first.find(() => '봄빛', async () => ({ schools: [school], stale: false }), String);
  await scheduled();
  let latest;
  const second = exports.createSchoolSearchSession((results, message, retryable) => { latest = { results, message, retryable }; }, storage);
  second.find(() => '봄빛', async () => { throw new Error('offline'); }, (error) => error.message);
  await scheduled();
  assert.equal(latest.results[0].id, school.id);
  assert.match(latest.message, /offline.*이 기기에 저장된 검색 결과.*최신 정보가 아닐/);
  assert.equal(latest.retryable, true);
  second.find(() => '다른 학교', async () => { throw new Error('offline'); }, String);
  await scheduled();
  assert.equal(latest.results.length, 0);
});

test('unavailable or malformed storage does not prevent searching', async () => {
  let latest;
  for (const storage of [() => { throw new Error('blocked'); }, () => ({ getItem: () => '{broken', setItem: () => { throw new Error('full'); } })]) {
    const session = exports.createSchoolSearchSession((results) => { latest = results; }, storage);
    session.find(() => '봄빛', async () => ({ schools: [{ id: '123', name: '봄빛', region: '서울' }], stale: false }), String);
    await scheduled();
    assert.equal(latest[0].id, '123');
  }
});

test('a fresh empty search invalidates the saved result across sessions', async () => {
  const values = new Map();
  const storage = () => ({ getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) });
  const school = { id: '123', name: '봄빛고등학교', region: '서울' };
  let latest;
  const session = exports.createSchoolSearchSession((results, message) => { latest = { results, message }; }, storage);
  session.find(() => '봄빛', async () => ({ schools: [school], stale: false }), String);
  await scheduled();
  session.find(() => '봄빛', async () => ({ schools: [], stale: false }), String);
  await scheduled();
  session.find(() => '봄빛', async () => { throw new Error('offline'); }, String);
  await scheduled();
  assert.equal(latest.results.length, 0);
  assert.match(latest.message, /저장된 결과가 없어요/);
  const reloaded = exports.createSchoolSearchSession((results, message) => { latest = { results, message }; }, storage);
  reloaded.find(() => '봄빛', async () => { throw new Error('offline'); }, String);
  await scheduled();
  assert.equal(latest.results.length, 0);
  assert.match(latest.message, /저장된 결과가 없어요/);
});
