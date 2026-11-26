import { expect, test } from '@playwright/test';

test('offline settings remain usable and suggestions recover after reconnecting', async ({ page, context, browserName }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not load suggestions');
  test.skip(browserName === 'webkit' && process.platform === 'win32', 'Playwright WebKit does not consistently emulate service-worker offline requests on Windows.');
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/v1/**', route => route.fulfill({ json: { suggestions: [], schools: [], meals: [] } }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => !!navigator.serviceWorker.controller)).toBe(true);
  await context.setOffline(true);
  await page.goto('/?offline=1');
  const chunkFailure = page.waitForEvent('requestfailed', request => /\/assets\/Suggestions-.*\.js/.test(request.url()));
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await chunkFailure;
  await expect(page.locator('#settings-panel')).toBeVisible();
  await expect(page.getByText('만들어주세요', { exact: true })).toHaveCount(0);
  await expect(page.getByText('제안 기능을 불러오지 못했어요.')).toBeVisible();
  await context.setOffline(false);
  await expect.poll(() => page.evaluate(() => navigator.onLine)).toBe(true);
  await page.getByRole('button', { name: '새로고침 후 다시 시도', exact: true }).click();
  try {
    await expect(page.getByText('만들어주세요', { exact: true })).toBeVisible({ timeout: 5000 });
  } catch (error) {
    console.log('Retry diagnostics:', await page.evaluate(() => ({
      url: location.href, online: navigator.onLine,
      retryMarker: sessionStorage.getItem('opencigan-retry-suggestions'),
      body: document.body.innerText.slice(-1800),
    })));
    throw error;
  }
  expect(errors).toEqual([]);
});
