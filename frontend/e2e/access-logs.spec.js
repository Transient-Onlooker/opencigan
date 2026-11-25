import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const log = {
  id: 42,
  timestamp: '2026-11-15T13:45:00+09:00',
  client_ip: '203.0.113.9',
  method: 'GET',
  route: '/api/v1/timetable',
  school_id: 'B10:1234567',
  grade: '2',
  class_nm: '3',
  week: '2026-11-09',
  dates: '2026-11-09,2026-11-10',
  datatype: 'timetable',
  status: 200,
  duration_ms: 12.5,
  cache_status: 'hit',
  referrer_origin: 'https://school.example',
  origin_class: 'frontend',
  user_agent: '<img src=x onerror=alert(1)>',
};

test('editing the token cancels an in-flight log query and clears previous rows', async ({ page }) => {
  let release, started, count = 0;
  const pending = new Promise(resolve => { release = resolve; });
  const requested = new Promise(resolve => { started = resolve; });
  await page.route('**/api/v1/admin/access-logs**', async route => {
    count++;
    if (count === 2) { started(); await pending; }
    try { await route.fulfill({ json: { items: [log], next_cursor: null, limit: 50, has_more: false } }); } catch { /* Request may be canceled. */ }
  });
  await page.goto('/access-logs.html');
  await page.getByLabel('관리자 토큰').fill('first-token');
  await page.getByRole('button', { name: '조회', exact: true }).click();
  await expect(page.locator('#logs-body')).toContainText(log.client_ip);
  await page.getByRole('button', { name: '조회', exact: true }).click();
  await requested;
  const canceled = page.waitForEvent('requestfailed', request => request.url().includes('/api/v1/admin/access-logs'));
  await page.getByLabel('관리자 토큰').fill('second-token');
  release();
  await canceled;
  await expect(page.locator('#results')).toBeHidden();
  await expect(page.locator('#logs-body')).toBeEmpty();
  await expect(page.getByRole('button', { name: '조회', exact: true })).toBeEnabled();
});

test('anomaly review remains hidden by default', async ({ page }) => {
  test.skip(process.env.VITE_ACCESS_ANOMALIES_ENABLED === '1', 'Only applies to the default build');
  await page.goto('/access-logs.html');
  await expect(page.locator('#anomaly-review')).toBeHidden();
});

