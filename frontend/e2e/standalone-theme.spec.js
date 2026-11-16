import { expect, test } from '@playwright/test';

test('standalone pages follow the saved theme and link back to the site', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  for (const path of ['/embed-builder.html', '/analytics.html', '/access-logs.html', '/webhooks.html']) {
    await page.goto(path);
    for (const [preference, expected] of [['dark', 'dark'], ['light', 'light'], ['system', 'dark']]) {
      await page.evaluate((value) => localStorage.setItem('opensigan-theme', value), preference);
      await page.reload();
      await expect(page.locator('html')).toHaveAttribute('data-theme', expected);
      await expect(page.locator('html')).toHaveCSS('background-color', expected === 'dark' ? 'rgb(17, 17, 17)' : 'rgb(255, 255, 255)');
    }
    await expect(page.locator('a[href="./"]').first()).toBeVisible();
    for (const width of [320, 800, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth), `${path} at ${width}px`).toBeLessThanOrEqual(width);
    }
  }
});
