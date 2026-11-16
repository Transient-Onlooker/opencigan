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
