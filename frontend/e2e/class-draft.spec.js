import { expect, test } from '@playwright/test';

test('timetable arrival preserves an unfinished class edit', async ({ page }) => {
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  let release;
  let started;
  const requested = new Promise((resolve) => { started = resolve; });
  const pending = new Promise((resolve) => { release = resolve; });
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== '/api/v1/timetable') return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
    started();
    await pending;
    return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), stale: false,
      fetchedAt: '2026-11-09T01:00:00Z', sourceUpdatedAt: null,
      records: [1, 2].map((room) => ({ grade: 1, class: room, date: '2026-11-09', period: 1, subject: `과목 ${room}`, teacher: null, isChanged: false })),
    } });
  });
  try {
    await page.goto('/');
    await requested;
    await page.getByRole('button', { name: '학교/학년 변경' }).click();
    const input = page.locator('#school-settings #classroom');
    await input.fill('2');
    await expect(input).toBeFocused();
    release();
    await expect(page.locator('#timetable-panel').getByText('과목 1', { exact: true })).toBeVisible();
    await expect(input).toHaveValue('2');
    await input.blur();
    await expect(page.locator('#timetable-panel').getByText('과목 2', { exact: true })).toBeVisible();
    await input.fill('3');
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await input.blur();
    await expect(input).toHaveValue('2');
    await expect(page.locator('#class-selection')).toContainText('1학년 2반');
  } finally {
    release();
  }
});

test('timetable arrival validates an unfinished unavailable class without erasing it', async ({ page }) => {
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  let release;
  let started;
  const requested = new Promise((resolve) => { started = resolve; });
  const pending = new Promise((resolve) => { release = resolve; });
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== '/api/v1/timetable') return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
    started();
    await pending;
    return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), stale: false,
      fetchedAt: '2026-11-09T01:00:00Z', sourceUpdatedAt: null,
      records: [{ grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '수학', teacher: null, isChanged: false }],
    } });
  });
  try {
    await page.goto('/');
    await requested;
    await page.getByRole('button', { name: '학교/학년 변경' }).click();
    const input = page.locator('#school-settings #classroom');
    await input.fill('2');
    release();
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await expect(input).toHaveValue('2');
    await input.blur();
    await expect(input).toHaveValue('1');
    await expect(page.locator('#class-selection')).toContainText('1학년 1반');
  } finally {
    release();
  }
});
