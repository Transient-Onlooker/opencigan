import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });
const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
const week = '2026-11-09';
const sharedHash = (room = 7) => '#' + new URLSearchParams({ school: school.id, name: school.name, region: school.region, grade: '1', class: String(room) });
const timetable = {
  schoolId: school.id, weekStart: week, fetchedAt: '2026-11-09T01:00:00Z', sourceUpdatedAt: null, stale: false,
  records: [1, 2].map((room) => ({ grade: 1, class: room, date: week, period: 1, subject: `과목${room}`, teacher: null, isChanged: false })),
};

async function mockApi(page, delayedSearch) {
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/schools') {
      if (delayedSearch) await delayedSearch;
      return route.fulfill({ json: { schools: [school], stale: false } });
    }
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: timetable });
    if (url.pathname === '/api/v1/neis/schools') return route.fulfill({ json: { schools: [{ id: 'B10:1234567', name: school.name, region: '서울', address: '서울특별시' }], stale: false } });
    if (url.pathname === '/api/v1/meals') return route.fulfill({ json: { meals: [{ date: url.searchParams.get('from'), type: '중식', dishes: ['식단 ' + url.searchParams.get('from')] }], stale: false } });
    return route.fulfill({ json: { schools: [], changes: [], stale: false } });
  });
}

test('invalid shared classroom exposes an error and can be corrected without saving the forged class', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash());
  const input = page.getByRole('spinbutton', { name: '반', exact: true });
  await expect(input).toBeVisible();
  await expect(input).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#class-error')).toContainText('1학년 7반');
  expect(await page.evaluate(() => localStorage.getItem('opensigan-school'))).toBeNull();
  await input.fill('2');
  await input.press('Tab');
  await expect(input).toHaveValue('2');
  await expect(input).toHaveAttribute('aria-invalid', 'false');
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목2');
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('2');
});

test('manual class selection wins over a delayed shared school check in the same school', async ({ page }) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  await mockApi(page, pending);
  await page.addInitScript((value) => {
    localStorage.setItem('opensigan-school', JSON.stringify(value));
    localStorage.setItem('opensigan-grade', '1');
    localStorage.setItem('opensigan-class', '1');
  }, school);
  await page.goto('/' + sharedHash(1));
  const classes = page.locator('.quick-class select').nth(1);
  await expect(classes).toHaveValue('1');
  await classes.selectOption('2');
  release();
  await page.getByRole('button', { name: '학교 변경', exact: true }).click();
  await expect(page.getByRole('spinbutton', { name: '반', exact: true })).toHaveValue('2');
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목2');
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('2');
});

test('invalid manual class edits restore the applied selection on blur', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '학교 변경', exact: true }).click();
  const input = page.getByRole('spinbutton', { name: '반', exact: true });
  await input.fill('99');
  await expect(input).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#class-selection')).toContainText('현재 선택: 1학년 1반');
  await input.press('Tab');
  await expect(input).toHaveValue('1');
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('1');
  await input.fill('2');
  await input.press('Tab');
  await expect(page.locator('#class-error')).toHaveCount(0);
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목2');
});

test('meal date errors preserve the applied date and valid input fetches the matching week', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const input = page.getByLabel('날짜 선택');
  await expect(input).toHaveValue(week);
  await input.fill('0005-11-13');
  await input.press('Tab');
  await expect(input).toHaveValue(week);
  await expect(input).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#meal-date-error')).toBeVisible();
  const requested = page.waitForRequest((request) => request.url().includes('/api/v1/meals?') && new URL(request.url()).searchParams.get('from') === '2024-02-26');
  await input.fill('2024-02-29');
  await input.press('Tab');
  await requested;
  await expect(input).toHaveValue('2024-02-29');
  await expect(input).toHaveAttribute('aria-invalid', 'false');
});

