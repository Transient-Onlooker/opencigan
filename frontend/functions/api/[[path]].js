// Cloudflare Pages Functions: only /api/* is sent to the private API Worker.
// This function is not included in GitHub Pages' static Vite output.
export async function onRequest(context) {
  const gateway = context.env?.OPENCIGAN_GATEWAY;
  const error = (code) => new Response(
    context.request.method === 'HEAD' ? null : JSON.stringify({ code, message: 'API 연결을 처리하지 못했어요.' }),
    { status: 503, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } },
  );
  if (!gateway || typeof gateway.fetch !== 'function') {
    return error('gateway_unconfigured');
  }
  try {
    return await gateway.fetch(context.request);
  } catch {
    return error('gateway_unavailable');
  }
}
