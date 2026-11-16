import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/api-error.ts', import.meta.url), 'utf8');
const exports = {};
runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports, Error });
const { apiError } = exports;

test('distinguishes rate limiting, overload and upstream failure', async () => {
  for (const [status, code, expected] of [
    [429, 'rate_limited', /요청이 너무 많아요/],
    [429, 'edge_rate_limited', /요청이 너무 많아요/],
    [503, 'service_overloaded', /요청이 몰리고/],
    [503, 'upstream_unavailable', /원본에서 데이터를 가져오지/],
    [503, 'gateway_unavailable', /API 서버에 연결하지/],
  ]) {
    const error = await apiError(Response.json({ code }, { status }));
    assert.match(error.message, expected);
    assert.equal(error.code, code);
  }
});

test('retains history disabled code and handles non-JSON errors', async () => {
  const history = await apiError(Response.json({ code: 'history_disabled' }, { status: 503 }));
  assert.equal(history.code, 'history_disabled');
  assert.match(history.message, /변경 이력을 제공하지/);
  const unknown = await apiError(new Response('<html>', { status: 502 }));
  assert.match(unknown.message, /502/);
});
