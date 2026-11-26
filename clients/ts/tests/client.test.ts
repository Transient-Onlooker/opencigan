import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { OpensiganClient, OpensiganError } from '../index.ts';

test('OpensiganClient query encoding and URL construction', async () => {
  const requests: { url: string; headers: Record<string, string> }[] = [];
  const mockFetch = async (url: string | URL | Request, init?: RequestInit): Promise<Response> => {
    requests.push({ url: url.toString(), headers: (init?.headers as Record<string, string>) ?? {} });
    return new Response(JSON.stringify({ status: 'ok', scope: 'process liveness' }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  const client = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: mockFetch,
  });

  // 1. Status
  await client.getStatus();
  assert.equal(requests[0].url, 'http://127.0.0.1:8000/api/v1/status');

  // 2. School search with special chars (&, +, #, %, spaces)
  await client.searchSchools('서울&경기+고등학교#1 100%');
  assert.equal(
    requests[1].url,
    'http://127.0.0.1:8000/api/v1/schools?q=' + encodeURIComponent('서울&경기+고등학교#1 100%')
  );

  // 3. Timetable query with filters
  await client.getTimetable('1234:한국+고등학교&본관', '2026-11-16', {
    grade: 2,
    class: 3,
    teacher: '김&이 선생님',
  });
  const parsedTimetableUrl = new URL(requests[2].url);
  assert.equal(parsedTimetableUrl.pathname, '/api/v1/timetable');
  assert.equal(parsedTimetableUrl.searchParams.get('school'), '1234:한국+고등학교&본관');
  assert.equal(parsedTimetableUrl.searchParams.get('week'), '2026-11-16');
  assert.equal(parsedTimetableUrl.searchParams.get('grade'), '2');
  assert.equal(parsedTimetableUrl.searchParams.get('class'), '3');
  assert.equal(parsedTimetableUrl.searchParams.get('teacher'), '김&이 선생님');
  await client.getTimetable('1234:학교', '2026-11-16', { teacher: ' ' });
  assert.equal(new URL(requests.pop()!.url).searchParams.get('teacher'), ' ');
  await client.searchNeisSchools('학교&검색');
  const neisUrl = new URL(requests.pop()!.url);
  assert.equal(neisUrl.pathname, '/api/v1/neis/schools');
  assert.equal(neisUrl.searchParams.get('q'), '학교&검색');

  // 4. Meals with 7-day range
  await client.getMeals('B10:1234567', '2026-11-16', '2026-11-22');
  const parsedMealsUrl = new URL(requests[3].url);
  assert.equal(parsedMealsUrl.pathname, '/api/v1/meals');
  assert.equal(parsedMealsUrl.searchParams.get('school'), 'B10:1234567');
  assert.equal(parsedMealsUrl.searchParams.get('from'), '2026-11-16');
  assert.equal(parsedMealsUrl.searchParams.get('to'), '2026-11-22');

  // 5. History with opaque cursor containing special characters
  await client.getTimetableHistory('1234:학교', '2026-11-16', { cursor: 'cursor/token+123==&foo' });
  const parsedHistoryUrl = new URL(requests[4].url);
  assert.equal(parsedHistoryUrl.pathname, '/api/v1/timetable/history');
  assert.equal(parsedHistoryUrl.searchParams.get('school'), '1234:학교');
  assert.equal(parsedHistoryUrl.searchParams.get('week'), '2026-11-16');
  assert.equal(parsedHistoryUrl.searchParams.get('cursor'), 'cursor/token+123==&foo');

  // 6. ICS URL generation for both modes
  const icsPeriods = client.getTimetableIcsUrl('1234:학교', 1, 2, { weeks: 1, mode: 'periods', teacher: '박' });
  const icsSummary = client.getTimetableIcsUrl('1234:학교', 1, 2, { weeks: 2, mode: 'summary' });
  const icsTimed = client.getTimetableIcsUrl('1234:학교', 1, 2, {
    weeks: 2,
    mode: 'timed',
    times: '1:0900-0950,2:1000-1050',
    weekdayTimes: '2.1:1000-1050,3.2:1100-1150',
  });
  const parsedIcsPeriods = new URL(icsPeriods);
  assert.equal(parsedIcsPeriods.searchParams.get('mode'), 'periods');
  assert.equal(parsedIcsPeriods.searchParams.get('weeks'), '1');
  assert.equal(parsedIcsPeriods.searchParams.get('teacher'), '박');
  const parsedIcsSummary = new URL(icsSummary);
  assert.equal(parsedIcsSummary.searchParams.get('mode'), 'summary');
  assert.equal(parsedIcsSummary.searchParams.get('weeks'), '2');
  const parsedIcsTimed = new URL(icsTimed);
  assert.equal(parsedIcsTimed.searchParams.get('mode'), 'timed');
  assert.equal(parsedIcsTimed.searchParams.get('weeks'), '2');
  assert.equal(parsedIcsTimed.searchParams.get('times'), '1:0900-0950,2:1000-1050');
  assert.equal(parsedIcsTimed.searchParams.get('weekday_times'), '2.1:1000-1050,3.2:1100-1150');
});

test('malformed success JSON is structured; HTTP error status survives invalid JSON', async () => {
  for (const body of ['<html>not JSON</html>', '', 'null', '[]']) {
    const client = new OpensiganClient({ fetch: async () => new Response(body) });
    await assert.rejects(client.getStatus(), {
      name: 'OpensiganError', status: 200, code: 'invalid_response',
    });
  }
  const client = new OpensiganClient({ fetch: async () => new Response('not JSON', { status: 429 }) });
  await assert.rejects(client.getStatus(), { name: 'OpensiganError', status: 429 });
});

test('HTTP errors retain Retry-After for JSON and calendar requests', async () => {
  for (const [status, retryAfter, body] of [
    [429, '30', '{"error":"limited","code":"rate_limited"}'],
    [503, 'Wed, 25 Nov 2026 12:00:00 GMT', 'unavailable'],
  ] as const) {
    const client = new OpensiganClient({ fetch: async () => new Response(body, { status, headers: { 'Retry-After': retryAfter } }) });
    for (const request of [() => client.getStatus(), () => client.getTimetableIcs('1:school', 1, 1)]) {
      await assert.rejects(request(), { name: 'OpensiganError', status, retryAfter });
    }
  }
});

test('configuration rejects invalid base URLs and deadlines without exposing them', async () => {
  for (const baseUrl of ['/relative', 'file:///tmp/feed', 'https://user:secret@example.com', 'https://example.com?token=secret', 'https://example.com#secret']) {
    assert.throws(() => new OpensiganClient({ baseUrl }), (error) => {
      assert.equal(error.code, 'invalid_config');
      assert.doesNotMatch(error.message, /secret/);
      return true;
    });
  }
  for (const timeoutMs of [0, -1, NaN, Infinity, 0.5, 2_147_483_648]) {
    assert.throws(() => new OpensiganClient({ timeoutMs }), { code: 'invalid_config' });
    await assert.rejects(new OpensiganClient().getStatus({ timeoutMs }), { code: 'invalid_config' });
  }
  assert.equal(new OpensiganClient({ baseUrl: 'https://example.com/proxy/' }).baseUrl, 'https://example.com/proxy');
});

test('HTTP deadline and caller cancellation cover JSON, ICS and error bodies', async () => {
  let received;
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'Content-Type': 'application/json' });
    response.flushHeaders();
    response.write('{');
    received?.();
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  const client = new OpensiganClient({ baseUrl: `http://127.0.0.1:${address.port}`, timeoutMs: 2000 });
  try {
    for (const calendar of [false, true]) {
      const pending = calendar
        ? client.getTimetableIcs('2:학교', 1, 1, { timeoutMs: 100 })
        : client.getStatus({ timeoutMs: 100 });
      await assert.rejects(pending, { name: 'OpensiganError', status: 200, isTimeout: true });
    }
    const controller = new AbortController();
    const headersReceived = new Promise<void>((resolve) => { received = resolve; });
    const pending = client.getStatus({ signal: controller.signal });
    await headersReceived;
    controller.abort();
    await assert.rejects(pending, { name: 'AbortError' });

    const alreadyAborted = new AbortController();
    alreadyAborted.abort();
    await assert.rejects(client.getStatus({ signal: alreadyAborted.signal }), { name: 'AbortError' });

    server.removeAllListeners('request');
    server.on('request', (_request, response) => {
      response.writeHead(503, { 'Content-Type': 'application/json' });
      response.flushHeaders();
      response.write('{');
    });
    await assert.rejects(client.getStatus({ timeoutMs: 40 }), { isTimeout: true });
    server.removeAllListeners('request');
    server.on('request', () => {});
    await assert.rejects(client.getStatus({ timeoutMs: 40 }), { isTimeout: true });
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
});

