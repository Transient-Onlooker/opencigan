import { expect, test } from '@playwright/test';

test('school and class display changes propagate to another tab without erasing earlier edits', async ({ context }) => {
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  await context.addInitScript(value => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await context.route('**/api/v1/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z',
      sourceUpdatedAt: null, stale: false, records: [{ grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '수학', teacher: null, isChanged: false }],
    } });
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  const first = await context.newPage();
  const second = await context.newPage();
  for (const page of [first, second]) {
    await page.goto('/?view=settings');
    await page.getByText('시간표 표시 설정', { exact: true }).click();
  }
  await second.getByLabel('시간표 밀도').selectOption('compact');
  await expect(first.getByLabel('시간표 밀도')).toHaveValue('compact');
  await first.getByLabel('시간표에 교사 표시').uncheck();
  await expect(second.getByLabel('시간표에 교사 표시')).not.toBeChecked();
  await expect(second.getByLabel('시간표 밀도')).toHaveValue('compact');

  await first.getByLabel('1학년 1반만 따로 설정').check();
  await expect(second.getByLabel('1학년 1반만 따로 설정')).toBeChecked();
  await second.getByLabel('시간표 밀도').selectOption('relaxed');
  await expect(first.getByLabel('시간표 밀도')).toHaveValue('relaxed');
  await first.getByLabel('시간표에 교사 표시').check();
  await expect(second.getByLabel('시간표에 교사 표시')).toBeChecked();
  await expect(second.getByLabel('시간표 밀도')).toHaveValue('relaxed');
});
