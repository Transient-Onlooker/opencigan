// Service-binding-only Worker for Cloudflare Pages -> Workers VPC -> Pi.
// Never expose a direct *.workers.dev route for this gateway.
const READ_PATHS = new Set([
  '/api/v1/status', '/api/v1/schools', '/api/v1/neis/schools',
  '/api/v1/timetable', '/api/v1/timetable.ics', '/api/v1/timetable/history',
  '/api/v1/timetable/history.rss', '/api/v1/meals',
  '/api/v1/admin/analytics', '/api/v1/admin/access-logs',
]);
// Suggestion intake stays OFF unless Pi persistence and edge budget are configured.
const SUGGESTION_ITEM = /^\/api\/v1\/suggestions\/[A-Za-z0-9_-]{24}$/;
const SUGGESTION_ADMIN_ITEM = /^\/api\/v1\/admin\/suggestions\/[A-Za-z0-9_-]{24}$/;
const MAX_BODY_BYTES = 4096;
const FORWARD_HEADERS = [
  'accept', 'accept-language', 'authorization', 'content-type', 'origin',
  'referer', 'if-none-match', 'if-modified-since', 'user-agent',
];
const ORIGIN = 'http://127.0.0.1:8000';

function jsonError(code, status, request, allowedOrigins, extraHeaders = {}) {
  const headers = new Headers({ 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'Vary': 'Origin', ...extraHeaders });
  const origin = request.headers.get('Origin');
  if (origin && allowedOrigins.includes(origin)) {
    headers.set('Access-Control-Allow-Origin', origin);
    headers.set('Access-Control-Expose-Headers', 'Retry-After');
  }
  return new Response(
    request.method === 'HEAD' ? null : JSON.stringify({ code, error: 'API 연결을 처리하지 못했어요.', message: 'API 연결을 처리하지 못했어요.' }),
    { status, headers },
  );
}


function normalizeClientIp(ip) {
  if (typeof ip !== 'string' || ip.length > 45) return null;
  if (/^(?:0|[1-9]\d{0,2})(?:\.(?:0|[1-9]\d{0,2})){3}$/.test(ip)) {
    return ip.split('.').every(part => Number(part) <= 255) ? ip : null;
  }
  if (ip.includes(':')) {
    try {
      const host = new URL('http://[' + ip + ']/').hostname;
      if (host.startsWith('[') && host.endsWith(']')) return host.slice(1, -1);
    } catch { /* Invalid IPv6. */ }
  }
  return null;
}

async function attachSignedClientIp(headers, request, env, url, clientIp) {
  const secret = env.PROXY_IP_SIGNING_KEY;
  if (secret === undefined || secret === null || secret === '') return;
  const encoder = new TextEncoder();
  if (typeof secret !== 'string' || encoder.encode(secret).byteLength < 32) {
    throw new Error('invalid client IP signing configuration');
  }
  if (clientIp === 'unidentified') return;
  const timestamp = String(Math.floor(Date.now() / 1000));
  const payload = [request.method.toUpperCase(), url.pathname, url.search.slice(1), clientIp, timestamp].join('\n');
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
  const signature = new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(payload)));
  headers.set('X-Opencigan-Client-IP', clientIp);
  headers.set('X-Opencigan-IP-Timestamp', timestamp);
  headers.set('X-Opencigan-IP-Signature', Array.from(signature, b => b.toString(16).padStart(2, '0')).join(''));
}

