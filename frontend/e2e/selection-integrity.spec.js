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

test('shared address follows class selection and browser history', async ({ page }) => {
  await mockApi(page);
  await page.goto('/?source=test' + sharedHash(1));
  const classes = page.locator('.quick-class select').nth(1);
  await expect(classes).toHaveValue('1');
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목1');
  await classes.selectOption('2');
  await expect.poll(() => new URL(page.url()).hash).toContain('class=2');
  expect(new URL(page.url()).searchParams.get('source')).toBe('test');
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목2');
  await page.goBack();
  await expect(classes).toHaveValue('1');
  expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get('class')).toBe('1');
  await page.goForward();
  await expect(classes).toHaveValue('2');
  expect(new URLSearchParams(new URL(page.url()).hash.slice(1)).get('class')).toBe('2');
  await page.getByRole('button', { name: '학급 링크 복사' }).click();
  const shared = new URL(await page.getByLabel('공유 링크', { exact: true }).inputValue());
  expect(new URLSearchParams(shared.hash.slice(1)).get('class')).toBe('2');
});

test('notification settings link follows theme, keyboard and mobile layout', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => { if (!localStorage.getItem('opensigan-theme')) localStorage.setItem('opensigan-theme', 'light'); });
  await page.route('**/webhooks.html', (route) => route.fulfill({ contentType: 'text/html; charset=utf-8', body: '<h1>알림 관리</h1>' }));
  await page.goto('/');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  const link = page.getByRole('link', { name: '시간표 변경 알림 관리' });
  await expect(link).toHaveAttribute('href', './webhooks.html');
  for (const width of [320, 390, 800, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    const bounds = await link.boundingBox();
    expect(bounds.height).toBeGreaterThanOrEqual(44);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.keyboard.press('Tab');
  await link.focus();
  await expect(link).toBeFocused();
  await expect(link).toHaveCSS('outline-style', 'solid');
  await link.hover();
  await expect(link).toHaveCSS('color', 'rgb(17, 17, 17)');
  await page.getByRole('button', { name: '다크 모드로 전환' }).click();
  await expect(link).toHaveCSS('color', 'rgb(245, 245, 245)');
  await link.click();
  await expect(page.getByRole('heading', { name: '알림 관리' })).toBeVisible();
  await page.goBack();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect(link).toHaveCSS('color', 'rgb(245, 245, 245)');
});

test('build version appears only at the bottom of settings', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem('opensigan-theme', 'light'));
  await page.goto('/');
  const version = page.locator('.build-info');
  const expectedSha = (process.env.VITE_BUILD_SHA || process.env.GITHUB_SHA || '0123456789abcdef0123456789abcdef01234567').slice(0, 7);
  await expect(version).toHaveCount(1);
  await expect(version).toHaveText(`웹 버전 ${expectedSha}`);
  await expect(version).toBeHidden();
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(version).toBeHidden();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  const settings = page.locator('#settings-panel');
  await expect(settings.locator(':scope > .build-info')).toBeVisible();
  await expect(settings.locator(':scope > :last-child')).toHaveClass(/build-info/);
  for (const width of [320, 390, 800, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.getByRole('button', { name: '다크 모드로 전환' }).click();
  await expect(version).toBeVisible();
  await expect(version).toHaveText(`웹 버전 ${expectedSha}`);
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await expect(version).toBeHidden();
});

