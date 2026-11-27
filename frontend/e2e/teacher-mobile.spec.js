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
  await panel.getByRole('searchbox', { name: '교사별 주간 시간표' }).fill('김');
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

for (const viewport of [{ width: 320, height: 700 }, { width: 375, height: 812 }, { width: 390, height: 844 }, { width: 667, height: 375 }, { width: 700, height: 844 }, { width: 768, height: 1024 }, { width: 960, height: 800 }, { width: 1280, height: 800 }]) {
  for (const theme of ['light', 'dark']) {
    test(`weekly timetable stays usable at ${viewport.width}px in ${theme} mode`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const school = { id: '2:봄빛고등학교', name: '아주 긴 이름의 봄빛고등학교', region: '서울' };
      await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
      await page.addInitScript(({ school, theme }) => {
        localStorage.setItem('opensigan-school', JSON.stringify(school));
        localStorage.setItem('opensigan-theme', theme);
      }, { school, theme });
      await page.route('**/api/v1/**', async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
          schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z',
          sourceUpdatedAt: null, stale: false, records: [
            { grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '아주 긴 과목 이름 하나', teacher: '김교사', isChanged: false },
            { grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '두 번째 수업', teacher: '이교사', isChanged: false },
            { grade: 1, class: 1, date: '2026-11-09', period: 7, subject: '마지막 수업', teacher: '김교사', isChanged: false },
          ],
        } });
        return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
      });
      await page.goto('/');
      const panel = page.locator('#timetable-panel');
      const table = panel.getByRole('table');
      await expect(table.getByText('아주 긴 과목 이름 하나')).toBeVisible();
      await expect(table.getByText('두 번째 수업')).toBeVisible();
      if (theme === 'dark') await expect(page.locator('.app-shell')).toHaveClass(/dark/);
      else await expect(page.locator('.app-shell')).not.toHaveClass(/dark/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport.width);
      if (process.env.ST04_CAPTURE === '1') {
        await page.screenshot({ path: testInfo.outputPath('timetable.png'), fullPage: true, animations: 'disabled' });
      }
      const last = table.getByText('마지막 수업');
      await last.scrollIntoViewIfNeeded();
      const box = await last.boundingBox();
      const menu = await page.getByRole('navigation', { name: '캘린더 메뉴' }).boundingBox();
      if (viewport.width <= 700) expect(box.y + box.height).toBeLessThanOrEqual(menu.y + 1);
      if (viewport.width <= 700) {
        const editSchool = page.getByRole('button', { name: '학교/학년 변경' });
        await expect(editSchool).toHaveAttribute('aria-expanded', 'false');
        await editSchool.click();
        await expect(page.getByRole('button', { name: '변경 닫기' })).toHaveAttribute('aria-expanded', 'true');
        for (const control of ['#school', '#grade', '#classroom']) {
          const element = page.locator('#school-settings').locator(control);
          await expect(element).toBeVisible();
          expect((await element.boundingBox()).height).toBeGreaterThanOrEqual(44);
        }
        await page.getByRole('searchbox', { name: '학교 찾기' }).focus();
        await expect(page.getByRole('navigation', { name: '캘린더 메뉴', includeHidden: true })).toBeHidden();
      }
    });
  }
}

for (const theme of ['light', 'dark']) {
  test(`mobile settings and meals remain usable in ${theme} mode`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
    await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
    await page.addInitScript(({ school, theme }) => {
      localStorage.setItem('opensigan-school', JSON.stringify(school));
      localStorage.setItem('opensigan-theme', theme);
    }, { school, theme });
    await page.route('**/api/v1/**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
        schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z',
        sourceUpdatedAt: null, stale: false, records: [{ grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '수학', teacher: null, isChanged: false }],
      } });
      if (url.pathname === '/api/v1/neis/schools') return route.fulfill({ json: { schools: [{ id: 'B10:1234567', name: school.name, region: '서울', address: '서울특별시' }], stale: false } });
      if (url.pathname === '/api/v1/meals') return route.fulfill({ json: { meals: [{ date: '2026-11-09', type: '중식', dishes: ['계란말이(1.2)'] }], stale: false } });
      return route.fulfill({ json: { schools: [], changes: [], stale: false } });
    });
    await page.goto('/');
    await page.getByRole('button', { name: '설정', exact: true }).click();
    const search = page.getByLabel('설정 검색');
    await search.focus();
    await expect(search).toBeFocused();
    expect(await search.evaluate((element) => getComputedStyle(element).fontSize)).toBe('16px');
    if (theme === 'dark') await expect(page.locator('.app-shell')).toHaveClass(/dark/);
    else await expect(page.locator('.app-shell')).not.toHaveClass(/dark/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
    await search.blur();
    await page.getByRole('button', { name: '급식', exact: true }).click();
    await expect(page.getByText('계란말이(1.2)')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
  });
}

for (const density of ['compact', 'relaxed']) {
  test(`mobile ${density} timetable retains its density rules`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 700 });
    const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };
    await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
    await page.addInitScript(({ school, density }) => {
      localStorage.setItem('opensigan-school', JSON.stringify(school));
      localStorage.setItem('opensigan-display:' + school.id, JSON.stringify({ density }));
    }, { school, density });
    await page.route('**/api/v1/**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
        schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z', sourceUpdatedAt: null, stale: false,
        records: [{ grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '수학', teacher: '김교사', isChanged: false }],
      } });
      return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
    });
    await page.goto('/');
    const cell = page.locator('.timetable .class-cell').first();
    await expect(cell).toBeVisible();
    if (density === 'compact') expect(await cell.locator('strong').evaluate((element) => getComputedStyle(element).fontSize)).toBe('11px');
    else expect(await cell.evaluate((element) => getComputedStyle(element).rowGap)).toBe('8px');
  });
}
