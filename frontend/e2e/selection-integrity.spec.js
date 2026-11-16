import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });
const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
const week = '2026-11-09';
const sharedHash = (room = 7) => '#' + new URLSearchParams({ school: school.id, name: school.name, region: school.region, grade: '1', class: String(room) });
const timetable = {
  schoolId: school.id, weekStart: week, fetchedAt: '2026-11-09T01:00:00Z', sourceUpdatedAt: null, stale: false,
  records: [1, 2].map((room) => ({ grade: 1, class: room, date: week, period: 1, subject: `과목${room}`, teacher: null, isChanged: false })),
};

async function mockApi(page, delayedSearch, onSchoolSearch) {
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/schools') {
      onSchoolSearch?.();
      if (delayedSearch) await delayedSearch;
      return route.fulfill({ json: { schools: [school], stale: false } });
    }
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: timetable });
    if (url.pathname === '/api/v1/neis/schools') return route.fulfill({ json: { schools: [{ id: 'B10:1234567', name: school.name, region: '서울', address: '서울특별시' }], stale: false } });
    if (url.pathname === '/api/v1/meals') return route.fulfill({ json: { meals: [{ date: url.searchParams.get('from'), type: '중식', dishes: ['식단 ' + url.searchParams.get('from'), '계란말이(1.2)', '김치볶음밥(5.6)'], calories: '650 kcal', nutrition: '탄수화물 : 90g<br/>단백질 : 30g', origin: '쌀: 국내산' }], stale: false } });
    return route.fulfill({ json: { schools: [], changes: [], stale: false } });
  });
}

test('shared school and class stay pending until the matching timetable is verified', async ({ page }) => {
  const previous = { id: '1:봄빛초등학교', name: '봄빛초등학교', region: '서울' };
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  let markRequested;
  const requested = new Promise((resolve) => { markRequested = resolve; });
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((saved) => {
    localStorage.setItem('opensigan-school', JSON.stringify(saved));
    localStorage.setItem('opensigan-grade', '5');
    localStorage.setItem('opensigan-class', '2');
  }, previous);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/schools') return route.fulfill({ json: { schools: [school], stale: false } });
    if (url.pathname === '/api/v1/timetable') {
      const id = url.searchParams.get('school');
      if (id === school.id) {
        markRequested();
        await waiting;
        return route.fulfill({ json: { ...timetable, records: [{ grade: 1, class: 7, date: week, period: 1, subject: '공유 수업' }] } });
      }
      return route.fulfill({ json: { ...timetable, schoolId: previous.id, records: [{ grade: 5, class: 2, date: week, period: 1, subject: '기존 수업' }] } });
    }
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/' + sharedHash());
  await requested;
  await expect(page.getByRole('heading', { name: previous.name })).toBeVisible();
  await expect(page.getByText('5학년 2반', { exact: false }).first()).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('2');
  release();
  await expect(page.getByRole('heading', { name: school.name })).toBeVisible();
  await expect(page.getByRole('table').getByText('공유 수업')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('7');
});

test('manual class change cancels an in-flight shared timetable verification', async ({ page }) => {
  const previous = { id: '1:기존고등학교', name: '기존고등학교', region: '서울' };
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  let markRequested;
  const requested = new Promise((resolve) => { markRequested = resolve; });
  let markFinished;
  const finished = new Promise((resolve) => { markFinished = resolve; });
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((saved) => {
    localStorage.setItem('opensigan-school', JSON.stringify(saved));
    localStorage.setItem('opensigan-grade', '1');
    localStorage.setItem('opensigan-class', '1');
  }, previous);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/schools') return route.fulfill({ json: { schools: [school], stale: false } });
    if (url.pathname === '/api/v1/timetable') {
      if (url.searchParams.get('school') === school.id) {
        markRequested();
        await waiting;
        try { await route.fulfill({ json: { ...timetable, records: [{ grade: 1, class: 7, date: week, period: 1, subject: '공유 수업' }] } }); } catch { /* The client may cancel the request. */ }
        finally { markFinished(); }
        return;
      }
      return route.fulfill({ json: { ...timetable, schoolId: previous.id } });
    }
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/' + sharedHash());
  await requested;
  const classroom = page.locator('.quick-class select').nth(1);
  await expect(classroom).toHaveValue('1');
  await classroom.selectOption('2');
  release();
  await finished;
  await expect(page.getByRole('heading', { name: previous.name })).toBeVisible();
  await expect(classroom).toHaveValue('2');
  await expect(page.getByRole('table').getByText('과목2')).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('2');
});

test('school settings backup restores display preferences and bell times', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await page.getByLabel('시간표에 교사 표시').uncheck();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await page.getByLabel('1교시 시작').fill('08:30');
  await page.getByLabel('1교시 종료').fill('09:20');
  await page.getByRole('button', { name: '시각 저장' }).click();
  await page.getByText('설정 백업·복원', { exact: true }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: '학교 설정 파일 저장' }).click();
  const download = await downloadPromise;
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const contents = Buffer.concat(chunks);
  const backup = JSON.parse(contents.toString());
  expect(backup.schoolId).toBe(school.id);
  expect(backup.lessonTimes['1']).toEqual({ start: '08:30', end: '09:20' });
  await page.getByLabel('시간표에 교사 표시').check();
  await page.getByRole('button', { name: '시각 초기화' }).click();
  await page.getByLabel('Opencigan 설정 JSON 파일 불러오기').setInputFiles({ name: 'school.json', mimeType: 'application/json', buffer: contents });
  await expect(page.getByText('현재 학교의 설정을 복원했어요.')).toBeVisible();
  await expect(page.getByLabel('시간표에 교사 표시')).not.toBeChecked();
  await expect(page.getByLabel('1교시 시작')).toHaveValue('08:30');
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await expect(page.getByLabel('시간표에 교사 표시')).not.toBeChecked();
  await expect(page.getByLabel('1교시 종료')).toHaveValue('09:20');
});

