import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import worker from '../src/index.mjs';

const req = (path, init = {}) => new Request('https://opencigan.pages.dev' + path, init);
function setup({search = true, general = true, failFetch = false, blockedKey = ''} = {}) {
  const calls = [];
  const limits = [];
  const env = {
    ALLOWED_ORIGINS: 'https://opencigan.mcv.kr,https://transient-onlooker.github.io',
    PRIVATE_API: { fetch: async (request) => {
      calls.push(request);
      if (failFetch) throw new Error('private origin unreachable: do not disclose');
      return new Response('calendar data', { status: 200, headers: { ETag: '"abc"' } });
    } },
    SEARCH_RATE: { limit: async ({key}) => { limits.push(['search', key]); return { success: search }; } },
    GENERAL_RATE: { limit: async ({key}) => { limits.push(['general', key]); return { success: general }; } },
    TIMETABLE_RATE: { limit: async ({key}) => { limits.push(['timetable', key]); return { success: blockedKey !== `timetable:${key}` }; } },
    CALENDAR_RATE: { limit: async ({key}) => { limits.push(['calendar', key]); return { success: blockedKey !== `calendar:${key}` }; } },
    MEAL_RATE: { limit: async ({key}) => { limits.push(['meal', key]); return { success: blockedKey !== `meal:${key}` }; } },
    ADMIN_RATE: { limit: async ({key}) => { limits.push(['admin', key]); return { success: blockedKey !== `admin:${key}` }; } },
    WEBHOOK_RATE: { limit: async ({key}) => { limits.push(['webhook', key]); return { success: blockedKey !== `webhook:${key}` }; } },
  };
  return { env, calls, limits };
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

test('requires VPC service and existing core limiters', async () => {
  const response = await worker.fetch(req('/api/v1/status'), {});
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'gateway_unconfigured');
});

test('meal, admin and webhook limits reject only their own category before forwarding', async () => {
  const ip = '203.0.113.9';
  const headers = {'CF-Connecting-IP': ip};
  for (const [category, path, init] of [
    ['meal', '/api/v1/meals', {}],
    ['admin', '/api/v1/admin/analytics', {}],
    ['webhook', '/api/v1/webhooks', {method: 'POST'}],
    ['webhook', '/api/v1/webhooks/abcdefghijklmnopqrstuvwx/deliveries', {}],
  ]) {
    const { env, calls, limits } = setup({blockedKey: `${category}:${ip}`});
    const response = await worker.fetch(req(path, {...init, headers}), env);
    assert.equal(response.status, 429);
    assert.equal(response.headers.get('retry-after'), '60');
    assert.equal(calls.length, 0);
    assert.deepEqual(limits, [['general', ip], [category, ip]]);
    assert.equal((await worker.fetch(req('/api/v1/timetable', {headers}), env)).status, 200);
  }
});

test('missing category binding fails closed for that category without disrupting others', async () => {
  const { env, calls } = setup();
  delete env.MEAL_RATE;
  const response = await worker.fetch(req('/api/v1/meals'), env);
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'gateway_unconfigured');
  assert.equal(calls.length, 0);
  assert.equal((await worker.fetch(req('/api/v1/status'), env)).status, 200);
});