test('return action follows the timetable view and preserves the selected class', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => Object.defineProperty(navigator, 'share', { configurable: true, value: undefined }));
  await page.route('**/api/v1/timetable?*', (route) => {
    const requestedWeek = new URL(route.request().url()).searchParams.get('week');
    return route.fulfill({ json: {
      ...timetable, weekStart: requestedWeek,
      records: timetable.records.map((record) => ({ ...record, date: requestedWeek, teacher: '김교사' })),
    } });
  });
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/' + sharedHash(2));
  const panel = page.locator('#timetable-panel');
  const tabs = panel.getByRole('group', { name: '시간표 보기' });
  const backToToday = panel.getByRole('button', { name: '오늘로', exact: true });
  const backToWeek = panel.getByRole('button', { name: '이번 주로', exact: true });
  await expect(panel.locator('.quick-class select').nth(1)).toHaveValue('2');
  await expect(backToToday).toHaveCount(0);
  await expect(backToWeek).toHaveCount(0);
  await tabs.getByRole('button', { name: '오늘', exact: true }).click();
  await expect(panel.locator('.quick-class select').nth(1)).toHaveValue('2');
  await expect(backToToday).toHaveCount(0);
  await panel.getByLabel('날짜', { exact: true }).fill('2026-11-10');
  await panel.getByLabel('날짜', { exact: true }).blur();
  await expect(backToToday).toBeVisible();
  await backToToday.click();
  await expect(panel.getByLabel('날짜', { exact: true })).toHaveValue('2026-11-09');
  await expect(backToToday).toHaveCount(0);
  await panel.getByRole('button', { name: '다음 주', exact: true }).click();
  await expect(backToToday).toBeVisible();
  await expect(backToWeek).toHaveCount(0);
  await backToToday.click();
  await expect(panel.getByLabel('날짜', { exact: true })).toHaveValue('2026-11-09');
  await tabs.getByRole('button', { name: '이번 주', exact: true }).click();
  for (const tab of ['이번 주', '1학년', '교사']) {
    await tabs.getByRole('button', { name: tab, exact: true }).click();
    await expect(backToWeek).toHaveCount(0);
    await panel.getByRole('button', { name: '다음 주', exact: true }).click();
    await expect(backToWeek).toBeVisible();
    await expect(backToToday).toHaveCount(0);
    await backToWeek.click();
    await expect(backToWeek).toHaveCount(0);
    if (tab === '1학년') {
      await expect(panel.locator('.quick-class select')).toHaveCount(1);
      await expect(panel.locator('.quick-class select').first()).toHaveValue('1');
      await expect(panel.getByLabel('비교 날짜')).toHaveValue(week);
      await expect(panel.locator('.grade-compact')).toContainText('1반');
      await expect(panel.locator('.grade-compact')).toContainText('2반');
      await page.setViewportSize({ width: 1366, height: 844 });
      await expect(panel.getByRole('region', { name: '1학년 학급별 비교 시간표' })).toBeVisible();
      await page.setViewportSize({ width: 320, height: 844 });
    } else {
      await expect(panel.locator('.quick-class select').nth(1)).toHaveValue('2');
    }
  }
  await tabs.getByRole('button', { name: '이번 주', exact: true }).click();
  await expect(panel.locator('.quick-class select').nth(1)).toHaveValue('2');
  const download = page.waitForEvent('download');
  await panel.getByRole('button', { name: '이미지 저장·공유' }).click();
  expect((await download).suggestedFilename()).toMatch(/1학년2반_week_2026-11-09\.png$/);
  await page.getByRole('button', { name: '학급 링크 복사' }).click();
  const shared = new URL(await page.getByLabel('공유 링크', { exact: true }).inputValue());
  expect(new URLSearchParams(shared.hash.slice(1)).get('class')).toBe('2');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test('settings icon remains visible and aligned in both themes on desktop and mobile', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem('opensigan-theme', 'light'));
  await page.goto('/');
  const settings = page.getByRole('navigation', { name: '캘린더 메뉴' }).getByRole('button', { name: '설정', exact: true });
  const icon = settings.locator('svg');
  await expect(icon).toHaveAttribute('aria-hidden', 'true');
  for (const width of [320, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    for (const theme of ['light', 'dark']) {
      if (theme === 'dark') await page.getByRole('button', { name: '다크 모드로 전환' }).click();
      await expect(icon).toBeVisible();
      const box = await icon.boundingBox();
      const button = await settings.boundingBox();
      expect(box.width).toBeGreaterThanOrEqual(18);
      expect(box.height).toBeGreaterThanOrEqual(18);
      expect(box.x).toBeGreaterThanOrEqual(button.x);
      expect(box.x + box.width).toBeLessThanOrEqual(button.x + button.width);
      expect(box.y).toBeGreaterThanOrEqual(button.y);
      expect(box.y + box.height).toBeLessThanOrEqual(button.y + button.height);
      const colors = await settings.evaluate((node) => ({ icon: getComputedStyle(node.querySelector('svg')).stroke, text: getComputedStyle(node).color }));
      expect(colors.icon).toBe(colors.text);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      if (theme === 'dark') await page.getByRole('button', { name: '라이트 모드로 전환' }).click();
    }
  }
  await settings.click();
  await expect(page.getByRole('heading', { name: '설정', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '기존 개인 데이터 내보내기' })).toHaveCount(0);
});

test('collapsed settings cards align and remain keyboard accessible across themes and widths', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem('opensigan-theme', 'light'));
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  for (const width of [320, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    for (const theme of ['light', 'dark']) {
      if (theme === 'dark') await page.getByRole('button', { name: '다크 모드로 전환' }).click();
      const boxes = await page.locator('.settings-cards > details').evaluateAll((cards) => cards.map((card) => {
        const bounds = card.getBoundingClientRect();
        return { height: bounds.height, left: bounds.left, width: bounds.width, border: getComputedStyle(card).borderTopWidth };
      }));
      expect(boxes.length).toBeGreaterThan(4);
      for (const box of boxes) {
        expect(Math.abs(box.height - boxes[0].height)).toBeLessThan(1);
        expect(Math.abs(box.left - boxes[0].left)).toBeLessThan(1);
        expect(Math.abs(box.width - boxes[0].width)).toBeLessThan(1);
        expect(box.border).toBe('1px');
      }
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      if (theme === 'dark') await page.getByRole('button', { name: '라이트 모드로 전환' }).click();
    }
  }
  const summary = page.getByText('일반 설정', { exact: true });
  await summary.focus();
  await expect(summary).toBeFocused();
  await summary.press('Enter');
  await expect(page.getByLabel('테마', { exact: true })).toBeVisible();
});

test('settings groups keep advanced controls separate and restore expanded state after search', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('일반 설정', { exact: true }).click();
  await expect(page.getByLabel('테마', { exact: true })).toBeVisible();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await expect(page.getByLabel('시간표에 교사 표시')).toBeVisible();
  await expect(page.getByLabel('과목 색상', { exact: true })).toBeHidden();
  const search = page.getByRole('searchbox', { name: '설정 검색' });
  await search.fill('과목');
  const results = page.getByRole('list', { name: '설정 검색 결과' });
  await expect(results.getByRole('button', { name: '과목 색상 과목·교사 상세 설정', exact: true })).toBeVisible();
  await expect(results.getByRole('button', { name: /교사 표시 이름/ })).toHaveCount(0);
  await expect(page.getByLabel('시간표에 교사 표시')).toBeHidden();
  await expect(page.getByText('학교 교시 시각 설정', { exact: true })).toBeHidden();
  await search.clear();
  await expect(page.getByLabel('테마', { exact: true })).toBeVisible();
  await expect(page.getByLabel('시간표에 교사 표시')).toBeVisible();
  await expect(page.getByLabel('과목 색상', { exact: true })).toBeHidden();
  await search.fill('과목 색상');
  await results.getByRole('button', { name: '과목 색상 과목·교사 상세 설정', exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('과목 색상', { exact: true })).toBeFocused();
  await page.getByLabel('과목 색상', { exact: true }).selectOption('auto');
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('과목·교사 상세 설정', { exact: true }).click();
  await expect(page.getByLabel('과목 색상', { exact: true })).toHaveValue('auto');
});

