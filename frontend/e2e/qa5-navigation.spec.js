import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

test('week and teacher selection survive return and browser history', async ({ page }) => {
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((s) => localStorage.setItem('opensigan-school', JSON.stringify(s)), school);
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/timetable') {
      const week = url.searchParams.get('week');
      return route.fulfill({ json: { schoolId: school.id, weekStart: week, fetchedAt: '2026-11-09T01:00:00Z', stale: false,
        records: [{ grade: 1, class: 1, date: week, period: 1, subject: week === '2026-11-09' ? '이번주수학' : '다음주수학', teacher: '김교사', isChanged: false },
          { grade: 1, class: 1, date: week, period: 2, subject: '영어', teacher: '이교사', isChanged: false }] } });
    }
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByText('이번주수학')).toBeVisible();
  await panel.getByRole('button', { name: '교사', exact: true }).click();
  await panel.getByRole('button', { name: '김교사', exact: true }).click();
  await expect(panel.locator('.teacher-table')).toContainText('이번주수학');
  await panel.getByRole('button', { name: '다음 주', exact: true }).click();
  await expect(panel.locator('.teacher-table')).toContainText('다음주수학');
  await panel.getByRole('button', { name: '이번 주로', exact: true }).click();
  await expect(panel.locator('.teacher-table')).toContainText('이번주수학');
  await page.goBack();
  await expect(panel.locator('.calendar-date')).toContainText('11.16');
  await expect(panel.locator('.teacher-table')).toContainText('다음주수학');
  await page.goForward();
  await expect(panel.locator('.calendar-date')).toContainText('11.9');
  await expect(panel.locator('.teacher-table')).toContainText('이번주수학');
  await panel.getByRole('searchbox', { name: '교사별 주간 시간표' }).fill('이교사');
  await expect(panel.locator('.teacher-table')).toContainText('영어');
  await page.goBack();
  await expect(panel.locator('.calendar-date')).toContainText('11.16');
  await expect(panel.getByRole('searchbox', { name: '교사별 주간 시간표' })).toHaveValue('김교사');
  await expect(panel.locator('.teacher-table')).toContainText('다음주수학');
  await page.goForward();
  await expect(panel.getByRole('searchbox', { name: '교사별 주간 시간표' })).toHaveValue('이교사');
});

test('teacher view explains an absent teacher for the destination week and restores it on return', async ({ page }) => {
  const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((s) => localStorage.setItem('opensigan-school', JSON.stringify(s)), school);
  await page.route('**/api/v1/**', (route) => {
    const url = new URL(route.request().url());
    const week = url.searchParams.get('week');
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
      schoolId: school.id, weekStart: week, fetchedAt: '2026-11-09T01:00:00Z', stale: false,
      records: [{ grade: 1, class: 1, date: week, period: 1, subject: '수학', teacher: week === '2026-11-09' ? '김교사' : '이교사', isChanged: false }],
    } });
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByText('수학')).toBeVisible();
  await panel.getByRole('button', { name: '교사', exact: true }).click();
  await panel.getByRole('button', { name: '김교사', exact: true }).click();
  await panel.getByRole('button', { name: '다음 주', exact: true }).click();
  await expect(panel.getByText('이 주에 검색된 교사가 없어요')).toBeVisible();
  await panel.getByRole('button', { name: '이번 주로', exact: true }).click();
  await expect(panel.locator('.teacher-table')).toContainText('수학');
  await expect(panel.getByRole('searchbox', { name: '교사별 주간 시간표' })).toHaveValue('김교사');
  await page.goBack();
  await expect(panel.locator('.calendar-date')).toContainText('11.16');
  await expect(panel.getByText('이 주에 검색된 교사가 없어요')).toBeVisible();
  await expect(panel.getByRole('searchbox', { name: '교사별 주간 시간표' })).toHaveValue('김교사');
  await page.goForward();
  await expect(panel.locator('.calendar-date')).toContainText('11.9');
  await expect(panel.locator('.teacher-table')).toContainText('수학');
  await expect(panel.getByRole('searchbox', { name: '교사별 주간 시간표' })).toHaveValue('김교사');
});

for (const [fragment, explanation] of [
  ['#school=2%3A%ED%&name=x&region=y&grade=1&class=1', '인코딩이 올바르지'],
  ['#school=2%3A%EB%B4%84%EB%B9%9B%EA%B3%A0%EB%93%B1%ED%95%99%EA%B5%90&name=x&region=y&grade=1&class=1&%ZZ=x', '인코딩이 올바르지'],
  ['#school=2%3A%EB%B4%84%EB%B9%9B%EA%B3%A0%EB%93%B1%ED%95%99%EA%B5%90&grade=1&class=1', '필수 정보가 빠졌거나'],
]) {
  test(`invalid shared link keeps saved selection: ${fragment}`, async ({ page }) => {
    const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
    await page.addInitScript((s) => {
      localStorage.setItem('opensigan-school', JSON.stringify(s));
      localStorage.setItem('opensigan-grade', '2'); localStorage.setItem('opensigan-class', '3');
    }, school);
    await page.route('**/api/v1/**', (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
        schoolId: school.id, weekStart: url.searchParams.get('week'), stale: false, fetchedAt: new Date().toISOString(),
        records: [{ grade: 2, class: 3, date: url.searchParams.get('week'), period: 1, subject: '저장된 수업', teacher: '김교사', isChanged: false }],
      } });
      return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
    });
    await page.goto('/' + fragment);
    await expect(page.getByRole('status').filter({ hasText: explanation })).toBeVisible();
    await expect(page.locator('#timetable-panel').getByText('저장된 수업')).toBeVisible();
    expect(await page.evaluate(() => [localStorage.getItem('opensigan-grade'), localStorage.getItem('opensigan-class')])).toEqual(['2', '3']);
  });
}

test('a malformed shared link in a new profile does not save an unverified class', async ({ page }) => {
  await page.goto('/#school=2%3A%EB%B4%84%EB%B9%9B%EA%B3%A0%EB%93%B1%ED%95%99%EA%B5%90&grade=1&class=2');
  await expect(page.getByRole('status').filter({ hasText: '필수 정보가 빠졌거나' })).toContainText('학교와 학급을 직접 선택');
  expect(await page.evaluate(() => [localStorage.getItem('opensigan-school'), localStorage.getItem('opensigan-grade'), localStorage.getItem('opensigan-class')])).toEqual([null, null, null]);
  await page.reload();
  await expect(page.getByRole('status').filter({ hasText: '필수 정보가 빠졌거나' })).toBeVisible();
});
