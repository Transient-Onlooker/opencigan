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