test('subject settings manage several colors and aliases with school and class isolation', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((id) => {
    const key = 'opensigan-display:' + id;
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({ subjectAliases: { '이전과목': '이전별칭' } }));
  }, school.id);
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('과목·교사 상세 설정', { exact: true }).click();
  await page.getByLabel('과목 색상', { exact: true }).selectOption('custom');
  await page.getByText('과목 색상·표시 이름 관리', { exact: true }).click();
  await expect(page.getByLabel('이전과목 표시 이름', { exact: true })).toHaveValue('이전별칭');
  await page.getByLabel('과목1 표시 이름', { exact: true }).fill('수학');
  await page.getByLabel('과목1 표시 이름', { exact: true }).press('Tab');
  await page.getByLabel('과목1 색상', { exact: true }).fill('#123456');
  await page.getByLabel('과목2 표시 이름', { exact: true }).fill('과학');
  await page.getByLabel('과목2 표시 이름', { exact: true }).press('Tab');
  await page.getByLabel('과목2 색상', { exact: true }).fill('#abcdef');
  await expect(page.getByLabel('과목1 색상', { exact: true })).toHaveValue('#123456');
  await expect(page.getByLabel('과목2 색상', { exact: true })).toHaveValue('#abcdef');
  await page.getByLabel('과목 목록 검색').fill('이전별칭');
  await expect(page.getByLabel('이전과목 표시 이름', { exact: true })).toBeVisible();
  await expect(page.getByLabel('과목1 표시 이름', { exact: true })).toHaveCount(0);
  await page.getByLabel('과목 목록 검색').clear();
  await page.getByRole('button', { name: '과목2 설정 초기화' }).click();
  await expect(page.getByLabel('과목2 표시 이름', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('과목1 색상', { exact: true })).toHaveValue('#123456');
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await page.getByLabel('1학년 1반만 따로 설정').check();
  await page.getByLabel('과목1 표시 이름', { exact: true }).fill('학급 수학');
  await page.getByLabel('과목1 표시 이름', { exact: true }).press('Tab');
  await page.getByLabel('1학년 1반만 따로 설정').uncheck();
  await expect(page.getByLabel('과목1 표시 이름', { exact: true })).toHaveValue('수학');
  for (const width of [320, 390, 800, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.getByRole('button', { name: '다크 모드로 전환' }).click();
  await expect(page.getByLabel('과목1 색상', { exact: true })).toHaveValue('#123456');
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('과목·교사 상세 설정', { exact: true }).click();
  await page.getByText('과목 색상·표시 이름 관리', { exact: true }).click();
  await expect(page.getByLabel('과목1 표시 이름', { exact: true })).toHaveValue('수학');
  await expect(page.getByLabel('과목1 색상', { exact: true })).toHaveValue('#123456');
  await expect(page.getByLabel('이전과목 표시 이름', { exact: true })).toHaveValue('이전별칭');
});

test('subject colors update immediately and respect school and class settings', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('table')).toContainText('과목1');
  const lesson = panel.getByRole('table').locator('strong', { hasText: '과목1' });
  const settings = page.getByRole('button', { name: '설정', exact: true });
  const timetableTab = page.getByRole('button', { name: '시간표', exact: true });
  await settings.click();
  await page.getByText('과목·교사 상세 설정', { exact: true }).click();
  await page.getByLabel('과목 색상', { exact: true }).selectOption('custom');
  await page.getByText('과목 색상·표시 이름 관리', { exact: true }).click();
  await page.getByLabel('과목1 색상', { exact: true }).fill('#123456');
  await timetableTab.click();
  await expect(lesson).toHaveCSS('background-color', 'rgb(18, 52, 86)');
  await settings.click();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await page.getByLabel('1학년 1반만 따로 설정').check();
  await page.getByLabel('과목1 색상', { exact: true }).fill('#abcdef');
  await timetableTab.click();
  await expect(lesson).toHaveCSS('background-color', 'rgb(171, 205, 239)');
  await settings.click();
  await page.getByLabel('1학년 1반만 따로 설정').uncheck();
  await timetableTab.click();
  await expect(lesson).toHaveCSS('background-color', 'rgb(18, 52, 86)');
  await settings.click();
  await page.getByRole('button', { name: '과목1 설정 초기화' }).click();
  await timetableTab.click();
  await expect(lesson).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
});

