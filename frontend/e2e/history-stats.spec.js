import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('history stats UI is hidden and makes no requests by default', async ({ page }) => {
  test.skip(process.env.VITE_HISTORY_STATS_ENABLED === '1', 'Only applies to default build where history stats is disabled');
  let requests = 0;
  await page.route('**/api/v1/admin/history-stats**', async (route) => {
    requests++;
    await route.fulfill({ status: 503, json: { code: 'history_stats_disabled' } });
  });
  await page.goto('/analytics.html');
  await expect(page.locator('#history-stats-section')).toBeHidden();
  expect(requests).toBe(0);
});

test('history stats disabled build maintains accessibility and theme without leaking UI', async ({ page }) => {
  test.skip(process.env.VITE_HISTORY_STATS_ENABLED === '1', 'Only applies to default build');
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/analytics.html');
  await expect(page.locator('#history-stats-section')).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test('enabled history stats: fetches stats, handles observed=false and observed=true, escapes HTML, clears on lock, and adapts to mobile', async ({ page }) => {
  test.skip(process.env.VITE_HISTORY_STATS_ENABLED !== '1', 'Requires opt-in build with VITE_HISTORY_STATS_ENABLED=1');

  const historyRequests = [];
  let statsResponse = {
    observed: false,
    totalChanges: null,
    byType: null,
    affectedClasses: null,
    lastObservedAt: null,
    retainedSince: '2026-10-23T00:00:00+00:00',
    comparisonCoverage: 'unknown',
  };

  await page.route('**/api/v1/admin/history-stats**', async (route) => {
    const request = route.request();
    historyRequests.push({
      url: request.url(),
      method: request.method(),
      headers: request.headers(),
    });
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'Cache-Control': 'no-store' },
      body: JSON.stringify(statsResponse),
    });
  });

  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/analytics.html');

  const historySection = page.locator('#history-stats-section');
  await expect(historySection).toBeVisible();

  await page.locator('#history-school').fill('1:Example');
  await page.locator('#history-week').fill('2026-11-16');
  await page.locator('#history-stats-load').click();
  await expect(page.locator('#history-stats-state')).toContainText('상단의 관리자 토큰을 먼저 입력해 주세요.');
  expect(historyRequests).toHaveLength(0);

  await page.locator('#token').fill('secret-admin-token');
  await page.locator('#history-stats-load').click();

  await expect.poll(() => historyRequests.length).toBe(1);
  const req1 = historyRequests[0];
  expect(req1.method).toBe('GET');
  expect(req1.headers.authorization).toBe('Bearer secret-admin-token');
  expect(req1.headers.referer).toBeUndefined();
  const url1 = new URL(req1.url);
  expect(url1.searchParams.get('school')).toBe('1:Example');
  expect(url1.searchParams.get('week')).toBe('2026-11-16');

  const resultsContainer = page.locator('#history-stats-results');
  await expect(resultsContainer).toBeVisible();
  await expect(resultsContainer).toContainText('미관측');
  await expect(resultsContainer).toContainText('30일 보존 한계');

  const storageState = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  expect(JSON.stringify(storageState)).not.toContain('secret-admin-token');

  statsResponse = {
    observed: true,
    totalChanges: 0,
    byType: { added: 0, changed: 0, deleted: 0 },
    affectedClasses: 0,
    lastObservedAt: '2026-11-16T08:30:00+00:00',
    retainedSince: '2026-10-23T00:00:00+00:00',
    comparisonCoverage: 'unknown',
  };
  await page.locator('#history-stats-load').click();
  await expect(resultsContainer).toContainText('보존된 관측 변경');
  await expect(resultsContainer).toContainText('0건');
  await expect(resultsContainer).toContainText('저장된 변경 기록 0건 · 비교 횟수와 관측 공백은 알 수 없음');
  await expect(resultsContainer).toContainText('마지막 관측 시각');
  await expect(resultsContainer).toContainText('30일 보존 한계');

  statsResponse = {
    observed: true,
    totalChanges: 12,
    byType: { added: 5, changed: 4, deleted: 3 },
    affectedClasses: 3,
    lastObservedAt: '2026-11-16T10:00:00+00:00',
    retainedSince: '2026-10-23T00:00:00+00:00',
    comparisonCoverage: 'unknown',
    subjectPeriods: [{ subject: '<img src=x onerror=alert(1)>', classPeriods: 2 }, { subject: '수학', classPeriods: 3 }],
  };
  await page.locator('#history-stats-load').click();
  await expect(resultsContainer).toContainText('12건');
  await expect(resultsContainer).toContainText('수학: 3학급 교시');
  await expect(resultsContainer).toContainText('<img src=x onerror=alert(1)>: 2학급 교시');
  await expect(resultsContainer.locator('img')).toHaveCount(0);
  await expect(resultsContainer).toContainText('보존된 관측 변경');
  await expect(resultsContainer).toContainText('3개 학급');
  await expect(resultsContainer).toContainText('5건');
  await expect(resultsContainer).toContainText('4건');
  await expect(resultsContainer).toContainText('3건');

  statsResponse = { ...statsResponse, totalChanges: null };
  await page.locator('#history-stats-load').click();
  await expect(page.locator('#history-stats-state')).toContainText('응답이 올바르지 않습니다');
  await expect(resultsContainer).toBeHidden();

  await expect(page.locator('#history-stats-results img')).toHaveCount(0);
  await expect(page.locator('#history-stats-results script')).toHaveCount(0);

  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);

  await page.locator('#clear').click();
  await expect(page.locator('#token')).toHaveValue('');
  await expect(resultsContainer).toBeHidden();
  await expect(resultsContainer).toBeEmpty();
  await expect(page.locator('#history-stats-state')).toHaveText('');
});