test('back and forward restore the app tab and class without adding history entries', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  const classes = page.locator('.quick-class select').nth(1);
  await expect(classes).toHaveValue('1');
  await classes.selectOption('2');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.locator('#meals-panel')).toBeVisible();
  const length = await page.evaluate(() => history.length);
  await page.goBack();
  await expect(page.locator('#timetable-panel')).toBeVisible();
  await expect(classes).toHaveValue('2');
  await page.goBack();
  await expect(classes).toHaveValue('1');
  await page.goForward();
  await expect(classes).toHaveValue('2');
  await page.goForward();
  await expect(page.locator('#meals-panel')).toBeVisible();
  expect(await page.evaluate(() => history.length)).toBe(length);
});

test('favorites collapse, settings search and keyboard help remain usable at narrow widths', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '현재 학급 즐겨찾기 추가' }).click();
  await page.getByRole('button', { name: '목록 접기' }).click();
  await expect(page.locator('#favorite-list')).toBeHidden();
  await expect(page.getByLabel('즐겨찾는 학급 바로 선택')).toBeVisible();
  const help = page.getByLabel('시간표 조회 범위 도움말');
  await help.focus();
  await expect(help.locator('..').getByText(/원본 서비스가 제공하는/)).toBeVisible();
  await help.press('Enter');
  await expect(help).toHaveAttribute('aria-expanded', 'true');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByLabel('설정 검색').fill('알레르기');
  await expect(page.getByText('급식 알레르기 설정', { exact: true })).toBeVisible();
  await expect(page.getByText('학교 교시 시각 설정', { exact: true })).toBeHidden();
  for (const width of [320, 800, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.getByLabel('설정 검색').fill('일치하지않는설정');
  await expect(page.getByText('일치하는 설정이 없어요.')).toBeVisible();
});

test('timed calendar includes bell times only after explicit consent and closes correctly', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByLabel('설정 검색').fill('교시');
  await page.getByLabel('1교시 시작', { exact: true }).fill('09:00');
  await page.getByLabel('1교시 종료', { exact: true }).fill('09:50');
  await page.getByRole('button', { name: '시각 저장', exact: true }).click();
  await expect(page.getByText('이 학교의 교시 시각을 저장했어요.')).toBeVisible();
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await page.getByRole('button', { name: '캘린더 구독 링크' }).click();
  await page.getByLabel('일정 표시 방식').selectOption('timed');
  const url = page.getByLabel(/시간표 구독 URL/);
  await expect(url).toHaveCount(0);
  await page.getByRole('checkbox', { name: /입력한 교시 시각을 구독 URL에 포함/ }).check();
  await expect(url).toHaveValue(/mode=timed&times=1%3A0900-0950$/);
  await page.getByRole('button', { name: '구독 링크 닫기' }).click();
  await expect(page.getByLabel('일정 표시 방식')).toHaveCount(0);
});

test('personal timetable saves, replaces and deletes local lessons without changing source data', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByText('개인 시간표·일정', { exact: true }).click();
  const personal = page.getByRole('region', { name: '개인 시간표', exact: true });
  await personal.getByLabel('과목명', { exact: true }).fill('개인 수학');
  await personal.getByRole('button', { name: '저장', exact: true }).click();
  await expect(personal.getByRole('table')).toContainText('개인 수학');
  await personal.getByLabel('과목명', { exact: true }).fill('수정한 수학');
  await personal.getByRole('button', { name: '저장', exact: true }).click();
  await expect(personal.getByRole('table')).toContainText('수정한 수학');
  await expect(personal.getByRole('table')).not.toContainText('개인 수학');
  const download = page.waitForEvent('download');
  await personal.getByRole('button', { name: '시간표 PNG 저장' }).click();
  expect((await download).suggestedFilename()).toMatch(/개인_시간표.*\.png$/);
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목1');
  await personal.getByRole('button', { name: /수정한 수학 삭제/ }).click();
  await expect(personal.getByRole('table')).not.toContainText('수정한 수학');
  await page.reload();
  await page.getByText('개인 시간표·일정', { exact: true }).click();
  await expect(personal.getByRole('table')).not.toContainText('수정한 수학');
});