test('multiple teacher aliases include saved names and affect timetable search', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript((id) => {
    const key = 'opensigan-display:' + id;
    if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({ teacherAliases: { '이전교사': '이전별칭' } }));
  }, school.id);
  await page.route('**/api/v1/timetable?*', (route) => route.fulfill({ json: {
    ...timetable, records: timetable.records.map((record, index) => ({ ...record, teacher: index ? '이교사' : '김교사' })),
  } }));
  await page.setViewportSize({ width: 320, height: 844 });
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('과목·교사 상세 설정', { exact: true }).click();
  await page.getByText('교사 표시 이름 관리', { exact: true }).click();
  await expect(page.getByLabel('이전교사 표시 이름', { exact: true })).toHaveValue('이전별칭');
  await page.getByLabel('김교사 표시 이름', { exact: true }).fill('김T');
  await page.getByLabel('김교사 표시 이름', { exact: true }).press('Tab');
  await page.getByLabel('이교사 표시 이름', { exact: true }).fill('이T');
  await page.getByLabel('이교사 표시 이름', { exact: true }).press('Tab');
  await page.getByLabel('교사 목록 검색').fill('이전별칭');
  await expect(page.getByLabel('이전교사 표시 이름', { exact: true })).toBeVisible();
  await expect(page.getByLabel('김교사 표시 이름', { exact: true })).toHaveCount(0);
  await page.getByLabel('교사 목록 검색').clear();
  await page.getByRole('button', { name: '이교사 표시 이름 초기화' }).click();
  await expect(page.getByLabel('이교사 표시 이름', { exact: true })).toHaveValue('');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await page.getByRole('group', { name: '시간표 보기' }).getByRole('button', { name: '교사', exact: true }).click();
  await page.getByLabel('교사별 주간 시간표').fill('김T');
  await expect(page.getByRole('region', { name: /김T 선생님 주간 시간표/ })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('과목·교사 상세 설정', { exact: true }).click();
  await page.getByText('교사 표시 이름 관리', { exact: true }).click();
  await expect(page.getByLabel('김교사 표시 이름', { exact: true })).toHaveValue('김T');
  await expect(page.getByLabel('이전교사 표시 이름', { exact: true })).toHaveValue('이전별칭');
});

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
  await page.getByText('상세 시간 설정하기', { exact: true }).click();
  await page.getByLabel('1교시 시작', { exact: true }).fill('08:30');
  await page.getByLabel('1교시 종료', { exact: true }).fill('09:20');
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
  await expect(page.getByLabel('1교시 시작', { exact: true })).toHaveValue('08:30');
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('시간표 표시 설정', { exact: true }).click();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await page.getByText('상세 시간 설정하기', { exact: true }).click();
  await expect(page.getByLabel('시간표에 교사 표시')).not.toBeChecked();
  await expect(page.getByLabel('1교시 종료', { exact: true })).toHaveValue('09:20');
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

test('history controls are absent while source change badges remain visible', async ({ page }) => {
  await mockApi(page);
  let historyRequests = 0;
  await page.route('**/api/v1/timetable?*', (route) => route.fulfill({ json: {
    ...timetable, records: timetable.records.map((record) => ({ ...record, teacher: '김교사', isChanged: true })),
  } }));
  await page.route('**/api/v1/timetable/history?*', (route) => { historyRequests++; return route.fulfill({ status: 503, json: { code: 'history_disabled' } }); });
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await expect(panel.locator('.change-label').first()).toBeVisible();
  await expect(panel.getByRole('button', { name: /시간표 변경 이력/ })).toHaveCount(0);
  await expect(panel.getByText(/변경 이력은 현재 제공되지 않아요/)).toHaveCount(0);
  await expect(panel.locator('.history-section')).toHaveCount(0);
  const views = panel.getByRole('group', { name: '시간표 보기' });
  await views.getByRole('button', { name: '오늘', exact: true }).click();
  await expect(panel.locator('.change-label').first()).toBeVisible();
  await views.getByRole('button', { name: '1학년', exact: true }).click();
  await expect(panel.locator('.change-label:visible').first()).toBeVisible();
  await views.getByRole('button', { name: '교사', exact: true }).click();
  await panel.getByLabel('교사별 주간 시간표').fill('김교사');
  await expect(panel.locator('.change-label').first()).toBeVisible();
  expect(historyRequests).toBe(0);
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

test('today view shows matching meals on wide screens without changing meal tab date', async ({ page }) => {
  await mockApi(page);
  const mealRequests = [];
  await page.route('**/api/v1/meals?*', (route) => {
    const from = new URL(route.request().url()).searchParams.get('from');
    mealRequests.push(from);
    return route.fulfill({ json: { meals: [{ date: from, type: '중식', dishes: ['식단 ' + from] }, { date: '2026-11-10', type: '중식', dishes: ['화요일 식단'] }], stale: false } });
  });
  await page.setViewportSize({ width: 1366, height: 844 });
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('table')).toContainText('과목1');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.locator('#meals-panel .meal-day')).toContainText('식단 2026-11-09');
  await page.getByLabel('날짜 선택').fill('2026-11-16');
  await page.getByLabel('날짜 선택').blur();
  await expect(page.locator('#meals-panel .meal-day')).toContainText('식단 2026-11-16');
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await panel.getByRole('button', { name: '오늘', exact: true }).click();
  const aside = panel.locator('.today-meals');
  await expect(aside).toBeVisible();
  await expect(panel.getByRole('complementary', { name: /급식/ })).toBeVisible();
  await panel.locator('#today-date').focus();
  await expect(panel.locator('#today-date')).toBeFocused();
  await expect(aside).toContainText('식단 2026-11-09');
  const before = mealRequests.filter((from) => from === '2026-11-09').length;
  await panel.locator('#today-date').fill('2026-11-10');
  await panel.locator('#today-date').blur();
  await expect(aside).toContainText('화요일 식단');
  expect(mealRequests.filter((from) => from === '2026-11-09').length).toBe(before);
  for (const width of [320, 375, 390, 640, 768, 820]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(aside).toBeHidden();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  for (const width of [1024, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(aside).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await panel.getByRole('button', { name: '이번 주', exact: true }).click();
  await expect(aside).toHaveCount(0);
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByLabel('날짜 선택')).toHaveValue('2026-11-16');
  await expect(page.locator('#meals-panel .meal-day')).toContainText('식단 2026-11-16');
});

test('today columns show timetable and meal failures independently', async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1280, height: 844 });
  await page.route('**/api/v1/timetable?*', (route) => route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } }));
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await panel.getByRole('button', { name: '오늘', exact: true }).click();
  await expect(panel.getByRole('alert')).toContainText('시간표');
  await expect(panel.locator('.today-meals')).toContainText('식단 2026-11-09');
});