test('older version 1 school settings files can still be imported', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await page.getByText('설정 백업·복원', { exact: true }).click();
  const legacy = { format: 'opencigan-settings', version: 1, schoolId: school.id, displaySettings: { colorMode: 'none', showTeachers: false }, lessonTimes: {} };
  await page.getByLabel('Opencigan 설정 JSON 파일 불러오기').setInputFiles({ name: 'legacy.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(legacy)) });
  await expect(page.getByText('현재 학교의 설정을 복원했어요.')).toBeVisible();
  await expect(page.getByLabel('시간표에 교사 표시')).not.toBeChecked();
});

test('class settings backup restores the selected class without changing another class', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await page.getByText('설정 백업·복원', { exact: true }).click();
  await expect(page.getByRole('button', { name: '학급 설정 파일 저장' })).toHaveCount(0);
  await expect(page.getByText('학급 설정 파일을 저장하려면', { exact: false })).toBeVisible();
  await page.getByLabel('1학년 1반만 따로 설정').check();
  await page.getByLabel('시간표에 교사 표시').uncheck();
  await expect(page.getByText('학급 설정 파일을 저장하려면', { exact: false })).toHaveCount(0);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: '학급 설정 파일 저장' }).click();
  const download = await downloadPromise;
  const chunks = [];
  for await (const chunk of await download.createReadStream()) chunks.push(chunk);
  const contents = Buffer.concat(chunks);
  expect(JSON.parse(contents.toString()).scope).toEqual({ grade: 1, classroom: 1 });
  await page.getByLabel('시간표에 교사 표시').check();
  await page.getByLabel('Opencigan 설정 JSON 파일 불러오기').setInputFiles({ name: 'class.json', mimeType: 'application/json', buffer: contents });
  await expect(page.getByText('현재 학급의 표시 설정을 복원했어요.')).toBeVisible();
  await expect(page.getByLabel('시간표에 교사 표시')).not.toBeChecked();
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await expect(page.getByLabel('시간표에 교사 표시')).not.toBeChecked();
  const otherKey = `opensigan-class-display:${school.id}:1:2`;
  expect(await page.evaluate((key) => localStorage.getItem(key), otherKey)).toBeNull();
});

