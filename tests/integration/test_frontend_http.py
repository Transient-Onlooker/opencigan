import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from backend.app import Handler
from backend.cache import Cache
from backend.neis import Meal, School


ROOT = Path(__file__).resolve().parents[2]

NODE_TEST = r"""
const assert = require('node:assert/strict');

(async () => {
  globalThis.location = { hostname: 'localhost' };
  const { createServer } = await import('vite');
  const vite = await createServer({
    configFile: false,
    root: process.cwd(),
    envDir: process.env.TEST_TEMP_DIR,
    cacheDir: process.env.TEST_TEMP_DIR,
    server: { middlewareMode: true, hmr: false },
    appType: 'custom',
    optimizeDeps: { noDiscovery: true, include: [] },
  });
  try {
    const api = await vite.ssrLoadModule('/src/api.ts');
    assert.deepEqual(await api.searchSchools('서울 학교'), {
      schools: [{ id: '2:서울 학교', name: '서울 학교', region: '서울' }], stale: false,
    });
    assert.deepEqual(await api.searchNeisSchools('서울 학교'), {
      schools: [{ id: 'B10:1234567', name: '서울 학교', region: '고등학교', address: '서울' }], stale: false,
    });
    assert.deepEqual(await api.getTimetable('2:서울 학교', '2026-11-09'), {
      schoolId: '2:서울 학교', weekStart: '2026-11-09', records: [],
      sourceUpdatedAt: null, fetchedAt: '2026-11-10T00:00:00Z', stale: false, cacheStatus: 'miss',
    });
    assert.deepEqual(await api.getMeals('B10:1234567', '2026-11-09', '2026-11-15'), {
      meals: [{ date: '2026-11-10', type: '중식', dishes: ['밥(1)', '국(2)'], calories: null, nutrition: null, origin: null }], stale: false,
    });
    await assert.rejects(api.getMeals('invalid', '2026-11-09', '2026-11-15'), /400/);
    await assert.rejects(api.searchSchools('failure'), error => error.code === 'upstream_unavailable' && /시간표나 급식 데이터를 불러오지/.test(error.message));

    const deadlines = [];
    const originalTimeout = AbortSignal.timeout;
    const originalFetch = globalThis.fetch;
    const { pathToFileURL } = require('node:url');
    const gateway = (await import(pathToFileURL(`${process.cwd()}/../cloudflare-gateway/src/index.mjs`))).default;
    const limiter = { limit: async () => ({ success: true }) };
    const forwarded = [];
    const gatewayEnv = {
      SEARCH_RATE: limiter, GENERAL_RATE: limiter, TIMETABLE_RATE: limiter, CALENDAR_RATE: limiter,
      PRIVATE_API: { fetch: request => {
        forwarded.push(request);
        const url = new URL(request.url);
        return originalFetch(`${process.env.VITE_API_BASE_URL}${url.pathname}${url.search}`, {
          method: request.method, headers: request.headers, signal: request.signal,
        });
      } },
    };
    globalThis.fetch = (url, options) => {
      if (!String(url).startsWith(`${process.env.VITE_API_BASE_URL}/api/v1/timetable?`)) return originalFetch(url, options);
      const request = new Request(url, options);
      const work = gateway.fetch(request, gatewayEnv);
      return new Promise((resolve, reject) => {
        const abort = () => reject(request.signal.reason);
        if (request.signal.aborted) return abort();
        request.signal.addEventListener('abort', abort, { once: true });
        work.then(value => { request.signal.removeEventListener('abort', abort); resolve(value); },
                  error => { request.signal.removeEventListener('abort', abort); reject(error); });
      });
    };
    AbortSignal.timeout = (milliseconds) => {
      assert.equal(milliseconds, 15_000);
      const deadline = new AbortController();
      deadlines.push(deadline);
      return deadline.signal;
    };
    try {
      const slowRequest = api.getTimetable('2:ST01-slow', '2026-11-09');
      let slowStarted = false;
      for (let attempt = 0; attempt < 100; attempt += 1) {
        const state = await fetch(`${process.env.VITE_API_BASE_URL}/__test__/state`).then(response => response.json());
        if (state.slowStarted) {
          slowStarted = true;
          break;
        }
        await new Promise(resolve => setTimeout(resolve, 5));
      }
      assert.equal(slowStarted, true, 'the local backend should enter its delayed upstream fetch');

      deadlines[0].abort(new DOMException('Synthetic client deadline', 'TimeoutError'));
      await assert.rejects(slowRequest, /서버 응답이 늦어요/);
      assert.equal(forwarded.length, 1, 'the slow request should pass through the gateway');
      assert.equal(forwarded[0].signal.aborted, false, 'the mocked gateway should not abort the private request');
      const afterCancel = await fetch(`${process.env.VITE_API_BASE_URL}/__test__/state`).then(response => response.json());
      assert.equal(afterCancel.slowCompleted, false, 'client cancellation must not cancel backend work');

      const fastSchool = process.env.ST01_FAST_SCHOOL;
      const fast = await api.getTimetable(fastSchool, '2026-11-09');
      assert.equal(fast.schoolId, fastSchool);
      const whileSlowIsBlocked = await fetch(`${process.env.VITE_API_BASE_URL}/__test__/state`).then(response => response.json());
      assert.equal(whileSlowIsBlocked.slowCompleted, false, 'a different cache key in the same stripe should finish independently');

      await fetch(`${process.env.VITE_API_BASE_URL}/__test__/release`);
      const recovered = await api.getTimetable('2:ST01-slow', '2026-11-09');
      assert.equal(recovered.schoolId, '2:ST01-slow');
      assert.equal(recovered.cacheStatus, 'hit', 'the completed server fetch should populate cache after client cancellation');
    } finally {
      AbortSignal.timeout = originalTimeout;
      globalThis.fetch = originalFetch;
      await fetch(`${process.env.VITE_API_BASE_URL}/__test__/release`);
    }
  } finally {
    await vite.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


class FrontendHttpTests(unittest.TestCase):
    def test_frontend_client_against_local_backend(self):
        upstream_started = threading.Event()
        upstream_release = threading.Event()
        upstream_completed = threading.Event()

        def schools(query):
            if query == "failure":
                raise RuntimeError("fixture failure")
            return [{"id": "2:서울 학교", "name": query, "region": "서울"}]

        def fetch_timetable(school, week):
            if school == "2:ST01-slow":
                upstream_started.set()
                if not upstream_release.wait(10):
                    raise RuntimeError("synthetic upstream gate was not released")
                upstream_completed.set()
            return {**timetable, "schoolId": school, "weekStart": week}

        timetable = {"schoolId": "2:서울 학교", "weekStart": "2026-11-09", "records": [],
                     "sourceUpdatedAt": None, "fetchedAt": "2026-11-10T00:00:00Z", "stale": False}
        test_cache = Cache(lock_stripes=1)
        slow_school = "2:ST01-slow"
        fast_school = "2:ST01-fast"
        temp_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Temp" if os.name == "nt" else None
        with tempfile.TemporaryDirectory(prefix="opensigan-http-", dir=temp_root) as temp_dir, \
                patch("backend.app.cache", test_cache), \
                patch("backend.app.search_schools", side_effect=schools) as search, \
                patch("backend.app.validate_timetable_week") as validate, \
                patch("backend.app.fetch_timetable", side_effect=fetch_timetable) as fetch_timetable_mock, \
                patch("backend.app.NEISClient.from_environment") as neis, \
                patch.dict(os.environ, {"NEIS_API_KEY": "fixture-key"}):
            neis.return_value.search_schools.return_value = [School("B10", "1234567", "서울 학교", "고등학교", "서울")]
            neis.return_value.get_meals.return_value = [Meal("2026-11-10", "중식", "밥(1)<br/>국(2)")]
            class BoundaryHandler(Handler):
                def do_GET(self):
                    if self.path == "/__test__/state":
                        body = json.dumps({"slowStarted": upstream_started.is_set(),
                                           "slowCompleted": upstream_completed.is_set()}).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    elif self.path == "/__test__/release":
                        upstream_release.set()
                        self.send_response(204)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        try:
                            super().do_GET()
                        except (BrokenPipeError, ConnectionAbortedError):
                            pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), BoundaryHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                env = {key: value for key, value in os.environ.items() if not key.startswith("VITE_")}
                env.update(VITE_API_BASE_URL=f"http://127.0.0.1:{server.server_port}",
                           TEST_TEMP_DIR=temp_dir, ST01_FAST_SCHOOL=fast_school, TEMP=temp_dir, TMP=temp_dir)
                result = subprocess.run(["node", "-e", NODE_TEST], cwd=ROOT / "frontend", env=env,
                                        capture_output=True, text=True, encoding="utf-8", timeout=45)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual([call.args[0] for call in search.call_args_list], ["서울 학교", "failure"])
                neis.return_value.search_schools.assert_called_once_with("서울 학교")
                self.assertEqual(validate.call_count, 4)
                self.assertTrue(all(call.args == ("2026-11-09",) for call in validate.call_args_list))
                self.assertEqual([call.args for call in fetch_timetable_mock.call_args_list], [
                    ("2:서울 학교", "2026-11-09"),
                    ("2:ST01-slow", "2026-11-09"),
                    (fast_school, "2026-11-09"),
                ])
                self.assertTrue(upstream_started.is_set())
                self.assertTrue(upstream_completed.is_set())
                meal_args = neis.return_value.get_meals.call_args.args
                self.assertEqual((meal_args[0].office_code, meal_args[0].school_code), ("B10", "1234567"))
                self.assertEqual(tuple(map(str, meal_args[1:])), ("2026-11-09", "2026-11-15"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    unittest.main()
