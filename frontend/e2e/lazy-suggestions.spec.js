import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('suggestions recover after a failed chunk fetch', async ({ page }) => {
  test.skip(process.env.VITE_SUGGESTIONS_ENABLED === '0', 'Explicitly disabled build does not load suggestions');
  let attempts = 0;
  await page.route('**/assets/Suggestions-*.js', route => {
    attempts++;
    return attempts === 1 ? route.abort('failed') : route.continue();
  });
  await page.route('**/api/v1/suggestions**', route => route.fulfill({ json: { suggestions: [], nextCursor: null } }));
  await page.goto('/');
  expect(attempts).toBe(0);
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect.poll(() => attempts).toBe(1);
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect(page.getByText('만들어주세요', { exact: true })).toBeVisible({ timeout: 5000 });
});