test('disabled history is compact without hiding source change badges', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/timetable?*', (route) => route.fulfill({ json: {
    ...timetable, records: timetable.records.map((record) => ({ ...record, isChanged: true })),
  } }));
  await page.route('**/api/v1/timetable/history?*', (route) => route.fulfill({ status: 503, json: { code: 'history_disabled' } }));
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await expect(panel.locator('.change-label').first()).toBeVisible();
  await panel.getByRole('button', { name: '이력 보기' }).click();
  await expect(panel.getByRole('status').filter({ hasText: '변경 이력은 현재 제공되지 않아요.' })).toBeVisible();
  await expect(panel.locator('.history-section')).toHaveCount(0);
  await expect(panel.locator('.change-label').first()).toBeVisible();
});

test('invalid shared classroom explains why the saved class is retained', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((saved) => {
    localStorage.setItem('opensigan-school', JSON.stringify(saved));
    localStorage.setItem('opensigan-grade', '1');
    localStorage.setItem('opensigan-class', '2');
  }, school);
  await page.goto('/' + sharedHash(99));
  await expect(page.getByRole('status').filter({ hasText: '공유 링크의 1학년 99반' })).toContainText('기존 봄빛고등학교 1학년 2반을 유지');
  await expect(page.getByRole('status').filter({ hasText: '공유 링크의 1학년 99반' })).toContainText('시간표에 없어요');
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('2');
});

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
  await page.getByRole('button', { name: '학교/학년 변경', exact: true }).click();
  await expect(page.getByRole('spinbutton', { name: '반', exact: true })).toHaveValue('2');
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목2');
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('2');
});

test('history navigation cancels an outstanding shared school verification', async ({ page }) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  let markStarted;
  const started = new Promise((resolve) => { markStarted = resolve; });
  await mockApi(page, pending, markStarted);
  await page.addInitScript((value) => {
    localStorage.setItem('opensigan-school', JSON.stringify(value));
    localStorage.setItem('opensigan-grade', '1');
    localStorage.setItem('opensigan-class', '1');
  }, school);
  await page.goto('/' + sharedHash(2));
  await started;
  const classes = page.locator('.quick-class select').nth(1);
  await expect(classes).toHaveValue('1');
  await page.evaluate(({ school, week }) => {
    const state = { version: 1, view: 'timetable', timetableView: 'week', school, grade: 1, classroom: 1, week, selectedDay: week, mealDate: week };
    window.dispatchEvent(new PopStateEvent('popstate', { state: { opensigan: state } }));
  }, { school, week });
  release();
  await page.waitForTimeout(350);
  await expect(classes).toHaveValue('1');
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목1');
  expect(await page.evaluate(() => localStorage.getItem('opensigan-class'))).toBe('1');
});

test('invalid manual class edits restore the applied selection on blur', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '학교/학년 변경', exact: true }).click();
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

test('grade changes reconcile the class and remain synchronized across both selectors', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/timetable?*', (route) => route.fulfill({ json: {
    ...timetable,
    records: [...timetable.records, { grade: 2, class: 3, date: week, period: 1, subject: '2학년 수학', teacher: null, isChanged: false }],
  } }));
  await page.goto('/' + sharedHash(1));
  const grade = page.locator('.quick-class select').nth(0);
  const classroom = page.locator('.quick-class select').nth(1);
  await expect(grade).toHaveValue('1');
  await grade.selectOption('2');
  await expect(classroom).toHaveValue('3');
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('2학년 수학');
  await page.getByRole('button', { name: '학교/학년 변경', exact: true }).click();
  await expect(page.locator('#grade')).toHaveValue('2');
  expect(await page.evaluate(() => [localStorage.getItem('opensigan-grade'), localStorage.getItem('opensigan-class')])).toEqual(['2', '3']);
});

test('grade comparison accepts a pasted date in the selected week', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await page.getByRole('group', { name: '시간표 보기' }).getByRole('button', { name: '1학년' }).click();
  const input = page.getByLabel('비교 날짜');
  await expect(page.getByText('비교할 시간표가 없어요')).toHaveCount(0);
  await input.evaluate((element) => {
    const clipboard = new DataTransfer();
    clipboard.setData('text/plain', '2026-11-10');
    element.dispatchEvent(new ClipboardEvent('paste', { clipboardData: clipboard, bubbles: true, cancelable: true }));
  });
  await expect(input).toHaveValue('2026-11-10');
  await expect(page.getByText('비교할 시간표가 없어요')).toBeVisible();
});

