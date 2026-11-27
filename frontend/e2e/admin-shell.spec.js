import { test, expect } from '@playwright/test';

test('admin login, charts, navigation and lock keep credentials out of URLs and storage', async ({ page }) => {
  const requests = [];
  await page.route('**/api/v1/admin/analytics?**', async (route) => {
    requests.push(route.request().headers().authorization);
    await route.fulfill({ json: {
      visitors: 2, sessions: 3, pageViews: 4, apiRequests: 5, apiErrorRate: 0,
      apiAverageMs: 10, droppedApiEvents: 0,
      daily: [{ day: '2026-11-27', visitors: 2, sessions: 3, page_views: 4, api_requests: 5 }],
      routes: [{ route: '/api/v1/timetable', requests: 5, errors: 0, avg_ms: 10 }],
      apiHourly: [{ hour: '2026-11-27T13:00:00+09:00', requests: 5, errors: 0, upstream_errors: 0, overload_errors: 0, cache_hits: 3, stale_responses: 0 }],
    } });
  });
  await page.route('**/api/v1/admin/suggestions?**', async (route) => {
    await route.fulfill({ json: { suggestions: [{ id: 'a'.repeat(24), title: '<b>테스트</b>', description: '설명', context: null, status: 'pending', created_at: '2026-11-27', reviewed_at: null, merged_into: null, reviewer_note: null }], nextCursor: null } });
  });
  await page.route('**/api/v1/status', async (route) => route.fulfill({ json: { status: 'ok', scope: 'process liveness' } }));
  await page.route('**/api/v1/admin/school-usage?**', async (route) => route.fulfill({ json: { start_day: '2026-11-21', end_day: '2026-11-27', has_more: false, items: [{ datatype: 'timetable', school_id: '123:샘플학교', school_name: '샘플학교', requests: 12 }] } }));
  await page.goto('/admin/');
  await expect(page.locator('#admin-workspace')).toBeHidden();
  await page.locator('#admin-token').fill('example-admin-token');
  await page.getByRole('button', { name: '잠금 해제' }).click();
  const analytics = page.frameLocator('iframe[title="이용 통계"]');
  await expect(analytics.locator('#charts svg')).toHaveCount(7);
  await expect(analytics.locator('#metrics').getByText('미제공')).toHaveCount(6);
  expect(requests).toEqual(['Bearer example-admin-token', 'Bearer example-admin-token']);
  await page.getByRole('button', { name: '접속 로그' }).click();
  await expect(page.frameLocator('iframe[title="접속 로그"]').locator('#token')).toHaveValue('example-admin-token');
  await page.getByRole('button', { name: '기능 제안' }).click();
  await expect(page.getByRole('heading', { name: '<b>테스트</b>' })).toBeVisible();
  await expect(page.locator('#admin-content b')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '승인', exact: true })).toBeEnabled();
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: '승인', exact: true }).click();
  await expect(page.getByRole('heading', { name: '<b>테스트</b>' })).toBeVisible();
  await page.getByRole('button', { name: '서비스 상태' }).click();
  await expect(page.getByText('백엔드 프로세스 응답 정상')).toBeVisible();
  await page.getByRole('button', { name: '학교별 조회' }).click();
  await expect(page.getByRole('cell', { name: '샘플학교', exact: true })).toBeVisible();
  await expect(page.locator('.school-bar')).toHaveCount(1);
  await page.getByRole('button', { name: '시간표 관측' }).click();
  await expect(page.getByText('시간표 관측 통계가 이 배포에서 활성화되지 않았습니다.')).toBeVisible();
  await page.getByRole('button', { name: '이상 접근' }).click();
  await expect(page.getByText('이상 접근 검토가 이 배포에서 활성화되지 않았습니다.')).toBeVisible();
  await page.getByRole('button', { name: '잠금', exact: true }).click();
  await expect(page.locator('iframe')).toHaveCount(0);
  await expect(page.locator('#admin-content')).toBeEmpty();
  await expect(page.locator('#admin-token')).toBeEmpty();
  expect(page.url()).not.toContain('example-admin-token');
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain('example-admin-token');
});

test('rejects invalid admin credentials without showing a workspace', async ({ page }) => {
  await page.route('**/api/v1/admin/analytics?**', (route) => route.fulfill({ status: 401, json: { code: 'unauthorized' } }));
  await page.goto('/admin/');
  await page.locator('#admin-token').fill('invalid-token');
  await page.getByRole('button', { name: '잠금 해제' }).click();
  await expect(page.locator('#admin-state')).toHaveText('관리자 토큰을 확인해 주세요.');
  await expect(page.locator('#admin-workspace')).toBeHidden();
  await expect(page.locator('iframe')).toHaveCount(0);
});

test('locking discards an in-flight embedded request', async ({ page }) => {
  let seen = 0;
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  await page.route('**/api/v1/admin/analytics?**', async (route) => {
    seen++;
    if (seen > 1) await waiting;
    await route.fulfill({ json: { visitors: 1, sessions: 1, pageViews: 1, apiRequests: 1, apiErrorRate: 0, apiAverageMs: 0, droppedApiEvents: 0, daily: [], routes: [] } }).catch(() => {});
  });
  await page.goto('/admin/');
  await page.locator('#admin-token').fill('example-admin-token');
  await page.getByRole('button', { name: '잠금 해제' }).click();
  await expect.poll(() => seen).toBe(2);
  await page.getByRole('button', { name: '잠금', exact: true }).click();
  release();
  await expect(page.locator('#admin-workspace')).toBeHidden();
  await expect(page.locator('#admin-content')).toBeEmpty();
});
