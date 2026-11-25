import { test } from 'node:test';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';
import { createServer } from 'vite';

test('actual client deadline interrupts a stalled request', { skip: process.env.OPENCIGAN_SLOW_NETWORK_TESTS !== '1' }, async () => {
  const previousLocation = globalThis.location;
  const previousFetch = globalThis.fetch;
  globalThis.location = { hostname: 'localhost', origin: 'https://example.test' };
  globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  });
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', optimizeDeps: { noDiscovery: true, include: [] } });
  try {
    const api = await server.ssrLoadModule('/src/api.ts');
    const start = performance.now();
    await assert.rejects(api.searchSchools('example'), /서버 응답이 늦어요/);
    const elapsed = performance.now() - start;
    assert.ok(elapsed >= 14_500 && elapsed < 25_000, `client timeout took ${elapsed}ms`);
  } finally {
    globalThis.fetch = previousFetch;
    globalThis.location = previousLocation;
    await server.close();
  }
});
