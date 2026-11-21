import { expect, test } from '@playwright/test';

test('suggestion UI is hidden and makes no requests by default', async ({ page }) => {
  let requests = 0;
  await page.route('**/api/v1/suggestions**', async (route) => {
    requests++;
    await route.fulfill({ status: 503, json: { code: 'suggestions_disabled' } });
  });
  await page.goto('/?view=settings');
  await expect(page.locator('#settings-panel')).toBeVisible();
  await expect(page.getByText('만들어주세요', { exact: true })).toHaveCount(0);
  expect(requests).toBe(0);
});
