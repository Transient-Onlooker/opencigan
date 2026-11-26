import { test, expect } from '@playwright/test';

test('admin hourly diagnostics show data, support older servers, and clear on lock', async ({ page }) => {
  const summary = {
    visitors: 0, sessions: 0, pageViews: 0, apiRequests: 2, apiErrorRate: 0.5,
    apiAverageMs: 10, droppedApiEvents: 0, daily: [], routes: [
      { route: '/api/v1/timetable', requests: 2, errors: 1, avg_ms: 10, data_failures: 1, overload_errors: 0, unclassified_server_errors: 0 },
      { route: '/api/v1/meals', requests: 1, errors: 0, avg_ms: 5 },
    ],
    refreshObservations: { timetable: { result: 'failure', origin: 'calendar', observedAt: '2026-11-18T02:00:00+00:00', lastSuccessAt: '2026-11-18T01:00:00+00:00', lastFailureAt: '2026-11-18T02:00:00+00:00', durationMs: 1250 }, meals: { result: 'not_cached', observedAt: '2026-11-18T02:00:00+00:00' } },
    cacheWaitObservations: { timetable: { waitMs: 320, observedAt: '2026-11-18T02:01:00+00:00' } },
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
  const observations = page.getByRole('region', { name: '데이터 갱신 관측 표' });
  await expect(observations).toContainText('아직 관측 없음');
  await expect(observations).toContainText('실패');
  await expect(observations).toContainText('응답 수신 · 캐시 저장 불가');
  const timetableObservation = observations.locator('tbody tr').nth(1).locator('td');
  await expect(timetableObservation.nth(1)).toHaveText('캘린더 구독');
  await expect(timetableObservation.nth(4)).not.toHaveText('—');
  await expect(timetableObservation.nth(5)).not.toHaveText('—');
  await expect(timetableObservation.nth(6)).toHaveText('1,250 ms');
  await expect(timetableObservation.nth(7)).toHaveText('320 ms');
  await expect(timetableObservation.nth(8)).not.toHaveText('—');
  const oldServerObservation = observations.locator('tbody tr').nth(3).locator('td');
  await expect(oldServerObservation.nth(1)).toHaveText('—');
  await expect(oldServerObservation.nth(4)).toHaveText('—');
  await expect(oldServerObservation.nth(5)).toHaveText('—');
  await expect(oldServerObservation.nth(6)).toHaveText('—');
  await page.getByRole('button', { name: '잠금' }).click();
  await expect(page.locator('#hourly tr')).toHaveCount(0);
  await expect(page.locator('#refresh-observations tr')).toHaveCount(0);
  await expect(page.getByLabel('관리자 토큰')).toHaveValue('');
  delete summary.apiHourly;
  delete summary.refreshObservations;
  await page.getByLabel('관리자 토큰').fill('test-token');
  await page.getByRole('button', { name: '조회 / 새로고침' }).click();
  await expect(page.locator('#hourly-state')).toHaveText('현재 서버에서는 시간대별 통계를 제공하지 않습니다.');
  await expect(page.locator('#refresh-state')).toHaveText('현재 서버에서는 갱신 관측을 제공하지 않습니다.');
  await expect(table).toBeHidden();
  summary.apiHourly = [];
  await page.getByRole('button', { name: '조회 / 새로고침' }).click();
  await expect(page.locator('#hourly-state')).toHaveText('최근 24시간에 기록된 API 요청이 없습니다.');
});