test('today timetable remains visible when meal lookup fails', async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1280, height: 844 });
  await page.route('**/api/v1/meals?*', (route) => route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } }));
  await page.goto('/' + sharedHash(1));
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('table')).toContainText('과목1');
  await panel.getByRole('button', { name: '오늘', exact: true }).click();
  await expect(panel.locator('.lesson-list')).toContainText('과목1');
  await expect(panel.locator('.today-meals').getByRole('alert')).toContainText('급식을 불러오지 못했어요');
});

test('meal return button follows day, week and Korea midnight', async ({ page }) => {
  await mockApi(page);
  await page.clock.setFixedTime(new Date('2026-11-15T14:59:00Z'));
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const panel = page.locator('#meals-panel');
  const back = panel.getByRole('button', { name: '오늘로', exact: true });
  const date = panel.getByLabel('날짜 선택');
  await expect(date).toHaveValue('2026-11-15');
  await expect(back).toHaveCount(0);
  await panel.getByRole('button', { name: '이전 날짜' }).click();
  await expect(back).toBeVisible();
  await back.click();
  await expect(date).toHaveValue('2026-11-15');
  await panel.getByRole('button', { name: '주간 식단' }).click();
  await expect(back).toHaveCount(0);
  await panel.getByRole('button', { name: '이전 급식 주' }).click();
  await expect(back).toBeVisible();
  await back.click();
  await expect(back).toHaveCount(0);
  await date.fill('2026-11-14');
  await date.blur();
  await expect(back).toHaveCount(0);
  await page.clock.setFixedTime(new Date('2026-11-15T15:01:00Z'));
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(back).toBeVisible();
  await back.click();
  await expect(date).toHaveValue('2026-11-16');
  await expect(back).toHaveCount(0);
  await panel.getByRole('button', { name: '하루 식단' }).click();
  await expect(back).toHaveCount(0);
});

test('meal loading, failure and an empty successful response are distinct', async ({ page }) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  let calls = 0;
  await mockApi(page);
  await page.route('**/api/v1/meals?*', async (route) => {
    calls += 1;
    if (calls === 1) {
      await pending;
      return route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } });
    }
    return route.fulfill({ json: { meals: [], stale: false } });
  });
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const panel = page.locator('#meals-panel');
  await expect(panel.getByRole('status').filter({ hasText: '식단을 불러오고 있어요' })).toBeVisible();
  release();
  await expect(panel.getByRole('alert')).toContainText('급식을 불러오지 못했어요');
  await expect(panel.getByRole('alert')).toContainText('표시할 급식 정보가 없어요');
  await expect(panel.getByText('이 날짜에 등록된 식단이 없어요.')).toHaveCount(0);
  await panel.getByRole('button', { name: '다시 시도' }).click();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(panel.getByText('이 날짜에 등록된 식단이 없어요.')).toBeVisible();
});

test('failed meal refresh marks retained meals stale until a retry succeeds', async ({ page }) => {
  await mockApi(page);
  let calls = 0;
  await page.route('**/api/v1/meals?*', (route) => {
    calls += 1;
    if (calls === 2) return route.fulfill({ status: 503, json: { code: 'upstream_unavailable' } });
    return route.fulfill({ json: { meals: [{ date: week, type: '중식', dishes: [calls === 1 ? '이전 식단' : '갱신 식단'] }], stale: false } });
  });
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const panel = page.locator('#meals-panel');
  await expect(panel).toContainText('이전 식단');
  await page.clock.setFixedTime(new Date('2026-11-09T02:31:00Z'));
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(panel.getByRole('alert')).toContainText('이전 급식 정보를 표시');
  await expect(panel.getByRole('status').filter({ hasText: '저장된 급식 정보' })).toBeVisible();
  await expect(panel).toContainText('이전 식단');
  await panel.getByRole('button', { name: '다시 시도' }).click();
  await expect(panel).toContainText('갱신 식단');
  await expect(panel.getByRole('status').filter({ hasText: '저장된 급식 정보' })).toHaveCount(0);
  await expect(panel.getByRole('alert')).toHaveCount(0);
});

test('stale meal data and hidden meal types are identified on mobile and desktop', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('opensigan-meal-preferences', JSON.stringify({ view: 'day', types: ['조식'], showAllergenNumbers: true })));
  await mockApi(page);
  await page.route('**/api/v1/meals?*', (route) => route.fulfill({ json: { meals: [{ date: week, type: '중식', dishes: ['밥'] }], stale: true } }));
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const panel = page.locator('#meals-panel');
  await expect(panel.getByRole('status').filter({ hasText: '저장된 급식 정보' })).toBeVisible();
  await expect(panel.getByText('표시하도록 설정한 식사에 등록된 식단이 없어요.')).toBeVisible();
  for (const width of [320, 390, 800, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
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
  await expect(panel.getByRole('alert')).toContainText('시간표나 급식 데이터를 불러오지');
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
  await expect(panel.getByRole('alert')).toContainText('시간표나 급식 데이터를 불러오지');
  await expect(panel.getByRole('table')).toHaveCount(0);
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('김치볶음밥(5.6)').first()).toBeVisible();
  fail = false;
  await page.getByRole('button', { name: '시간표', exact: true }).click();
  await panel.getByRole('button', { name: '다시 시도' }).click();
  await expect(panel.getByRole('table')).toContainText('과목1');
  await expect(panel.getByRole('alert')).toHaveCount(0);
});

