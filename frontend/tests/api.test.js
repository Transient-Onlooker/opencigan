import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';

test('정규 API 경로, 매개변수와 오류를 처리한다', async (t) => {
  globalThis.location = { hostname: 'localhost', origin: 'https://example.test' };
  const requests = [];
  globalThis.fetch = async (url) => {
    requests.push(url);
    return { ok: true, json: async () => ({ schools: [], records: [], meals: [] }) };
  };
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', optimizeDeps: { noDiscovery: true, include: [] } });
  try {
    const api = await server.ssrLoadModule('/src/api.ts');
    const calendar = new URL(api.timetableSubscriptionUrl('1:학교', 1, 2, 'timed', { 1: { start: '09:00', end: '09:50' } }));
    assert.equal(calendar.searchParams.get('mode'), 'timed');
    assert.equal(calendar.searchParams.get('times'), '1:0900-0950');
    await api.searchSchools('서울 학교');
    await api.searchNeisSchools('서울 학교');
    await api.getTimetable('comci/1', '2026-11-09');
    await api.getTimetableHistory('comci:학교', '2026-11-09', 'cursor / 1');
    await api.getMeals('neis/2', '2026-11-09', '2026-11-15');
    assert.deepEqual(requests, [
      '/api/v1/schools?q=%EC%84%9C%EC%9A%B8%20%ED%95%99%EA%B5%90',
      '/api/v1/neis/schools?q=%EC%84%9C%EC%9A%B8%20%ED%95%99%EA%B5%90',
      '/api/v1/timetable?school=comci%2F1&week=2026-11-09',
      '/api/v1/timetable/history?school=comci%3A%ED%95%99%EA%B5%90&week=2026-11-09&cursor=cursor%20%2F%201',
      '/api/v1/meals?school=neis%2F2&from=2026-11-09&to=2026-11-15',
    ]);
    globalThis.fetch = async () => new Response('', { status: 503 });
    await assert.rejects(api.getMeals('neis/2', '2026-11-09', '2026-11-15'), /일시적으로 이용할 수 없어요/);
    globalThis.fetch = async () => Response.json({ code: 'history_disabled' }, { status: 503 });
    await assert.rejects(api.getTimetableHistory('school', '2026-11-09'), (error) => error.code === 'history_disabled');
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await assert.rejects(api.searchSchools('서울'), /서버에 연결할 수 없어요/);

    const deadline = new AbortController();
    t.mock.method(AbortSignal, 'timeout', () => deadline.signal);
    globalThis.fetch = async (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    });
    const caller = new AbortController();
    const canceled = api.searchSchools('서울', caller.signal);
    caller.abort();
    await assert.rejects(canceled, { name: 'AbortError' });
    const pending = api.searchSchools('서울');
    deadline.abort();
    await assert.rejects(pending, /서버 응답이 늦어요/);
  } finally { await server.close(); }
});

test('client deadline can expire before an upstream response arrives', async (t) => {
  globalThis.location = { hostname: 'localhost', origin: 'https://example.test' };
  const deadline = new AbortController();
  let budget;
  t.mock.method(AbortSignal, 'timeout', (ms) => { budget = ms; return deadline.signal; });
  let finishUpstream;
  globalThis.fetch = (_url, { signal }) => new Promise((resolve, reject) => {
    finishUpstream = () => resolve(Response.json({ schools: [], stale: false }));
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
  });
  const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', optimizeDeps: { noDiscovery: true, include: [] } });
  try {
    const api = await server.ssrLoadModule('/src/api.ts');
    const pending = api.searchSchools('서울');
    assert.equal(budget, 45_000);
    deadline.abort();
    await assert.rejects(pending, /서버 응답이 늦어요/);
    finishUpstream();
  } finally { await server.close(); }
});
