import { expect, test } from '@playwright/test';

test('school search works with arrow keys, Enter and Escape', async ({ page }) => {
  const schools = [
    { id: '1:봄빛고등학교', name: '봄빛고등학교', region: '서울' },
    { id: '2:봄빛중학교', name: '봄빛중학교', region: '경기' },
  ];
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/schools') {
      return route.fulfill({ json: { schools, stale: false } });
    }
    if (url.pathname === '/api/v1/timetable') {
      return route.fulfill({ json: {
        schoolId: url.searchParams.get('school'),
        weekStart: url.searchParams.get('week'),
        fetchedAt: new Date().toISOString(),
        sourceUpdatedAt: null, stale: false, records: [],
      } });
    }
    return route.fulfill({ json: { schools: [], meals: [], stale: false } });
  });
  await page.goto('/');
  const search = page.getByRole('searchbox', { name: '학교 찾기' });
  await search.fill('봄빛');
  const first = page.getByRole('button', { name: /봄빛고등학교/ });
  const second = page.getByRole('button', { name: /봄빛중학교/ });
  await expect(first).toBeVisible();
  await search.press('ArrowDown');
  await expect(first).toBeFocused();
  await first.press('ArrowDown');
  await expect(second).toBeFocused();
  await second.press('ArrowUp');
  await expect(first).toBeFocused();
  await first.press('Escape');
  await expect(search).toBeFocused();
  await expect(first).toHaveCount(0);

  await search.fill('봄빛');
  await expect(first).toBeVisible();
  await search.press('ArrowDown');
  await first.press('Enter');
  await expect(page.getByRole('heading', { name: '봄빛고등학교' })).toBeVisible();
  await expect(search).toHaveCount(0);
});

test('school selection and navigation do not cause horizontal overflow on small screens', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto('/');
  const menu = page.getByRole('navigation', { name: '캘린더 메뉴' });
  await expect(menu.getByRole('button', { name: '시간표' })).toBeVisible();
  await expect(menu.getByRole('button', { name: '급식' })).toBeVisible();
  await expect(menu.getByRole('button', { name: '설정' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});
