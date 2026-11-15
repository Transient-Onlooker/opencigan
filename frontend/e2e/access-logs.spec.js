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
};

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