test('enabled anomaly review authenticates, safely renders and clears on lock', async ({ page }) => {
  test.skip(process.env.VITE_ACCESS_ANOMALIES_ENABLED !== '1', 'Requires opt-in build');
  let request;
  await page.route('**/api/v1/admin/access-anomalies**', async route => {
    request = route.request();
    await route.fulfill({ json: { findings: [{ client_ip: '<img src=x onerror=alert(1)>', kind: 'status_errors', status_group: '429', observed: 5, threshold: 3 }] } });
  });
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/access-logs.html');
  await page.getByLabel('관리자 토큰').fill('test-secret');
  await page.getByLabel('IP별 요청 수 기준').fill('25');
  await page.getByLabel('오류 비율 기준').fill('0.25');
  await page.getByLabel('서로 다른 학교 수 기준').fill('4');
  await page.getByLabel('상태별 오류 기준 (선택)').fill('3');
  await page.getByRole('button', { name: '이상 조회 검토' }).click();
  await expect(page.locator('#anomaly-results')).toContainText('429');
  await expect(page.locator('#anomaly-results')).toContainText('상태별 오류 수');
  await expect(page.locator('#anomaly-results img')).toHaveCount(0);
  expect(request.headers().authorization).toBe('Bearer test-secret');
  expect(request.url()).not.toContain('test-secret');
  expect(new URL(request.url()).searchParams.get('max_status_errors')).toBe('3');
  expect(new URL(request.url()).searchParams.get('max_requests_per_ip')).toBe('25');
  expect(new URL(request.url()).searchParams.get('max_error_ratio')).toBe('0.25');
  expect(new URL(request.url()).searchParams.get('max_distinct_schools')).toBe('4');
  expect(await page.evaluate(() => JSON.stringify({ local: localStorage, session: sessionStorage, url: location.href }))).not.toContain('test-secret');
  await page.getByRole('button', { name: '잠금' }).click();
  await expect(page.locator('#anomaly-results')).toBeEmpty();
  await expect(page.getByLabel('관리자 토큰')).toHaveValue('');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test('locking during anomaly review prevents a late result from appearing', async ({ page }) => {
  test.skip(process.env.VITE_ACCESS_ANOMALIES_ENABLED !== '1', 'Requires opt-in build');
  let release, started;
  const pending = new Promise(resolve => { release = resolve; });
  const requested = new Promise(resolve => { started = resolve; });
  await page.route('**/api/v1/admin/access-anomalies**', async route => {
    started();
    await pending;
    try { await route.fulfill({ json: { findings: [{ client_ip: '203.0.113.9', kind: 'request_volume', observed: 10, threshold: 5 }] } }); } catch { /* The request may be canceled. */ }
  });
  await page.goto('/access-logs.html');
  await page.getByLabel('관리자 토큰').fill('test-secret');
  await page.getByRole('button', { name: '이상 조회 검토' }).click();
  await requested;
  await page.getByRole('button', { name: '잠금' }).click();
  release();
  await expect(page.locator('#anomaly-results')).toBeEmpty();
  await expect(page.getByLabel('관리자 토큰')).toHaveValue('');
});

test('anomaly review explains authentication, rate limit and availability failures', async ({ page }) => {
  test.skip(process.env.VITE_ACCESS_ANOMALIES_ENABLED !== '1', 'Requires opt-in build');
  let status = 401;
  await page.route('**/api/v1/admin/access-anomalies**', route => route.fulfill({ status, json: { error: 'unavailable' } }));
  await page.goto('/access-logs.html');
  await page.getByLabel('관리자 토큰').fill('test-secret');
  for (const [code, message] of [[401, '관리자 토큰을 확인'], [429, '요청이 많아요'], [503, '이상 조회 검토를 사용할 수 없습니다']]) {
    status = code;
    await page.getByRole('button', { name: '이상 조회 검토' }).click();
    await expect(page.locator('#anomaly-state')).toContainText(message);
    await expect(page.locator('#anomaly-results')).toBeEmpty();
  }
});

test('filters, authenticated query, lock clears rows, and CSV uses authenticated fetch', async ({ page }) => {
  const requests = [];
  await page.route('**/api/v1/admin/access-logs**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({ url, headers: request.headers() });

    if (url.searchParams.get('format') === 'csv') {
      return route.fulfill({
        status: 200,
        contentType: 'text/csv; charset=utf-8',
        body: 'timestamp,client_ip\n2026-11-15,203.0.113.9\n',
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify({ items: [log], next_cursor: null, limit: 50, has_more: false, dropped: 0 }),
    });
  });

  await page.goto('/access-logs.html');
  await page.getByLabel('관리자 토큰').fill('test-token');
  await page.getByLabel('클라이언트 IP').fill(log.client_ip);
  await page.getByLabel('학교 ID').fill(log.school_id);
  await page.getByLabel('학년').fill('2');
  await page.getByLabel('반', { exact: true }).fill('3');
  await page.getByLabel('시작일 (KST)').fill('2026-11-01');
  await page.getByLabel('종료일 (KST)').fill('2026-11-15');
  await page.getByLabel('경로 (Route)').fill(log.route);
  await page.getByLabel('HTTP 상태 코드').fill('200');
  await page.getByLabel('출처 분류').selectOption('frontend');
  await page.getByLabel('캐시 상태').selectOption('hit');
  await page.getByRole('button', { name: '조회', exact: true }).click();

  await expect(page.getByRole('table')).toContainText(log.client_ip);
  await expect(page.getByRole('table')).toContainText(log.user_agent);
  await expect(page.locator('#logs-body img')).toHaveCount(0);
  expect(requests).toHaveLength(1);
  const query = requests[0].url.searchParams;
  for (const [key, value] of Object.entries({
    client_ip: log.client_ip,
    school_id: log.school_id,
    grade: '2',
    class: '3',
    start_day: '2026-11-01',
    end_day: '2026-11-15',
    route: log.route,
    status: '200',
    origin_class: 'frontend',
    cache_status: 'hit',
    limit: '50',
  })) {
    expect(query.get(key)).toBe(value);
  }
  expect(requests[0].headers.authorization).toBe('Bearer test-token');
  expect(requests[0].headers.referer).toBeUndefined();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'CSV 다운로드' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe('opencigan-access.csv');
  expect(requests).toHaveLength(2);
  expect(requests[1].url.searchParams.get('format')).toBe('csv');
  expect(requests[1].url.searchParams.get('cursor')).toBeNull();
  expect(requests[1].headers.authorization).toBe('Bearer test-token');

  await page.getByRole('button', { name: '잠금' }).click();
  await expect(page.locator('#token')).toHaveValue('');
  await expect(page.locator('#results')).toBeHidden();
  await expect(page.locator('#logs-body tr')).toHaveCount(0);
});

test('rejects a wrong token and keeps the response out of the results table', async ({ page }) => {
  let authorization = '';
  await page.route('**/api/v1/admin/access-logs**', async (route) => {
    authorization = route.request().headers().authorization;
    return route.fulfill({ status: 401, body: JSON.stringify({ code: 'unauthorized' }) });
  });

  await page.goto('/access-logs.html');
  await page.getByLabel('관리자 토큰').fill('wrong-token');
  await page.getByRole('button', { name: '조회', exact: true }).click();

  await expect(page.locator('#state')).toContainText('관리자 토큰을 확인');
  await expect(page.locator('#results')).toBeHidden();
  expect(authorization).toBe('Bearer wrong-token');
});

