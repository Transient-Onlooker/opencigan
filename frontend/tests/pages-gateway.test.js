import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequest } from '../functions/api/[[path]].js';

test('Pages API function fails closed without a Worker service binding', async () => {
  const result = await onRequest({ env: {}, request: new Request('https://example.pages.dev/api/v1/status') });
  assert.equal(result.status, 503);
  assert.equal((await result.json()).code, 'gateway_unconfigured');
});

test('Pages API function forwards exact request to the service binding', async () => {
  const request = new Request('https://example.pages.dev/api/v1/timetable.ics?school=123', {
    headers: { 'If-None-Match': '"hash"' },
  });
  let passed;
  const result = await onRequest({
    request,
    env: { OPENCIGAN_GATEWAY: { fetch: async (r) => { passed = r; return new Response(null, { status: 304 }); } } },
  });
  assert.equal(passed, request);
  assert.equal(result.status, 304);
});

test('Pages API function returns a safe 503 when the service binding rejects', async () => {
  const env = { OPENCIGAN_GATEWAY: { fetch: async () => { throw new Error('private service details'); } } };
  const result = await onRequest({ env, request: new Request('https://example.pages.dev/api/v1/status') });
  assert.equal(result.status, 503);
  assert.equal(result.headers.get('cache-control'), 'no-store');
  const body = await result.text();
  assert.equal(JSON.parse(body).code, 'gateway_unavailable');
  assert.doesNotMatch(body, /private service details/);
});

test('Pages API function does not return a body for HEAD errors', async () => {
  const request = new Request('https://example.pages.dev/api/v1/status', { method: 'HEAD' });
  for (const env of [{}, { OPENCIGAN_GATEWAY: { fetch: async () => { throw new Error('unavailable'); } } }]) {
    const result = await onRequest({ env, request });
    assert.equal(result.status, 503);
    assert.equal(await result.text(), '');
  }
});

test('Pages errors allow only the known frontend origins without credentials', async () => {
  for (const [origin, expected] of [
    ['https://transient-onlooker.github.io', 'https://transient-onlooker.github.io'],
    ['https://opencigan.mcv.kr', 'https://opencigan.mcv.kr'],
    ['https://opencigan.mcv.kr.evil.example', null],
    ['null', null],
  ]) {
    for (const env of [{}, { OPENCIGAN_GATEWAY: { fetch: async () => { throw new Error('unavailable'); } } }]) {
      const request = new Request('https://opencigan.pages.dev/api/v1/status', { headers: { Origin: origin } });
      const result = await onRequest({ env, request });
      assert.equal(result.status, 503);
      assert.equal(result.headers.get('access-control-allow-origin'), expected);
      assert.equal(result.headers.get('access-control-allow-credentials'), null);
      assert.equal(result.headers.get('vary'), 'Origin');
    }
  }
});

test('failed preflight remains a 503 rather than claiming the API is available', async () => {
  const request = new Request('https://opencigan.pages.dev/api/v1/timetable.ics', {
    method: 'OPTIONS',
    headers: { Origin: 'https://transient-onlooker.github.io', 'Access-Control-Request-Method': 'GET' },
  });
  const result = await onRequest({ env: {}, request });
  assert.equal(result.status, 503);
  assert.equal(result.headers.get('access-control-allow-origin'), 'https://transient-onlooker.github.io');
  assert.equal(result.headers.get('access-control-allow-methods'), null);
});
