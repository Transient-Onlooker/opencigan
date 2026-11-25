import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('mobile timetable controls remain visible when viewing next week', async ({ page }) => {
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: new Date().toISOString(),
      sourceUpdatedAt: null, stale: false,
      records: [{ grade: 1, class: 1, date: url.searchParams.get('week'), period: 1, subject: '수학', teacher: '교사', isChanged: false }],
    } });
    return route.fulfill({ json: { schools: [], meals: [], stale: false } });
  });
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('button', { name: '이미지 저장·공유' })).toBeEnabled();
  await panel.getByRole('button', { name: '다음 주', exact: true }).click();
  await expect(panel.getByRole('button', { name: '이번 주로' })).toBeVisible();
  await expect(panel.getByRole('button', { name: '이미지 저장·공유' })).toBeEnabled();
  const bounds = await panel.locator('.heading-actions button').evaluateAll((buttons) => buttons.map((button) => {
    const { x, y, width, height } = button.getBoundingClientRect();
    return { x, y, width, height };
  }));
  expect(bounds).toHaveLength(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  for (const button of bounds) {
    expect(button.x).toBeGreaterThanOrEqual(0);
    expect(button.x + button.width).toBeLessThanOrEqual(320);
    expect(button.height).toBeGreaterThanOrEqual(40);
  }
  for (let i = 0; i < bounds.length; i++) for (let j = i + 1; j < bounds.length; j++) {
    const a = bounds[i], b = bounds[j];
    expect(a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y).toBeTruthy();
  }
});
