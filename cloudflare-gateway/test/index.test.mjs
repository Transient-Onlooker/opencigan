import test from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/index.mjs';

const req = (path, init = {}) => new Request('https://opencigan.pages.dev' + path, init);
function setup({search = true, general = true, failFetch = false} = {}) {
  const calls = [];
  const env = {
    PRIVATE_API: { fetch: async (request) => {
      calls.push(request);
      if (failFetch) throw new Error('private origin unreachable: do not disclose');
      return new Response('calendar data', { status: 200, headers: { ETag: '"abc"' } });
    } },
    SEARCH_RATE: { limit: async () => ({ success: search }) },
    GENERAL_RATE: { limit: async () => ({ success: general }) },
  };
  return { env, calls };
}

test('only /api/v1/ routes are forwarded; no open proxy', async () => {
  const { env, calls } = setup();
  assert.equal((await worker.fetch(req('/private?url=http://evil.test'), env)).status, 404);
  assert.equal((await worker.fetch(req('/api/other'), env)).status, 404);
  assert.equal((await worker.fetch(req('/api/v1/unknown'), env)).status, 404);
  assert.equal((await worker.fetch(req('/api/v1/%2e%2e/admin'), env)).status, 404);
  assert.equal((await worker.fetch(req('/api/v1/status', {method: 'POST'}), env)).status, 405);
  assert.equal(calls.length, 0);
});

test('requires VPC service and both limiters', async () => {
  const response = await worker.fetch(req('/api/v1/status'), {});
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'gateway_unconfigured');
});

test('private request URL remains fixed and conditional ICS headers survive', async () => {
  const { env, calls } = setup();
  const response = await worker.fetch(req('/api/v1/timetable.ics?school=99', {
    headers: {
      'If-None-Match': '"abc"', 'Accept': 'text/calendar',
      'X-Forwarded-For': '9.9.9.9', Forwarded: 'for=9.9.9.9',
      'CF-Connecting-IP': '203.0.113.9', Host: 'evil.example',
    },
  }), env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('etag'), '"abc"');
  assert.equal(calls.length, 1);
  const outgoing = calls[0];
  assert.equal(outgoing.url, 'http://127.0.0.1:8000/api/v1/timetable.ics?school=99');
  assert.equal(outgoing.headers.get('if-none-match'), '"abc"');
  assert.equal(outgoing.headers.get('x-forwarded-for'), null);
  assert.equal(outgoing.headers.get('forwarded'), null);
  assert.equal(outgoing.headers.get('cf-connecting-ip'), null);
  assert.equal(outgoing.headers.get('host'), null);
});

test('school search is separately rate limited', async () => {
  const { env, calls } = setup({ search: false });
  const response = await worker.fetch(req('/api/v1/schools?q=test'), env);
  assert.equal(response.status, 429);
  assert.equal((await response.json()).code, 'edge_rate_limited');
  assert.equal(calls.length, 0);
});

test('OPTIONS bypasses rate limits for CORS preflight and still reaches Pi', async () => {
  const { env, calls } = setup({ search: false, general: false });
  const response = await worker.fetch(req('/api/v1/schools', { method: 'OPTIONS', headers: {Origin: 'https://opencigan.mcv.kr'} }), env);
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get('origin'), 'https://opencigan.mcv.kr');
});

test('webhook PUT preserves authorization and JSON body', async () => {
  const { env, calls } = setup();
  const response = await worker.fetch(req('/api/v1/webhooks/abcdefghijklmnopqrstuvwx', {
    method: 'PUT',
    headers: { 'Authorization': 'Bearer example', 'Content-Type': 'application/json' },
    body: '{"filters":{}}',
  }), env);
  assert.equal(response.status, 200);
  assert.equal(calls[0].method, 'PUT');
  assert.equal(calls[0].headers.get('authorization'), 'Bearer example');
  assert.equal(await calls[0].text(), '{"filters":{}}');
});

test('limits streamed request bodies to the backend 4096 byte limit', async () => {
  const { env, calls } = setup();
  const path = '/api/v1/analytics/pageview';
  const accepted = await worker.fetch(req(path, {method: 'POST', body: 'a'.repeat(4096)}), env);
  assert.equal(accepted.status, 200);
  assert.equal((await calls[0].arrayBuffer()).byteLength, 4096);
  const oversized = await worker.fetch(req(path, {method: 'POST', body: 'a'.repeat(4097)}), env);
  assert.equal(oversized.status, 413);
  assert.equal((await oversized.json()).code, 'payload_too_large');
  assert.equal(calls.length, 1);
  const stream = new ReadableStream({start(controller) {
    controller.enqueue(new Uint8Array(4096));
    controller.enqueue(new Uint8Array(1));
    controller.close();
  }});
  const streamed = await worker.fetch(req(path, {method: 'POST', body: stream, duplex: 'half'}), env);
  assert.equal(streamed.status, 413);
  assert.equal(calls.length, 1);
});

test('private service errors do not expose internal exception messages', async () => {
  const { env } = setup({failFetch: true});
  const response = await worker.fetch(req('/api/v1/status'), env);
  assert.equal(response.status, 503);
  const body = await response.text();
  assert.equal(body.includes('private origin unreachable'), false);
});

test('HEAD failures contain no response body', async () => {
  const response = await worker.fetch(req('/api/v1/status',{method:'HEAD'}), {});
  assert.equal(response.status, 503);
  assert.equal(await response.text(), '');
});