test('rate limited timetable shows retry delay without blocking meals and recovers', async ({ page }) => {
  await page.addInitScript((savedSchool) => {
    localStorage.setItem('opensigan-school', JSON.stringify(savedSchool));
    localStorage.setItem('opensigan-grade', '1');
    localStorage.setItem('opensigan-class', '1');
    localStorage.removeItem('opensigan-offline-timetable');
  }, school);
  await mockApi(page);
  let blocked = true;
  await page.route('**/api/v1/timetable?*', (route) => blocked
    ? route.fulfill({ status: 429, headers: { 'Retry-After': '17' }, json: { code: 'rate_limited' } })
    : route.fulfill({ json: timetable }));
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await expect(panel.getByRole('alert')).toContainText('요청이 너무 많아요');
  await expect(panel.getByRole('alert')).toContainText('17초 후 다시 시도');
  await expect(panel.getByRole('alert')).toContainText('이 학교와 주에 저장된 시간표가 없어요');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('김치볶음밥(5.6)').first()).toBeVisible();
  blocked = false;
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
  await page.reload();
  await search.fill('봄빛고');
  await expect(page.locator('.search-results p').filter({ hasText: '이 검색어의 저장된 결과가 없어요' })).toBeVisible();
  await search.fill('봄빛');
  await expect(page.locator('.search-results p').filter({ hasText: '이 기기에 저장된 검색 결과' })).toBeVisible();
  await expect(page.getByRole('button', { name: /봄빛고등학교/ })).toBeVisible();
  fail = false;
  await page.getByRole('button', { name: '학교 검색 다시 시도' }).click();
  await expect(page.getByRole('button', { name: /봄빛고등학교/ })).toBeVisible();
  await expect(page.locator('.search-results p').filter({ hasText: '이 기기에 저장된 검색 결과' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '학교 검색 다시 시도' })).toHaveCount(0);
});

test('meal menu search, allergy filters, NEIS details and timetable date link work together', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('opensigan-allergies', '[1]'); localStorage.setItem('opensigan-theme', 'light'); });
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('열량(NEIS 원문): 650 kcal')).toBeVisible();
  await expect(page.locator('.meal-filter-note')).toHaveCount(0);
  const allergyWarning = page.locator('.meal-types li.warning').filter({ hasText: '계란말이' });
  await expect(allergyWarning).toContainText('⚠ 주의: 1. 난류');
  await expect(allergyWarning).toHaveCSS('border-left-color', 'rgb(196, 38, 61)');
  await page.getByRole('searchbox', { name: '메뉴 검색' }).fill('김치');
  await expect(page.getByText('김치볶음밥(5.6)')).toBeVisible();
  await expect(page.getByText('계란말이(1.2)')).toHaveCount(0);
  await page.getByRole('searchbox', { name: '메뉴 검색' }).fill('');
  await page.getByRole('searchbox', { name: '메뉴 검색' }).blur();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('급식 설정', { exact: true }).click();
  await page.getByText('알레르기 관리 (1개 선택)', { exact: true }).click();
  await page.getByLabel('메뉴 표시 방식').selectOption('marked');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('알레르기 필터 적용 중', { exact: false })).toBeVisible();
  await expect(page.locator('.meal-filter-note')).toContainText('선택한 알레르기 1개');
  await expect(page.getByText('계란말이(1.2)')).toBeVisible();
  await expect(page.getByText('김치볶음밥(5.6)')).toHaveCount(0);
  await page.getByRole('button', { name: '알레르기 설정', exact: true }).click();
  await expect(page.getByLabel('메뉴 표시 방식')).toBeFocused();
  await page.getByLabel('메뉴 표시 방식').selectOption('unmarked');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('김치볶음밥(5.6)')).toBeVisible();
  await expect(page.getByText('계란말이(1.2)')).toHaveCount(0);
  await expect(page.getByText(/미표시 메뉴도 안전을 보장하지 않습니다/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText('김치볶음밥(5.6)')).toBeVisible();
  await expect(page.getByText('계란말이(1.2)')).toHaveCount(0);
  await page.getByRole('searchbox', { name: '메뉴 검색' }).fill('계란');
  await expect(page.getByText('검색·필터에 맞는 메뉴가 없어요.')).toBeVisible();
  await page.getByRole('searchbox', { name: '메뉴 검색' }).clear();
  await page.getByRole('button', { name: '주간 식단' }).click();
  await expect(page.getByText('김치볶음밥(5.6)')).toBeVisible();
  await page.getByRole('button', { name: '하루 식단' }).click();
  await page.getByRole('button', { name: '알레르기 설정', exact: true }).click();
  await page.getByRole('checkbox', { name: '1. 난류' }).uncheck();
  await page.getByLabel('메뉴 표시 방식').selectOption('marked');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText(/주의 알레르기를 선택해 주세요/)).toBeVisible();
  await expect(page.locator('.meal-filter-note')).toContainText('선택한 알레르기 0개');
  await expect(page.getByText('검색·필터에 맞는 메뉴가 없어요.')).toBeVisible();
  await page.getByRole('button', { name: '알레르기 설정', exact: true }).click();
  await page.getByRole('checkbox', { name: '1. 난류' }).check();
  await page.getByLabel('메뉴 표시 방식').selectOption('unmarked');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await page.setViewportSize({ width: 320, height: 844 });
  await page.getByRole('button', { name: '다크 모드로 전환' }).click();
  await expect(page.getByText(/알레르기 필터 적용 중/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  await page.getByText('영양·원산지 정보').click();
  await expect(page.locator('.meal-source-text').first()).toContainText('탄수화물 : 90g');
  await expect(page.getByText('원산지: 쌀: 국내산')).toBeVisible();
  await page.getByRole('button', { name: '이 날짜 시간표' }).click();
  await expect(page.locator('#timetable-panel')).toBeVisible();
  await expect(page.locator('#today-date')).toHaveValue(week);
});

