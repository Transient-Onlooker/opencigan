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

test('allowed preflight during an outage lets the actual request expose its 503', async () => {
  const request = new Request('https://opencigan.pages.dev/api/v1/timetable.ics', {
    method: 'OPTIONS',
    headers: { Origin: 'https://transient-onlooker.github.io', 'Access-Control-Request-Method': 'GET', 'Access-Control-Request-Headers': 'if-none-match' },
  });
  for (const env of [{}, { OPENCIGAN_GATEWAY: { fetch: async () => { throw new Error('unavailable'); } } }]) {
    const result = await onRequest({ env, request });
    assert.equal(result.status, 204);
    assert.equal(result.headers.get('access-control-allow-origin'), 'https://transient-onlooker.github.io');
    assert.match(result.headers.get('access-control-allow-methods'), /GET/);
    assert.match(result.headers.get('access-control-allow-headers'), /If-None-Match/i);
    assert.equal(result.headers.get('cache-control'), 'no-store');
    const actual = await onRequest({ env, request: new Request(request.url, {headers: {Origin: 'https://transient-onlooker.github.io'}}) });
    assert.equal(actual.status, 503);
    assert.equal(actual.headers.get('access-control-allow-origin'), 'https://transient-onlooker.github.io');
    assert.match((await actual.json()).code, /^gateway_/);
  }
});

test('outage preflight does not authorize unknown origins or unsupported methods', async () => {
  for (const [origin, method] of [
    ['https://opencigan.mcv.kr.evil.example', 'GET'],
    ['null', 'GET'],
    ['https://opencigan.mcv.kr', 'DELETE'],
    ['https://opencigan.mcv.kr', ''],
  ]) {
    const headers = {Origin: origin};
    if (method) headers['Access-Control-Request-Method'] = method;
    const result = await onRequest({env: {}, request: new Request('https://opencigan.pages.dev/api/v1/status', {method: 'OPTIONS', headers})});
    assert.equal(result.status, 503);
    assert.equal(result.headers.get('access-control-allow-methods'), null);
  }
});

test('outage preflight keeps webhook methods separate from read paths', async () => {
  const headers = {Origin: 'https://opencigan.mcv.kr', 'Access-Control-Request-Method': 'DELETE'};
  const result = await onRequest({env: {}, request: new Request('https://opencigan.pages.dev/api/v1/webhooks/abcdefghijklmnopqrstuvwx', {method: 'OPTIONS', headers})});
  assert.equal(result.status, 204);
  assert.match(result.headers.get('access-control-allow-methods'), /DELETE/);
  assert.equal(result.headers.get('access-control-allow-credentials'), null);
});
