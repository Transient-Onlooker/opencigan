import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('suggestion UI is hidden when the API is disabled', async ({ page }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not probe');
  let requests = 0;
  await page.route('**/api/v1/suggestions**', async (route) => {
    requests++;
    await route.fulfill({ status: 503, json: { code: 'suggestions_disabled' } });
  });
  await page.goto('/?view=settings');
  await expect(page.locator('#settings-panel')).toBeVisible();
  await expect(page.getByText('만들어주세요', { exact: true })).toHaveCount(0);
  await expect.poll(() => requests).toBeGreaterThan(0);
});

test('enabled suggestions search and submit safely', async ({ page }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not probe');
  let submissions = 0, searched = false;
  await page.route('**/api/v1/suggestions**', async (route) => {
    if (route.request().method() === 'POST') {
      submissions++;
      return route.fulfill(submissions === 1
        ? { status: 409, json: { code: 'duplicate_suggestion' } }
        : { status: 201, json: { id: 'a'.repeat(24), token: 'b'.repeat(43) } });
    }
    if (new URL(route.request().url()).searchParams.get('q') === '검색어') searched = true;
    await route.fulfill({ json: { suggestions: [{ id: '1', title: '<img src=x onerror=alert(1)>', description: '공개 제안', context: null }], nextCursor: null } });
  });
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/?view=settings');
  await page.getByText('만들어주세요', { exact: true }).click();
  await expect(page.getByText('<img src=x onerror=alert(1)>')).toBeVisible();
  await expect(page.locator('.suggestions img')).toHaveCount(0);
  await page.getByLabel('공개 제안 검색').fill('검색어');
  await page.getByRole('button', { name: '검색', exact: true }).click();
  await expect.poll(() => searched).toBe(true);
  await page.getByLabel('제목', { exact: true }).fill('새 기능');
  await page.getByLabel('내용', { exact: true }).fill('설명');
  await page.getByRole('button', { name: '제안 보내기' }).click();
  await expect(page.locator('.suggestions [role="status"]')).toContainText('비슷한 제안');
  await page.getByRole('button', { name: '제안 보내기' }).click();
  await expect(page.locator('.suggestions [role="status"]')).toContainText('접수했어요');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test('enabled build hides the entry when the API is unavailable', async ({ page }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not probe');
  await page.route('**/api/v1/suggestions**', (route) => route.fulfill({ status: 503, json: { code: 'suggestions_disabled' } }));
  const response = page.waitForResponse((res) => res.url().includes('/api/v1/suggestions'));
  await page.goto('/?view=settings');
  await response;
  await expect(page.locator('#settings-panel')).toBeVisible();
  await expect(page.getByText('만들어주세요', { exact: true })).toHaveCount(0);
});
