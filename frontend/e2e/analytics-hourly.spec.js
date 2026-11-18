import { test, expect } from '@playwright/test';

test('admin hourly diagnostics show data, support older servers, and clear on lock', async ({ page }) => {
  const summary = {
    visitors: 0, sessions: 0, pageViews: 0, apiRequests: 2, apiErrorRate: 0.5,
    apiAverageMs: 10, droppedApiEvents: 0, daily: [], routes: [
      { route: '/api/v1/timetable', requests: 2, errors: 1, avg_ms: 10, data_failures: 1, overload_errors: 0, unclassified_server_errors: 0 },
      { route: '/api/v1/meals', requests: 1, errors: 0, avg_ms: 5 },
    ],
    apiHourly: [{ hour: '2026-11-18T11:00:00+09:00', requests: 2, errors: 1,
      upstream_errors: 1, overload_errors: 0, cache_hits: 1, stale_responses: 0 }],
  };
  await page.route('**/api/v1/admin/analytics?*', (route) => route.fulfill({ json: summary }));
  await page.goto('/analytics.html');
  await page.getByLabel('관리자 토큰').fill('test-token');
  await page.getByRole('button', { name: '조회 / 새로고침' }).click();
  const table = page.getByRole('region', { name: '시간대별 API 상태 표' });
  await expect(table).toBeVisible();
  await expect(table.locator('tbody tr')).toHaveCount(1);
  await expect(table).toContainText('2026-11-18 11:00');
  await expect(table.locator('tbody tr').locator('td')).toHaveText(['2026-11-18 11:00', '2', '1', '1', '0', '1', '0']);
  const routes = page.getByRole('region', { name: '경로별 통계 표' }).locator('tbody tr');
  await expect(routes.nth(0).locator('td')).toHaveText(['/api/v1/timetable', '2', '1', '1', '0', '0', '10']);
  await expect(routes.nth(1).locator('td')).toHaveText(['/api/v1/meals', '1', '0', '—', '—', '—', '5']);
  await page.getByRole('button', { name: '잠금' }).click();
  await expect(page.locator('#hourly tr')).toHaveCount(0);
  await expect(page.getByLabel('관리자 토큰')).toHaveValue('');
  delete summary.apiHourly;
  await page.getByLabel('관리자 토큰').fill('test-token');
  await page.getByRole('button', { name: '조회 / 새로고침' }).click();
  await expect(page.locator('#hourly-state')).toHaveText('현재 서버에서는 시간대별 통계를 제공하지 않습니다.');
  await expect(table).toBeHidden();
  summary.apiHourly = [];
  await page.getByRole('button', { name: '조회 / 새로고침' }).click();
  await expect(page.locator('#hourly-state')).toHaveText('최근 24시간에 기록된 API 요청이 없습니다.');
});