test('meal date accepts continuous keyboard entry', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Native date keyboard entry varies by browser and locale.');
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const input = page.getByLabel('날짜 선택');
  await input.fill('');
  await input.focus();
  await input.pressSequentially('12252026');
  await input.blur();
  await expect(input).toHaveValue('2026-12-25');
  await expect(input).toHaveAttribute('aria-invalid', 'false');
});

test('meal date accepts pasted ISO date', async ({ page, browserName, context }) => {
  test.skip(browserName !== 'chromium', 'Clipboard permissions differ by browser.');
  await mockApi(page);
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const input = page.getByLabel('날짜 선택');
  await input.fill('');
  await input.focus();
  await page.evaluate(() => navigator.clipboard.writeText('2026-12-25'));
  await input.press('Control+V');
  await input.blur();
  await expect(input).toHaveValue('2026-12-25');
});

test('meal date errors preserve the applied date and valid input fetches the matching week', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const input = page.getByLabel('날짜 선택');
  await expect(input).toHaveValue(week);
  await input.focus();
  await input.fill('0005-11-13');
  await input.dispatchEvent('change');
  await expect(input).toHaveValue('0005-11-13');
  await expect(page.locator('#meal-date-error')).toHaveCount(0);
  await input.blur();
  await expect(input).toHaveValue(week);
  await expect(input).toHaveAttribute('aria-invalid', 'true');
  await expect(page.locator('#meal-date-error')).toBeVisible();
  const requested = page.waitForRequest((request) => request.url().includes('/api/v1/meals?') && new URL(request.url()).searchParams.get('from') === '2024-02-26');
  await input.fill('2024-02-29');
  await input.blur();
  await requested;
  await expect(input).toHaveValue('2024-02-29');
  await expect(input).toHaveAttribute('aria-invalid', 'false');
});

test('refresh keeps the visible timetable while announcing progress and failure', async ({ page }) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  let calls = 0;
  await mockApi(page);
  await page.route('**/api/v1/timetable?*', async (route) => {
    calls += 1;
    if (calls === 1) return route.fulfill({ json: timetable });
    await pending;
    return route.fulfill({ status: 503, headers: { 'Retry-After': '12' }, json: { code: 'upstream_unavailable' } });
  });
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('table')).toContainText('과목1');
  await panel.getByRole('button', { name: /시간표 새로고침/ }).click();
  await expect(panel.getByRole('status').filter({ hasText: '새 시간표를 확인하는 동안' })).toBeVisible();
  await expect(panel.getByRole('table')).toContainText('과목1');
  release();
  await expect(panel.getByRole('alert')).toContainText('이전 시간표를 표시하고 있어요');
  await expect(panel.getByRole('alert')).toHaveCount(1);
  await expect(panel.getByRole('alert')).toContainText('새로고침 실패');
  await expect(panel.getByRole('alert')).toContainText('12초 후 다시 시도');
  await expect(panel.locator('.refresh-feedback')).toHaveCount(0);
  await expect(panel.getByRole('table')).toContainText('과목1');
  await expect(panel.getByText('저장된 시간표 · 최신 정보가 아닐 수 있어요')).toBeVisible();
});

test('online server failure restores the matching saved timetable and retry recovers', async ({ page }) => {
  await page.addInitScript(({ school, timetable }) => {
    localStorage.setItem('opensigan-school', JSON.stringify(school));
    localStorage.setItem('opensigan-grade', '1');
    localStorage.setItem('opensigan-class', '1');
    localStorage.setItem('opensigan-offline-timetable', JSON.stringify(timetable));
  }, { school, timetable });
  await mockApi(page);
  let calls = 0;
  await page.route('**/api/v1/timetable?*', (route) => {
    calls += 1;
    return calls === 1
      ? route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } })
      : route.fulfill({ json: { ...timetable, records: timetable.records.map((record) => ({ ...record, subject: '복구된 수업' })) } });
  });
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('alert')).toContainText('원본에서 데이터를 가져오지');
  await expect(panel.getByText('이 기기에 저장된 시간표 · 최신 정보가 아닐 수 있어요')).toBeVisible();
  await expect(panel.getByRole('table')).toContainText('과목1');
  await panel.getByRole('button', { name: '다시 시도' }).click();
  await expect(panel.getByRole('table')).toContainText('복구된 수업');
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(panel.getByText('이 기기에 저장된 시간표 · 최신 정보가 아닐 수 있어요')).toHaveCount(0);
});

