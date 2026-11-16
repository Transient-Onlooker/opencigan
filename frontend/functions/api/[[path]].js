// Cloudflare Pages Functions: only /api/* is sent to the private API Worker.
// This function is not included in GitHub Pages' static Vite output.
export async function onRequest(context) {
  const gateway = context.env?.OPENCIGAN_GATEWAY;
  if (!gateway || typeof gateway.fetch !== 'function') {
    return new Response(
      JSON.stringify({ code: 'gateway_unconfigured', message: 'API 연결이 아직 설정되지 않았어요.' }),
      {
        status: 503,
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' },
      },
    );
  }
  return gateway.fetch(context.request);
}
