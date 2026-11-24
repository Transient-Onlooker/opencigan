import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('calendar tabs retain readable contrast in light and dark themes', async ({ page }) => {
  await page.route('**/api/v1/**', (route) => route.fulfill({ status: 503, json: {} }));
  for (const theme of ['light', 'dark']) {
    await page.addInitScript((value) => localStorage.setItem('opensigan-theme', value), theme);
    await page.goto('/');
    if (theme === 'dark') await expect(page.locator('.app-shell')).toHaveClass(/\bdark\b/);
    else await expect(page.locator('.app-shell')).not.toHaveClass(/\bdark\b/);
    const menu = page.getByRole('navigation', { name: '캘린더 메뉴' });
    for (const width of [390, 1024]) {
      await page.setViewportSize({ width, height: 844 });
      for (const name of ['시간표', '급식', '설정']) {
        const button = menu.getByRole('button', { name, exact: true });
        await button.click();
        await expect(button).toHaveAttribute('aria-pressed', 'true');
        for (const tabName of ['시간표', '급식', '설정']) {
          const tab = menu.getByRole('button', { name: tabName, exact: true });
          for (const hovered of [false, true]) {
            if (hovered) await tab.hover();
            else await page.mouse.move(0, 0);
            const ratio = await tab.evaluate((node) => {
              const style = getComputedStyle(node);
              const luminance = (color) => {
                const values = color.match(/\d+(?:\.\d+)?/g).slice(0, 3).map(Number);
                const channels = values.map((value) => {
                  const v = value / 255;
                  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
                });
                return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
              };
              const foreground = luminance(style.color);
              const background = luminance(style.backgroundColor);
              return { ratio: (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05), color: style.color, background: style.backgroundColor };
            });
            expect(ratio.ratio, `${theme} ${width}px ${name}/${tabName} hovered=${hovered} ${ratio.color} on ${ratio.background}`).toBeGreaterThanOrEqual(4.5);
          }
        }
      }
    }
  }
});
