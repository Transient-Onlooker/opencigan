# OpenCigan private API gateway (staging scaffold)

**No live Cloudflare, DNS or Pi resources are created by this directory.** The existing GitHub Pages + Tailscale Funnel stays the production path until all gates pass.

### Topology

`<project>.pages.dev/api/v1/*` → `frontend/functions/api/[[path]].js` → Pages **Service Binding** `OPENCIGAN_GATEWAY` → `opensigan-private-api` Worker → **Workers VPC Service** binding `PRIVATE_API` → Pi `127.0.0.1:8000`.

The separate Pi → Comcigan WARP egress proxy is unchanged.

### Cloudflare account setup (after confirming Workers VPC access)

1. Create Cloudflare Pages from the existing GitHub repository with **Root directory: `frontend`**, build command `npm ci && npm run build`, output `dist`. **Set `VITE_API_BASE_URL` to an empty string** (same-origin API via Pages Functions), not the current Tailscale URL. Test only at the `pages.dev` hostname.
2. Under **Workers VPC → Tunnels**, create a dedicated private Tunnel; install the dashboard-supplied `cloudflared` ARM64 package/service on the Raspberry Pi with operator approval. Workers VPC needs cloudflared >=2025.7.0, QUIC and outgoing UDP 7844. **No public hostname or port forward is needed.**
3. Register a VPC Service for HTTP `127.0.0.1:8000` reachable through that tunnel. Replace `REPLACE_WITH_VPC_SERVICE_ID` in a **local copy** of `wrangler.example.jsonc` named `wrangler.jsonc` and run `npx wrangler deploy --config wrangler.jsonc` from this directory. The example's rate limits are *staging starting values*, not validated production thresholds.
4. In **Pages → Settings → Bindings** add **Service binding** `OPENCIGAN_GATEWAY` → Worker `opensigan-private-api`; redeploy Pages. No direct public `workers.dev` endpoint is exposed for the API Worker (`workers_dev: false`).
5. Verify `https://<project>.pages.dev/api/v1/status`, JSON, school lookup, meals, `.ics` 200/304, HEAD/OPTIONS, and frontend same-origin calls, plus admin authentication and distinct-IP rate limiting (including the Pi's reverse proxy behavior). Do not push a change to MCVKR CNAME before passing tests.

**Security gates:** the Worker strips visitor-supplied forwarding/IP headers before calling Pi and does not yet establish verified original-client-IP attribution on the Pi. The Edge rate limit is approximate per PoP, not a strict global quota. **Do not treat P0 as complete** until the trusted client-IP path and other release checks in [the rollout checklist](../docs/cloudflare-tunnel-rollout.md) are verified.

### Tests

From repository root: `node --test cloudflare-gateway/test/*.test.mjs`

From `frontend`: `npm test` includes the Pages Service Binding tests.

Reference: [Cloudflare Workers VPC](https://developers.cloudflare.com/workers-vpc/) · [Pages Service bindings](https://developers.cloudflare.com/pages/functions/bindings/) · [Worker Rate Limiting](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).