test('active allergy filter remains visible without a selected school or meal data', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem('opensigan-meal-allergy-filter', 'unmarked'));
  await page.goto('/');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.locator('#meals-panel').getByText('학교를 먼저 선택해 주세요')).toBeVisible();
  const note = page.locator('.meal-filter-note');
  await expect(note).toContainText('선택한 알레르기 0개');
  await expect(note).toContainText('미표시 메뉴도 안전을 보장하지 않습니다');
  await page.reload();
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(note).toBeVisible();
  await note.getByRole('button', { name: '알레르기 설정' }).click();
  await expect(page.getByLabel('메뉴 표시 방식')).toBeFocused();
});

test('active allergy filter is visible when the school has no meals', async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem('opensigan-meal-allergy-filter', 'marked'));
  await page.route('**/api/v1/meals?*', (route) => route.fulfill({ json: { meals: [], stale: false } }));
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.locator('.meal-filter-note')).toContainText('선택한 알레르기 0개');
  await expect(page.getByRole('button', { name: '알레르기 설정' })).toBeVisible();
});

test('meal settings keep allergy preferences and allow search navigation into the nested panel', async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('opensigan-allergies')) localStorage.setItem('opensigan-allergies', '[1]');
    if (!localStorage.getItem('opensigan-meal-preferences')) localStorage.setItem('opensigan-meal-preferences', JSON.stringify({ view: 'day', types: ['중식'], showAllergenNumbers: true }));
  });
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('급식 설정', { exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '중식', exact: true })).toBeChecked();
  await expect(page.getByText('알레르기 관리 (1개 선택)', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '1. 난류' })).toBeHidden();
  await page.getByRole('searchbox', { name: '설정 검색' }).fill('알레르기');
  await page.getByRole('list', { name: '설정 검색 결과' }).getByRole('button', { name: /알레르기 관리/ }).click();
  await expect(page.getByRole('checkbox', { name: '1. 난류' })).toBeChecked();
  await page.getByRole('checkbox', { name: '2. 우유' }).check();
  await expect.poll(() => page.evaluate(() => localStorage.getItem('opensigan-allergies'))).toBe('[1,2]');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  await expect(page.getByText(/주의: 1\. 난류, 2\. 우유/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('급식 설정', { exact: true }).click();
  await page.getByText('알레르기 관리 (2개 선택)', { exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '2. 우유' })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: '중식', exact: true })).toBeChecked();
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
  await page.getByRole('searchbox', { name: '설정 검색' }).fill('알레르기');
  await expect(page.getByRole('list', { name: '설정 검색 결과' }).getByRole('button', { name: /알레르기 관리/ })).toBeVisible();
  await expect(page.getByText('학교 교시 시각 설정', { exact: true })).toBeHidden();
  for (const width of [320, 800, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
  await page.getByRole('searchbox', { name: '설정 검색' }).fill('일치하지않는설정');
  await expect(page.getByText('일치하는 설정이 없어요.')).toBeVisible();
});

test('timed calendar includes bell times only after explicit consent and closes correctly', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByRole('searchbox', { name: '설정 검색' }).fill('교시');
  await page.getByRole('list', { name: '설정 검색 결과' }).getByRole('button', { name: '1교시 시작 상세 시간 설정하기', exact: true }).click();
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

test('lesson time rules preview lunch and require explicit application and saving', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await page.getByLabel('1교시 시작 시각').fill('08:15');
  await page.getByLabel('수업 시간 (분)').fill('50');
  await page.getByLabel('기본 쉬는 시간 (분)').fill('10');
  await page.getByLabel('점심시간 시작').selectOption('4');
  await page.getByLabel('점심시간 길이 (분)').fill('60');
  await expect(page.getByLabel('계산된 교시 시각 미리보기')).toContainText('5교시 13:05–13:55');
  await page.getByText('상세 시간 설정하기', { exact: true }).click();
  await expect(page.getByLabel('1교시 시작', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: '계산값 입력란에 적용' }).click();
  await expect(page.getByLabel('5교시 시작', { exact: true })).toHaveValue('13:05');
  await page.getByLabel('5교시 시작', { exact: true }).fill('13:10');
  await page.getByRole('button', { name: '5교시 계산값으로 되돌리기' }).click();
  await expect(page.getByLabel('5교시 시작', { exact: true })).toHaveValue('13:05');
  await page.getByLabel('5교시 시작', { exact: true }).fill('12:00');
  await page.getByRole('button', { name: '시각 저장', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: /겹치거나 순서가 맞지/ })).toBeVisible();
  expect(await page.evaluate((id) => localStorage.getItem('opensigan-lesson-times:' + id), school.id)).toBeNull();
  await page.getByLabel('5교시 시작', { exact: true }).fill('13:10');
  expect(await page.evaluate((id) => localStorage.getItem('opensigan-lesson-times:' + id), school.id)).toBeNull();
  await page.getByRole('button', { name: '시각 저장', exact: true }).click();
  await expect(page.getByText('이 학교의 교시 시각을 저장했어요.')).toBeVisible();
  expect(JSON.parse(await page.evaluate((id) => localStorage.getItem('opensigan-lesson-times:' + id), school.id))[5].start).toBe('13:10');
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await expect(page.getByLabel('1교시 시작 시각')).toHaveValue('08:15');
  await expect(page.getByLabel('수업 시간 (분)')).toHaveValue('50');
  await expect(page.getByLabel('기본 쉬는 시간 (분)')).toHaveValue('10');
  await expect(page.getByLabel('점심시간 시작')).toHaveValue('4');
  await expect(page.getByLabel('점심시간 길이 (분)')).toHaveValue('60');
  await page.getByText('상세 시간 설정하기', { exact: true }).click();
  await expect(page.getByLabel('5교시 시작', { exact: true })).toHaveValue('13:10');
  await expect(page.getByLabel('계산된 교시 시각 미리보기')).toContainText('5교시 13:05–13:55');
});