test('network errors omit raw fetch URLs and causes', async () => {
  const client = new OpensiganClient({
    fetch: async () => { throw new TypeError('GET https://example.com/?token=secret'); },
  });
  await assert.rejects(client.getStatus(), (error) => {
    assert.equal(error.isNetworkError, true);
    assert.doesNotMatch(error.message, /secret|https/);
    assert.equal(error.cause, undefined);
    return true;
  });
});

test('OpensiganClient error code handling and boundary responses', async () => {
  // 1. JSON 400 invalid_request error
  const client400 = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: (async () => new Response(JSON.stringify({ error: '주 시작일이 올바르지 않습니다', code: 'invalid_request' }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    })),
  });
  await assert.rejects(client400.getTimetable('1234:학교', '2026-11-17'), (err: any) => {
    assert.ok(err instanceof OpensiganError);
    assert.equal(err.status, 400);
    assert.equal(err.code, 'invalid_request');
    assert.match(err.message, /주 시작일이 올바르지 않습니다/);
    return true;
  });

  // 2. 503 history_disabled error
  const client503History = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: (async () => new Response(JSON.stringify({ error: '변경 이력 저장이 활성화되지 않았습니다', code: 'history_disabled' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    })),
  });
  await assert.rejects(client503History.getTimetableHistory('1234:학교', '2026-11-16'), (err: any) => {
    assert.ok(err instanceof OpensiganError);
    assert.equal(err.status, 503);
    assert.equal(err.code, 'history_disabled');
    return true;
  });

  // 3. Non-JSON HTTP 502/503 upstream error
  const client502Html = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: (async () => new Response('<html>502 Bad Gateway</html>', {
      status: 502,
      headers: { 'Content-Type': 'text/html' },
    })),
  });
  await assert.rejects(client502Html.getStatus(), (err: any) => {
    assert.ok(err instanceof OpensiganError);
    assert.equal(err.status, 502);
    assert.equal(err.code, undefined);
    return true;
  });

  // 4. ICS 304 Not Modified
  const client304 = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: (async (_url, init) => {
      const reqHeaders = (init?.headers as Record<string, string>) || {};
      if (reqHeaders['If-None-Match'] === '"etag-123"') {
        return new Response(null, { status: 304, headers: { ETag: '"etag-123"' } });
      }
      return new Response('BEGIN:VCALENDAR\r\nEND:VCALENDAR', {
        status: 200,
        headers: { ETag: '"etag-123"', 'Content-Type': 'text/calendar' },
      });
    }),
  });
  const initialIcs = await client304.getTimetableIcs('1234:학교', 1, 1);
  assert.equal(initialIcs.notModified, false);
  assert.equal(initialIcs.etag, '"etag-123"');
  assert.match(initialIcs.data!, /VCALENDAR/);

  const cachedIcs = await client304.getTimetableIcs('1234:학교', 1, 1, { ifNoneMatch: '"etag-123"' });
  assert.equal(cachedIcs.notModified, true);
  assert.equal(cachedIcs.data, null);
  assert.equal(cachedIcs.etag, '"etag-123"');

  // 4b. ICS timed mode and ETag revalidation with times
  let requestedTimes: string | null = null;
  const clientTimed = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: (async (url, init) => {
      const parsed = new URL(url.toString());
      requestedTimes = parsed.searchParams.get('times');
      const reqHeaders = (init?.headers as Record<string, string>) || {};
      if (reqHeaders['If-None-Match'] === '"etag-timed"') {
        return new Response(null, { status: 304, headers: { ETag: '"etag-timed"' } });
      }
      return new Response('BEGIN:VCALENDAR\r\nDTSTART:20261109T000000Z\r\nEND:VCALENDAR', {
        status: 200,
        headers: { ETag: '"etag-timed"', 'Content-Type': 'text/calendar' },
      });
    }),
  });
  const timedIcs = await clientTimed.getTimetableIcs('1234:학교', 1, 1, {
    mode: 'timed',
    times: '1:0900-0950,2:1000-1050',
  });
  assert.equal(requestedTimes, '1:0900-0950,2:1000-1050');
  assert.equal(timedIcs.notModified, false);
  assert.equal(timedIcs.etag, '"etag-timed"');
  assert.match(timedIcs.data!, /DTSTART:20261109T000000Z/);

  const timedIcsCached = await clientTimed.getTimetableIcs('1234:학교', 1, 1, {
    mode: 'timed',
    times: '1:0900-0950,2:1000-1050',
    ifNoneMatch: '"etag-timed"',
  });
  assert.equal(timedIcsCached.notModified, true);
  assert.equal(timedIcsCached.data, null);
  assert.equal(timedIcsCached.etag, '"etag-timed"');

  // 4c. Timed mode query encoding with special characters and multiple periods
  let capturedUrl: string = '';
  const clientTimedUrl = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: (async (url) => {
      capturedUrl = url.toString();
      return new Response('BEGIN:VCALENDAR\r\nEND:VCALENDAR', {
        status: 200,
        headers: { ETag: '"etag-multi"', 'Content-Type': 'text/calendar' },
      });
    }),
  });
  await clientTimedUrl.getTimetableIcs('1234:학교&본관', 1, 2, {
    weeks: 2,
    mode: 'timed',
    times: '1:0900-0950,2:1000-1050',
  });
  const parsedCaptured = new URL(capturedUrl);
  assert.equal(parsedCaptured.searchParams.get('school'), '1234:학교&본관');
  assert.equal(parsedCaptured.searchParams.get('mode'), 'timed');
  assert.equal(parsedCaptured.searchParams.get('times'), '1:0900-0950,2:1000-1050');

  // 5. Network TypeError
  const clientNetworkErr = new OpensiganClient({
    baseUrl: 'http://127.0.0.1:8000',
    fetch: async () => { throw new TypeError('Failed to fetch'); },
  });
  await assert.rejects(clientNetworkErr.getStatus(), (err: any) => {
    assert.ok(err instanceof OpensiganError);
    assert.equal(err.isNetworkError, true);
    return true;
  });
});
