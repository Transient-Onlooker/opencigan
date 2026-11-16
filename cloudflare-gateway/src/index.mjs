// Service-binding-only Worker for Cloudflare Pages -> Workers VPC -> Pi.
// Never expose a direct *.workers.dev route for this gateway.
const VALID_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'DELETE']);
const FORWARD_HEADERS = [
  'accept', 'accept-language', 'authorization', 'content-type', 'origin',
  'referer', 'if-none-match', 'if-modified-since',
];
const ORIGIN = 'http://127.0.0.1:8000';

function jsonError(code, status, method) {
  return new Response(
    method === 'HEAD' ? null : JSON.stringify({ code, message: 'API 연결을 처리하지 못했어요.' }),
    { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } },
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith('/api/v1/')) return jsonError('not_found', 404, request.method);
    if (!VALID_METHODS.has(request.method)) return jsonError('method_not_allowed', 405, request.method);

    if (!env?.PRIVATE_API || typeof env.PRIVATE_API.fetch !== 'function' ||
        !env.SEARCH_RATE || !env.GENERAL_RATE) {
      return jsonError('gateway_unconfigured', 503, request.method);
    }

    // Only the Cloudflare-injected client IP is used for the edge limiter.
    // This Worker has workers_dev=false and is callable by Pages service binding only.
    // A missing/invalid IP is grouped under 'unidentified' rather than trusting XFF.
    const ip = request.headers.get('CF-Connecting-IP') ?? '';
    const clientKey = ip.length <= 45 && /^[0-9a-f.:]+$/i.test(ip) ? ip : 'unidentified';
    if (request.method !== 'OPTIONS') {
      const search = url.pathname === '/api/v1/schools' || url.pathname === '/api/v1/neis/schools';
      try {
        const { success } = await (search ? env.SEARCH_RATE : env.GENERAL_RATE).limit({ key: clientKey });
        if (!success) return jsonError('edge_rate_limited', 429, request.method);
      } catch {
        return jsonError('gateway_unavailable', 503, request.method);
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
        body: request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body,
        duplex: 'half',
        redirect: 'manual',
      });
      return await env.PRIVATE_API.fetch(outbound);
    } catch {
      return jsonError('gateway_unavailable', 503, request.method);
    }
  },
};