test('weekday bell times save independently and are included in school backup', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('.quick-class select').nth(1)).toHaveValue('1');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await page.getByText('상세 시간 설정하기', { exact: true }).click();
  await page.getByLabel('1교시 시작', { exact: true }).fill('09:00');
  await page.getByLabel('1교시 종료', { exact: true }).fill('09:50');
  await page.getByText('요일별 예외 시각', { exact: true }).click();
  await page.getByLabel('요일 선택').selectOption('2');
  await page.getByLabel('요일별 1교시 시작').fill('10:00');
  await page.getByLabel('요일별 1교시 종료').fill('10:50');
  await page.getByRole('button', { name: '시각 저장', exact: true }).click();
  await expect(page.getByText('이 학교의 교시 시각을 저장했어요.')).toBeVisible();
  await page.getByText('설정 백업·복원', { exact: true }).click();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '학교 설정 파일 저장' }).click();
  const chunks = [];
  for await (const chunk of await (await download).createReadStream()) chunks.push(chunk);
  const backupFile = Buffer.concat(chunks);
  const backup = JSON.parse(backupFile.toString());
  expect(backup.version).toBe(2);
  expect(backup.weekdayLessonTimes['2']['1'].start).toBe('10:00');
  await page.reload();
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await page.getByText('요일별 예외 시각', { exact: true }).click();
  await page.getByLabel('요일 선택').selectOption('2');
  await expect(page.getByLabel('요일별 1교시 시작')).toHaveValue('10:00');
  await page.getByRole('button', { name: '시각 초기화' }).click();
  await page.getByText('설정 백업·복원', { exact: true }).click();
  await page.getByLabel('Opencigan 설정 JSON 파일 불러오기').setInputFiles({ name: 'school.json', mimeType: 'application/json', buffer: backupFile });
  await expect(page.getByText('현재 학교의 설정을 복원했어요.')).toBeVisible();
  await expect(page.getByLabel('요일별 1교시 시작')).toHaveValue('10:00');
});

test('invalid lesson times identify the affected inputs and preserve saved times', async ({ page }) => {
  await mockApi(page);
  await page.goto('/' + sharedHash(1));
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.getByText('학교 교시 시각 설정', { exact: true }).click();
  await page.getByText('상세 시간 설정하기', { exact: true }).click();
  await page.getByLabel('1교시 시작', { exact: true }).fill('09:00');
  await page.getByLabel('1교시 종료', { exact: true }).fill('09:50');
  await page.getByLabel('2교시 시작', { exact: true }).fill('10:00');
  await page.getByLabel('2교시 종료', { exact: true }).fill('10:50');
  await page.getByRole('button', { name: '시각 저장', exact: true }).click();
  await expect(page.getByText('이 학교의 교시 시각을 저장했어요.')).toBeVisible();
  const stored = await page.evaluate((id) => localStorage.getItem('opensigan-lesson-times:' + id), school.id);
  await page.getByLabel('1교시 종료', { exact: true }).fill('08:00');
  await page.getByRole('button', { name: '시각 저장', exact: true }).press('Enter');
  await expect(page.getByRole('alert').filter({ hasText: /1교시 종료 시각은 시작 시각보다 늦어야/ })).toBeVisible();
  await expect(page.getByLabel('1교시 종료', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  expect(await page.evaluate((id) => localStorage.getItem('opensigan-lesson-times:' + id), school.id)).toBe(stored);
  await page.getByLabel('1교시 종료', { exact: true }).fill('09:50');
  await page.getByText('요일별 예외 시각', { exact: true }).click();
  await page.getByLabel('요일 선택').selectOption('2');
  await page.getByLabel('요일별 1교시 시작').fill('09:30');
  await page.getByLabel('요일별 1교시 종료').fill('10:10');
  await page.getByRole('button', { name: '시각 저장', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: /화요일.*겹치/ })).toBeVisible();
  await expect(page.getByLabel('요일별 1교시 시작')).toHaveAttribute('aria-invalid', 'true');
  expect(await page.evaluate((id) => localStorage.getItem('opensigan-lesson-times:' + id), school.id)).toBe(stored);
});

test('retired personal timetable preserves and exports data from all classes', async ({ page }) => {
  await mockApi(page);
  const saved = [
    { key: `personal_timetable_v1:${school.id}:1:1`, value: JSON.stringify({ version: 1, entries: [{ subject: '개인 수업' }], events: [{ title: '개인 일정' }] }) },
    { key: 'personal_timetable_v1:다른학교:2:3', value: '{기존 원문 그대로' },
  ];
  await page.addInitScript((records) => {
    for (const { key, value } of records) if (!localStorage.getItem(key)) localStorage.setItem(key, value);
    localStorage.setItem('unrelated-setting', 'do-not-export');
  }, saved);
  await page.goto('/' + sharedHash(1));
  await expect(page.locator('#timetable-panel').getByRole('table')).toContainText('과목1');
  await expect(page.locator('#timetable-panel')).not.toContainText('개인 수업');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await expect(page.getByText('개인 시간표·일정', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('region', { name: '개인 시간표', exact: true })).toHaveCount(0);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: '기존 개인 데이터 내보내기' }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe('opencigan-personal-data.json');
  const chunks = [];
  for await (const chunk of await file.createReadStream()) chunks.push(chunk);
  const backup = JSON.parse(Buffer.concat(chunks).toString());
  expect(backup.format).toBe('opencigan-personal-data');
  expect(backup.entries).toEqual(expect.arrayContaining(saved));
  expect(backup.entries).toHaveLength(2);
  await page.reload();
  for (const { key, value } of saved) expect(await page.evaluate((k) => localStorage.getItem(k), key)).toBe(value);
});