test('returning to a week after a failed refresh fetches it again', async ({ page }) => {
  await mockApi(page);
  let currentWeekRequests = 0;
  await page.route('**/api/v1/timetable?*', (route) => {
    const requestedWeek = new URL(route.request().url()).searchParams.get('week');
    if (requestedWeek !== week) {
      return route.fulfill({ json: { ...timetable, weekStart: requestedWeek, records: timetable.records.map((record) => ({ ...record, date: requestedWeek })) } });
    }
    currentWeekRequests += 1;
    if (currentWeekRequests === 2) return route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } });
    return route.fulfill({ json: currentWeekRequests === 1 ? timetable : { ...timetable, records: timetable.records.map((record) => ({ ...record, subject: '재조회한 수업' })) } });
  });
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('table')).toContainText('과목1');
  await panel.getByRole('button', { name: /시간표 새로고침/ }).click();
  await expect(panel.getByRole('alert')).toContainText('새로고침 실패');
  await panel.getByRole('button', { name: '다음 주' }).click();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await panel.getByRole('button', { name: '이전 주' }).click();
  await expect(panel.getByRole('table')).toContainText('재조회한 수업');
  expect(currentWeekRequests).toBe(3);
});

test('timetable outage without a saved copy leaves meals available and retry recovers', async ({ page }) => {
  await page.addInitScript((savedSchool) => {
    localStorage.setItem('opensigan-school', JSON.stringify(savedSchool));
    localStorage.setItem('opensigan-grade', '1');
    localStorage.setItem('opensigan-class', '1');
    localStorage.removeItem('opensigan-offline-timetable');
  }, school);
  await mockApi(page);
  let fail = true;
  await page.route('**/api/v1/timetable?*', (route) => fail
    ? route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } })
    : route.fulfill({ json: timetable }));
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('alert')).toContainText('이 학교와 주에 저장된 시간표가 없어요');
  await expect(panel.getByRole('alert')).toContainText('원본에서 데이터를 가져오지');
  await expect(panel.getByRole('table')).toHaveCount(0);
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('김치볶음밥(5.6)').first()).toBeVisible();
  fail = false;
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await panel.getByRole('button', { name: '다시 시도' }).click();
  await expect(panel.getByRole('table')).toContainText('과목1');
  await expect(panel.getByRole('alert')).toHaveCount(0);
});

test('school search shows matching saved results on failure and clears the notice after recovery', async ({ page }) => {
  await mockApi(page);
  let fail = false;
  await page.route('**/api/v1/schools?*', (route) => fail
    ? route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } })
    : route.fulfill({ json: { schools: [school], stale: false } }));
  await page.goto('/');
  const search = page.getByRole('searchbox', { name: '학교 찾기' });
  await search.fill('봄빛');
  await expect(page.getByRole('button', { name: /봄빛고등학교/ })).toBeVisible();
  fail = true;
  await search.fill('봄빛고');
  await expect(page.locator('.search-results p').filter({ hasText: '이 검색어의 저장된 결과가 없어요' })).toBeVisible();
  await search.fill('봄빛');
  await expect(page.locator('.search-results p').filter({ hasText: '이 화면에 저장된 검색 결과' })).toBeVisible();
  await expect(page.getByRole('button', { name: /봄빛고등학교/ })).toBeVisible();
  fail = false;
  await page.getByRole('button', { name: '학교 검색 다시 시도' }).click();
  await expect(page.getByRole('button', { name: /봄빛고등학교/ })).toBeVisible();
  await expect(page.locator('.search-results p').filter({ hasText: '이 화면에 저장된 검색 결과' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '학교 검색 다시 시도' })).toHaveCount(0);
});

