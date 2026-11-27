import { expect, test } from '@playwright/test';

const school = { id: '2:봄빛고등학교', name: '봄빛고등학교', region: '서울' };

for (const width of [320, 960]) {
  for (const theme of ['light', 'dark']) {
    test(`widget link uses the action style at ${width}px in ${theme} mode`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 });
      await page.addInitScript(({ school, theme }) => {
        localStorage.setItem('opensigan-school', JSON.stringify(school));
        localStorage.setItem('opensigan-theme', theme);
      }, { school, theme });
      await page.route('**/api/v1/**', async (route) => {
        const url = new URL(route.request().url());
        if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
          schoolId: school.id, weekStart: url.searchParams.get('week'), records: [], stale: false,
        } });
        return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
      });
      await page.goto('/');
      await page.getByRole('button', { name: '시간표', exact: true }).click();
      const link = page.locator('.secondary-actions').getByRole('link', { name: '시간표 위젯 만들기' });
      await expect(link).toHaveAttribute('href', './embed-builder.html');
      await expect(link).toBeVisible();
      const styles = await link.evaluate((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return { color: style.color, decoration: style.textDecorationLine, left: rect.left, right: rect.right, height: rect.height };
      });
      expect(styles.color).toBe(await link.evaluate((element) => {
        const probe = document.createElement('span');
        probe.style.color = 'var(--ink)';
        element.append(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color;
      }));
      expect(styles.decoration).toBe('none');
      expect(styles.left).toBeGreaterThanOrEqual(0);
      expect(styles.right).toBeLessThanOrEqual(width);
      expect(styles.height).toBeGreaterThanOrEqual(44);
      await page.keyboard.press('Tab');
      await link.focus();
      await expect(link).toBeFocused();
      expect(await link.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe('none');
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.keyboard.press('Enter');
      await expect(page).toHaveURL(/\/embed-builder\.html$/);
      await page.goBack();
      await expect(page.locator('.secondary-actions').getByRole('link', { name: '시간표 위젯 만들기' })).toHaveCSS('color', styles.color);
    });
  }
}

test('today lessons fit above mobile navigation', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 600 });
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z',
      sourceUpdatedAt: null, stale: false,
      records: [1, 2, 3, 4, 5, 6, 7].map((period) => ({ grade: 1, class: 1, date: '2026-11-09', period, subject: `긴 수업 이름 ${period}`, teacher: '김교사', isChanged: false })),
    } });
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/');
  const panel = page.locator('#timetable-panel');
  await panel.getByRole('button', { name: '오늘', exact: true }).click();
  const lastLesson = panel.getByLabel('선택한 날짜 시간표').getByText('긴 수업 이름 7', { exact: true });
  await expect(lastLesson).toBeVisible();
  await lastLesson.scrollIntoViewIfNeeded();
  const lastBox = await lastLesson.boundingBox();
  const menuBox = await page.getByRole('navigation', { name: '캘린더 메뉴' }).boundingBox();
  expect(lastBox.y + lastBox.height).toBeLessThanOrEqual(menuBox.y);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test('meal source link remains accessible above mobile navigation', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 600 });
  await page.clock.setFixedTime(new Date('2026-11-09T02:00:00Z'));
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/neis/schools') return route.fulfill({ json: { schools: [{ id: 'B10:1234567', name: school.name, region: '서울', address: '서울' }] } });
    if (url.pathname === '/api/v1/meals') return route.fulfill({ json: { meals: [{ date: '2026-11-09', type: '중식', dishes: ['밥'] }], stale: false } });
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: { schoolId: school.id, weekStart: url.searchParams.get('week'), records: [], stale: false } });
    return route.fulfill({ json: { schools: [], meals: [], changes: [] } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '급식', exact: true }).click();
  const source = page.getByRole('link', { name: '나이스 교육정보 개방 포털' });
  await expect(source).toBeVisible();
  await source.evaluate((element) => element.scrollIntoView({ block: 'end', behavior: 'instant' }));
  const linkBox = await source.boundingBox();
  const navBox = await page.getByRole('navigation', { name: '캘린더 메뉴' }).boundingBox();
  expect(linkBox.y + linkBox.height).toBeLessThanOrEqual(navBox.y);
  await source.focus();
  await expect(source).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(320);
});