export default {
  async fetch(request, env) {
    const allowedOrigins = (env?.ALLOWED_ORIGINS || '').split(',').map(origin => origin.trim()).filter(Boolean);
    const error = (code, status, headers) => jsonError(code, status, request, allowedOrigins, headers);
    const url = new URL(request.url);
    const path = url.pathname;
    const webhook = path.match(/^\/api\/v1\/webhooks\/([A-Za-z0-9_-]{24})(\/deliveries|\/test|\/rotate|\/schedule|\/template(?:\/preview)?)?$/);
    let methods;
    if (path === '/api/v1/admin/access-anomalies' && env?.ACCESS_ANOMALIES_ENABLED === '1') methods = ['GET', 'HEAD'];
    else if (READ_PATHS.has(path)) methods = ['GET', 'HEAD'];
    else if (path === '/api/v1/suggestions') methods = ['GET', 'HEAD', 'POST'];
    else if (SUGGESTION_ITEM.test(path)) methods = ['GET', 'HEAD'];
    else if (path === '/api/v1/admin/suggestions') methods = ['GET', 'HEAD'];
    else if (SUGGESTION_ADMIN_ITEM.test(path)) methods = ['PATCH', 'DELETE'];
    else if (path === '/api/v1/analytics/pageview' || path === '/api/v1/webhooks') methods = ['POST'];
    else if (webhook?.[2] === '/deliveries') methods = ['GET', 'HEAD'];
    else if (webhook?.[2] === '/test' || webhook?.[2] === '/rotate' || webhook?.[2] === '/template/preview') methods = ['POST'];
    else if (webhook?.[2] === '/template' || webhook?.[2] === '/schedule') methods = ['GET', 'HEAD', 'PUT', 'DELETE'];
    else if (webhook) methods = ['GET', 'HEAD', 'PUT', 'DELETE'];
    else return error('not_found', 404);
    if (request.method !== 'OPTIONS' && !methods.includes(request.method)) {
      return error('method_not_allowed', 405);
    }

    if (!env?.PRIVATE_API || typeof env.PRIVATE_API.fetch !== 'function' ||
        !env.SEARCH_RATE || !env.GENERAL_RATE || !env.TIMETABLE_RATE || !env.CALENDAR_RATE) {
      return error('gateway_unconfigured', 503);
    }

    // Only the Cloudflare-injected client IP is used for the edge limiter.
    // This Worker has workers_dev=false and is callable by Pages service binding only.
    // A missing/invalid IP is grouped under 'unidentified' rather than trusting XFF.
    const clientKey = normalizeClientIp(request.headers.get('CF-Connecting-IP')) || 'unidentified';
    if (request.method === 'OPTIONS') {
      try {
        const { success } = await env.GENERAL_RATE.limit({ key: `preflight:${clientKey}` });
        if (!success) return error('edge_rate_limited', 429, { 'Retry-After': '60' });
      } catch {
        console.warn('gateway_failure stage=preflight_limit');
        return error('gateway_unavailable', 503);
      }
    } else {
      const search = path === '/api/v1/schools' || path === '/api/v1/neis/schools';
      const category = path === '/api/v1/timetable.ics' || path === '/api/v1/timetable/history.rss'
        ? 'CALENDAR_RATE' : path === '/api/v1/timetable' ? 'TIMETABLE_RATE'
        : path === '/api/v1/meals' ? 'MEAL_RATE'
        : path.startsWith('/api/v1/admin/') ? 'ADMIN_RATE'
        : path === '/api/v1/suggestions' || SUGGESTION_ITEM.test(path) ? 'SUGGESTION_RATE'
        : path === '/api/v1/webhooks' || webhook ? 'WEBHOOK_RATE' : null;
      const categoryLimiter = category ? env[category] : null;
      if (category && !categoryLimiter) return error('gateway_unconfigured', 503);
      try {
        const { success } = await (search ? env.SEARCH_RATE : env.GENERAL_RATE).limit({ key: clientKey });
        const categoryKey = category === 'SUGGESTION_RATE'
          ? `${request.method === 'POST' ? 'write' : 'read'}:${clientKey}` : clientKey;
        const categoryAllowed = success && categoryLimiter
          ? (await categoryLimiter.limit({ key: categoryKey })).success : true;
        if (!success || !categoryAllowed) {
          return error('edge_rate_limited', 429, { 'Retry-After': '60' });
        }
      } catch {
        console.warn('gateway_failure stage=request_limit');
        return error('gateway_unavailable', 503);
      }
    }

    let body;
    if (request.body) {
      const reader = request.body.getReader();
      const chunks = [];
      let size = 0;
      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > MAX_BODY_BYTES) {
            reader.cancel().catch(() => {});
            return error('payload_too_large', 413);
          }
          chunks.push(value);
        }
      } catch {
        return error('invalid_request', 400);
      }
      body = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        body.set(chunk, offset);
        offset += chunk.byteLength;
      }
    }

    const headers = new Headers();
    for (const key of FORWARD_HEADERS) {
      const value = request.headers.get(key);
      if (value !== null) headers.set(key, value);
    }
    // Never forward untrusted visitor-supplied IP headers to Pi.
    // Only this Worker may create authenticated client IP headers.
    const destination = new URL(url.pathname + url.search, ORIGIN);
    let stage = 'signing';
    const started = performance.now();
    try {
      await attachSignedClientIp(headers, request, env, url, clientKey);
      stage = 'private_fetch';
      const outbound = new Request(destination, {
        method: request.method,
        headers,
        body,
        duplex: 'half',
        redirect: 'manual',
      });
      return await env.PRIVATE_API.fetch(outbound);
    } catch {
      console.warn('gateway_failure stage=%s elapsed_ms=%d', stage, Math.max(0, Math.round(performance.now() - started)));
      return error('gateway_unavailable', 503);
    }
  },
};