test('meal menu search, allergy filters, NEIS details and timetable date link work together', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('opensigan-allergies', '[1]'));
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('열량(NEIS 원문): 650 kcal')).toBeVisible();
  const allergyWarning = page.locator('.meal-types li.warning').filter({ hasText: '계란말이' });
  await expect(allergyWarning).toContainText('⚠ 주의: 1. 난류');
  await expect(allergyWarning).toHaveCSS('border-left-color', 'rgb(196, 38, 61)');
  await page.getByRole('searchbox', { name: '메뉴 검색' }).fill('김치');
  await expect(page.getByText('김치볶음밥(5.6)')).toBeVisible();
  await expect(page.getByText('계란말이(1.2)')).toHaveCount(0);
  await page.getByRole('searchbox', { name: '메뉴 검색' }).fill('');
  await page.getByLabel('알레르기 필터').selectOption('marked');
  await expect(page.getByText('계란말이(1.2)')).toBeVisible();
  await expect(page.getByText('김치볶음밥(5.6)')).toHaveCount(0);
  await page.getByLabel('알레르기 필터').selectOption('unmarked');
  await expect(page.getByText('김치볶음밥(5.6)')).toBeVisible();
  await expect(page.getByText('계란말이(1.2)')).toHaveCount(0);
  await expect(page.getByText(/미표시 메뉴도 안전을 보장하지 않습니다/)).toBeVisible();
  await page.getByText('영양·원산지 정보').click();
  await expect(page.locator('.meal-source-text').first()).toContainText('탄수화물 : 90g');
  await expect(page.getByText('원산지: 쌀: 국내산')).toBeVisible();
  await page.getByRole('button', { name: '이 날짜 시간표' }).click();
  await expect(page.locator('#timetable-panel')).toBeVisible();
  await expect(page.locator('#today-date')).toHaveValue(week);
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

test('legacy favorites remain stored while settings search and keyboard help work at narrow widths', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem('opensigan-favorites', '[{"legacy":true}]'));
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await expect(page.getByRole('button', { name: '현재 학급 즐겨찾기 추가' })).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('opensigan-favorites'))).toBe('[{"legacy":true}]');
  const help = page.getByLabel('시간표 조회 범위 도움말');
  await help.focus();
  await expect(help.locator('..').getByText(/원본 서비스가 제공하는/)).toBeVisible();
  await help.press('Enter');
  await expect(help).toHaveAttribute('aria-expanded', 'true');
  const emptyPeriodHelp = page.getByLabel('빈 교시 도움말');
  await emptyPeriodHelp.focus();
  await expect(emptyPeriodHelp.locator('..').getByText(/수집된 수업 기록이 없는 칸/)).toBeVisible();
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
  await expect(page.getByRole('navigation', { name: '캘린더 메뉴' })).toBeVisible();
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

test('personal schedule preserves entered dates when saving lessons and events', async ({ page, browserName, context }) => {
  await mockApi(page);
  if (browserName === 'chromium') await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/' + sharedHash(1));
  await page.getByText('개인 시간표·일정', { exact: true }).click();
  const personal = page.getByRole('region', { name: '개인 시간표', exact: true });
  await personal.getByLabel('과목명', { exact: true }).fill('개인 수업');
  const specificDate = personal.getByLabel('특정 일자 (선택)');
  if (browserName === 'chromium') {
    await page.evaluate(() => navigator.clipboard.writeText('20261109'));
    await specificDate.focus();
    await specificDate.press('Control+V');
    await expect(specificDate).toHaveValue(week);
  } else {
    await specificDate.fill(week);
  }
  await personal.getByRole('button', { name: '저장', exact: true }).click();
  await expect(personal.getByRole('table')).toContainText('개인 수업');
  await personal.getByRole('button', { name: /일정 \/ 시험 오버레이/ }).click();
  await personal.getByLabel('날짜', { exact: true }).fill(week);
  await personal.getByLabel('제목', { exact: true }).fill('개인 일정');
  await personal.getByRole('button', { name: '추가', exact: true }).click();
  await expect(personal.locator('.events-list')).toContainText(week);
  await expect(personal.locator('.events-list')).toContainText('개인 일정');
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
