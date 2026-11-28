import { expect, test } from '@playwright/test';

test('today heading follows the selected date while other views retain the week', async ({ page }) => {
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z', stale: false,
      records: [{ grade: 1, class: 1, date: url.searchParams.get('week'), period: 1, subject: '수학', teacher: '김교사', isChanged: false }],
    } });
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  const date = panel.locator('.calendar-date strong');
  await expect(date).toHaveText('11.9 ~ 11.13');
  await panel.getByRole('button', { name: '오늘', exact: true }).click();
  await expect(panel.locator('.section-heading .eyebrow')).toHaveCount(0);
  await expect(date).toHaveText('2026. 11. 9.');
  await panel.locator('#today-date').fill('2026-11-11');
  await expect(date).toHaveText('2026. 11. 11.');
  await panel.getByRole('button', { name: '다음 주', exact: true }).click();
  await expect(date).toHaveText('2026. 11. 16.');
  await panel.getByRole('button', { name: '오늘로', exact: true }).click();
  await expect(date).toHaveText('2026. 11. 9.');
  for (const name of ['이번 주', '1학년', '교사']) {
    await panel.getByRole('button', { name, exact: true }).click();
    await expect(date).toHaveText('11.9 ~ 11.13');
    await expect(panel.locator('.section-heading .eyebrow')).toHaveText('이번 주');
  }
});

test('today heading uses the Korean date at midnight even without lessons', async ({ page }) => {
  await page.clock.setFixedTime(new Date('2026-11-15T15:01:00Z'));
  await page.route('**/api/v1/**', (route) => route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } }));
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await panel.getByRole('button', { name: '오늘', exact: true }).click();
  await expect(panel.locator('.calendar-date strong')).toHaveText('2026. 11. 16.');
});
