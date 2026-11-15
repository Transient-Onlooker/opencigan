import { expect, test } from '@playwright/test';

test('teacher and grade views keep class labels legible on narrow screens', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z',
      sourceUpdatedAt: null, stale: false, records: [
        { grade: 2, class: 11, date: '2026-11-09', period: 1, subject: '매우 긴 과목 이름', teacher: '김교사', isChanged: false },
        { grade: 2, class: 12, date: '2026-11-09', period: 3, subject: '수학', teacher: '김교사', isChanged: false },
      ],
    } });
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await panel.locator('.quick-class select').first().selectOption('2');
  await panel.getByRole('button', { name: '교사', exact: true }).click();
  await panel.getByRole('button', { name: '김교사', exact: true }).click();
  const table = panel.locator('.teacher-table');
  const pieces = table.locator('tbody tr').first().locator('td').first().locator('strong span');
  await expect(pieces).toHaveText(['2학년', '11반']);
  for (const piece of await pieces.all()) {
    const sizes = await piece.evaluate((el) => ({
      width: el.getBoundingClientRect().width,
      height: el.getBoundingClientRect().height,
      lineHeight: parseFloat(getComputedStyle(el).lineHeight),
      cellWidth: el.closest('td').getBoundingClientRect().width,
    }));
    expect(sizes.height).toBeLessThanOrEqual(sizes.lineHeight + 1);
    expect(sizes.width).toBeLessThanOrEqual(sizes.cellWidth);
  }
  expect(await table.locator('tbody tr').nth(1).evaluate((row) => row.getBoundingClientRect().height)).toBeLessThan(60);
  await panel.getByRole('button', { name: '2학년', exact: true }).click();
  const heading = panel.locator('.grade-compact h4').filter({ hasText: '11반' }).first();
  await expect(heading).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});