test('private request URL remains fixed and conditional ICS headers survive', async () => {
  const { env, calls } = setup();
  const response = await worker.fetch(req('/api/v1/timetable.ics?school=99', {
    headers: {
      'If-None-Match': '"abc"', 'Accept': 'text/calendar', 'User-Agent': 'OpenCigan-Test/1.0',
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
  assert.equal(outgoing.headers.get('user-agent'), 'OpenCigan-Test/1.0');
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
  assert.equal(response.headers.get('retry-after'), '60');
  assert.equal(calls.length, 0);
});

test('gateway errors expose retry information only to allowed origins', async () => {
  const { env } = setup({search: false});
  for (const [origin, expected] of [
    ['https://opencigan.mcv.kr', 'https://opencigan.mcv.kr'],
    ['https://opencigan.mcv.kr.evil.example', null],
    ['null', null],
  ]) {
    const response = await worker.fetch(req('/api/v1/schools', {headers: {Origin: origin}}), env);
    assert.equal(response.status, 429);
    assert.equal(response.headers.get('access-control-allow-origin'), expected);
    assert.equal(response.headers.get('access-control-expose-headers'), expected ? 'Retry-After' : null);
    assert.equal(response.headers.get('vary'), 'Origin');
  }
  const unconfigured = await worker.fetch(req('/api/v1/status', {headers: {Origin: 'https://opencigan.mcv.kr'}}), {
    ALLOWED_ORIGINS: 'https://opencigan.mcv.kr',
  });
  assert.equal(unconfigured.status, 503);
  assert.equal(unconfigured.headers.get('access-control-allow-origin'), 'https://opencigan.mcv.kr');
});

test('timetable and calendar use separate category budgets alongside the general cap', async () => {
  const ip = '203.0.113.9';
  const { env, calls, limits } = setup({blockedKey: `calendar:${ip}`});
  const headers = {'CF-Connecting-IP': ip, 'X-Forwarded-For': '198.51.100.1'};
  const calendar = await worker.fetch(req('/api/v1/timetable.ics', {headers}), env);
  assert.equal(calendar.status, 429);
  assert.equal(calendar.headers.get('retry-after'), '60');
  assert.equal(calls.length, 0);
  const timetable = await worker.fetch(req('/api/v1/timetable', {headers}), env);
  assert.equal(timetable.status, 200);
  assert.deepEqual(limits, [
    ['general', ip], ['calendar', ip],
    ['general', ip], ['timetable', ip],
  ]);
});

test('OPTIONS uses a separate preflight key and forwards allowed CORS requests', async () => {
  const { env, calls, limits } = setup({ search: false });
  const response = await worker.fetch(req('/api/v1/schools', { method: 'OPTIONS', headers: {Origin: 'https://opencigan.mcv.kr', 'CF-Connecting-IP': '203.0.113.9'} }), env);
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.get('origin'), 'https://opencigan.mcv.kr');
  assert.deepEqual(limits, [['general', 'preflight:203.0.113.9']]);
});

test('excessive preflights are rejected before reaching Pi without consuming normal keys', async () => {
  const { env, calls, limits } = setup();
  env.GENERAL_RATE.limit = async ({key}) => { limits.push(['general', key]); return { success: !key.startsWith('preflight:') }; };
  const headers = {Origin: 'https://opencigan.mcv.kr', 'CF-Connecting-IP': '203.0.113.9'};
  const blocked = await worker.fetch(req('/api/v1/meals', {method: 'OPTIONS', headers}), env);
  assert.equal(blocked.status, 429);
  assert.equal(blocked.headers.get('retry-after'), '60');
  assert.equal(blocked.headers.get('access-control-allow-origin'), 'https://opencigan.mcv.kr');
  assert.equal(calls.length, 0);
  assert.equal((await worker.fetch(req('/api/v1/meals', {headers}), env)).status, 200);
  assert.deepEqual(limits, [['general', 'preflight:203.0.113.9'], ['general', '203.0.113.9'], ['meal', '203.0.113.9']]);
});

test('preflight limiter failure returns 503 and never forwards to Pi', async () => {
  const { env, calls } = setup();
  env.GENERAL_RATE.limit = async () => { throw new Error('limiter unavailable'); };
  const response = await worker.fetch(req('/api/v1/meals', {method: 'OPTIONS'}), env);
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'gateway_unavailable');
  assert.equal(calls.length, 0);
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


test('signed visitor IP uses Cloudflare IP and binds method path and query', async () => {
  const { env, calls } = setup();
  env.PROXY_IP_SIGNING_KEY = 'long-shared-key-for-testing-only-0123456789abcdef';
  const result = await worker.fetch(req('/api/v1/timetable?school=2%3AExample&grade=2', {
    headers: {
      'CF-Connecting-IP': '203.0.113.9', 'X-Forwarded-For': '192.0.2.44',
      'X-Opencigan-Client-IP': '192.0.2.44', 'X-Opencigan-IP-Signature': 'spoofed',
    },
  }), env);
  assert.equal(result.status, 200);
  assert.equal(calls.length, 1);
  const h = calls[0].headers;
  const ts = h.get('x-opencigan-ip-timestamp');
  assert.equal(h.get('x-opencigan-client-ip'), '203.0.113.9');
  assert.ok(Math.abs(Date.now()/1000 - Number(ts)) < 60);
  assert.equal(h.get('x-forwarded-for'), null);
  const message = ['GET','/api/v1/timetable','school=2%3AExample&grade=2','203.0.113.9',ts].join('\n');
  assert.equal(h.get('x-opencigan-ip-signature'), createHmac('sha256', env.PROXY_IP_SIGNING_KEY).update(message).digest('hex'));
});

test('malformed edge IP does not produce signed attribution', async () => {
  const { env, calls } = setup();
  env.PROXY_IP_SIGNING_KEY = 'long-shared-key-for-testing-only-0123456789abcdef';
  for (const ip of ['999.1.1.1', 'not-an-ip', '1.2.3.4:5555']) {
    assert.equal((await worker.fetch(req('/api/v1/status', {headers:{
      'CF-Connecting-IP': ip, 'X-Opencigan-Client-IP': '198.51.100.1',
    }}),env)).status, 200);
  }
  assert.equal(calls.length, 3);
  for (const request of calls) {
    assert.equal(request.headers.get('x-opencigan-client-ip'), null);
    assert.equal(request.headers.get('x-opencigan-ip-signature'), null);
  }
});

test('invalid configured signing key fails closed', async () => {
  const { env, calls } = setup();
  env.PROXY_IP_SIGNING_KEY = 'short';
  const response = await worker.fetch(req('/api/v1/status',{headers:{'CF-Connecting-IP':'203.0.113.9'}}),env);
  assert.equal(response.status, 503);
  assert.equal(calls.length, 0);
  assert.equal((await response.json()).code, 'gateway_unavailable');
});