test('settings last allergy control stays above the fixed nav at 667x320', async ({ page }) => {
  await page.setViewportSize({ width: 667, height: 320 });
  await page.addInitScript((value) => localStorage.setItem('opensigan-school', JSON.stringify(value)), school);
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/timetable') return route.fulfill({ json: {
      schoolId: school.id, weekStart: url.searchParams.get('week'), fetchedAt: '2026-11-09T01:00:00Z',
      sourceUpdatedAt: null, stale: false, records: [{ grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '수학', teacher: null, isChanged: false }],
    } });
    return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '설정', exact: true }).click();
  await page.locator('#settings-panel details.meal-preferences > summary').click();
  await page.locator('#settings-panel details.allergy-settings > summary').click();

  const finalControl = page.locator('#settings-panel .allergy-grid input[type="checkbox"]').last();
  await finalControl.scrollIntoViewIfNeeded();
  await expect(finalControl).toBeVisible();
  const controlBox = await finalControl.boundingBox();
  const menuBox = await page.getByRole('navigation', { name: '캘린더 메뉴' }).boundingBox();
  expect(controlBox).not.toBeNull();
  expect(menuBox).not.toBeNull();
  expect(controlBox.y + controlBox.height).toBeLessThanOrEqual(menuBox.y);
});

for (const width of [320, 390, 700, 960]) {
  for (const theme of ['light', 'dark']) {
    test(`settings and selection fit ${width}px in ${theme} mode`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
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
        return route.fulfill({ json: { schools: [], meals: [], changes: [], stale: false } });
      });
      await page.goto('/');
      await page.getByRole('button', { name: '설정', exact: true }).click();
      await page.getByText('일반 설정', { exact: true }).click();
      await page.getByLabel('테마').selectOption(theme);
      if (theme === 'dark') await expect(page.locator('.app-shell')).toHaveClass(/dark/);
      else await expect(page.locator('.app-shell')).not.toHaveClass(/dark/);
      await page.getByText('시간표 표시 설정', { exact: true }).click();
      await page.getByLabel('시간표 밀도').selectOption('relaxed');
      await page.getByLabel('종료된 수업 표시').selectOption('hide');
      const overflow = await page.evaluate(() => {
        const width = document.documentElement.clientWidth;
        return [...document.querySelectorAll('#settings-panel details[open], #settings-panel select, #settings-panel input')]
          .filter((element) => {
            const rect = element.getBoundingClientRect();
            return rect.width && (rect.left < 0 || rect.right > width + 1);
          })
          .map((element) => ({ selector: element.tagName.toLowerCase(), type: element.getAttribute('type'), label: element.getAttribute('aria-label'), parent: element.parentElement?.className, left: Math.round(element.getBoundingClientRect().left), right: Math.round(element.getBoundingClientRect().right) }));
      });
      expect(overflow, `settings overflow at ${width}px`).toEqual([]);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.getByRole('button', { name: '학교/학년 변경' }).click();
      const selectionWidth = await page.locator('#school-settings').evaluate((element) => ({ right: element.getBoundingClientRect().right, width: element.getBoundingClientRect().width }));
      expect(selectionWidth.right, `school selector overflow at ${width}px`).toBeLessThanOrEqual(width + 1);
      for (const control of ['#school', '#grade', '#classroom']) {
        const rect = await page.locator('#school-settings').locator(control).evaluate((element) => {
          const { left, right } = element.getBoundingClientRect();
          return { left, right };
        });
        expect(rect.left, `${control} left at ${width}px`).toBeGreaterThanOrEqual(-1);
        expect(rect.right, `${control} right at ${width}px`).toBeLessThanOrEqual(width + 1);
      }
    });
  }
}
