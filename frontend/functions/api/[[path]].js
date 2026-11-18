// Cloudflare Pages Functions: only /api/* is sent to the private API Worker.
// This function is not included in GitHub Pages' static Vite output.
const errorOrigins = new Set(['https://opencigan.mcv.kr', 'https://transient-onlooker.github.io']);

export async function onRequest(context) {
  const gateway = context.env?.OPENCIGAN_GATEWAY;
  const error = (code) => {
    const headers = new Headers({ 'Cache-Control': 'no-store', Vary: 'Origin' });
    const origin = context.request.headers.get('Origin');
    const allowed = errorOrigins.has(origin);
    if (allowed) headers.set('Access-Control-Allow-Origin', origin);
    if (allowed && context.request.method === 'OPTIONS') {
      const path = new URL(context.request.url).pathname;
      const methods = path.startsWith('/api/v1/webhooks') ? ['GET', 'HEAD', 'POST', 'PUT', 'DELETE'] : ['GET', 'HEAD', 'POST'];
      const requested = context.request.headers.get('Access-Control-Request-Method');
      if (methods.includes(requested)) {
        headers.set('Vary', 'Origin, Access-Control-Request-Method, Access-Control-Request-Headers');
        headers.set('Access-Control-Allow-Methods', methods.join(', '));
        headers.set('Access-Control-Allow-Headers', path === '/api/v1/timetable.ics' || path === '/api/v1/timetable/history.rss'
          ? 'Content-Type, Authorization, If-None-Match' : 'Content-Type, Authorization');
        return new Response(null, { status: 204, headers });
      }
    }
    headers.set('Content-Type', 'application/json; charset=utf-8');
    return new Response(
      context.request.method === 'HEAD' ? null : JSON.stringify({ code, message: 'API 연결을 처리하지 못했어요.' }),
      { status: 503, headers },
    );
  };
  if (!gateway || typeof gateway.fetch !== 'function') {
    return error('gateway_unconfigured');
  }
  try {
    return await gateway.fetch(context.request);
  } catch {
    return error('gateway_unavailable');
  }
}
