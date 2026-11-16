// Service-binding-only Worker for Cloudflare Pages -> Workers VPC -> Pi.
// Never expose a direct *.workers.dev route for this gateway.
const READ_PATHS = new Set([
  '/api/v1/status', '/api/v1/schools', '/api/v1/neis/schools',
  '/api/v1/timetable', '/api/v1/timetable.ics', '/api/v1/timetable/history',
  '/api/v1/timetable/history.rss', '/api/v1/meals',
  '/api/v1/admin/analytics', '/api/v1/admin/access-logs',
]);
const MAX_BODY_BYTES = 4096;
const FORWARD_HEADERS = [
  'accept', 'accept-language', 'authorization', 'content-type', 'origin',
  'referer', 'if-none-match', 'if-modified-since',
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
    request.method === 'HEAD' ? null : JSON.stringify({ code, message: 'API 연결을 처리하지 못했어요.' }),
    { status, headers },
  );
}

export default {
  async fetch(request, env) {
    const allowedOrigins = (env?.ALLOWED_ORIGINS || '').split(',').map(origin => origin.trim()).filter(Boolean);
    const error = (code, status, headers) => jsonError(code, status, request, allowedOrigins, headers);
    const url = new URL(request.url);
    const path = url.pathname;
    const webhook = path.match(/^\/api\/v1\/webhooks\/([A-Za-z0-9_-]{24})(\/deliveries|\/test)?$/);
    let methods;
    if (READ_PATHS.has(path)) methods = ['GET', 'HEAD'];
    else if (path === '/api/v1/analytics/pageview' || path === '/api/v1/webhooks') methods = ['POST'];
    else if (webhook?.[2] === '/deliveries') methods = ['GET', 'HEAD'];
    else if (webhook?.[2] === '/test') methods = ['POST'];
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
    const ip = request.headers.get('CF-Connecting-IP') ?? '';
    const clientKey = ip.length <= 45 && /^[0-9a-f.:]+$/i.test(ip) ? ip : 'unidentified';
    if (request.method !== 'OPTIONS') {
      const search = path === '/api/v1/schools' || path === '/api/v1/neis/schools';
      const category = path === '/api/v1/timetable.ics' || path === '/api/v1/timetable/history.rss'
        ? 'calendar' : path === '/api/v1/timetable' ? 'timetable' : null;
      try {
        const { success } = await (search ? env.SEARCH_RATE : env.GENERAL_RATE).limit({ key: clientKey });
        const categoryLimiter = category === 'calendar' ? env.CALENDAR_RATE : env.TIMETABLE_RATE;
        const categoryAllowed = success && category
          ? (await categoryLimiter.limit({ key: clientKey })).success : true;
        if (!success || !categoryAllowed) {
          return error('edge_rate_limited', 429, { 'Retry-After': '60' });
        }
      } catch {
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
    // Never pass visitor-supplied Forwarded, X-Forwarded-For, CF-Connecting-IP,
    // CF-Access headers, or arbitrary Host values into the Pi trust boundary.
    // Origin-side per-IP attribution remains a separate P0 verification gate.
    const destination = new URL(url.pathname + url.search, ORIGIN);
    try {
      const outbound = new Request(destination, {
        method: request.method,
        headers,
        body,
        duplex: 'half',
        redirect: 'manual',
      });
      return await env.PRIVATE_API.fetch(outbound);
    } catch {
      return error('gateway_unavailable', 503);
    }
  },
};
