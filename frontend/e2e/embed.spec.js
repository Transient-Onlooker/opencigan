import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const school = {
  id: '2:임베드고등학교',
  name: '<img src=x onerror=alert(1)> " & 학교',
  region: '<svg onload=alert(2)> & 지역',
};
const week = '2026-11-16';
const maliciousSubject = '<script>window.embedXss=1</script> & " 과목';
const records = [
  { grade: 2, class: 3, date: week, period: 1, subject: maliciousSubject, teacher: null, isChanged: false },
  { grade: 2, class: 3, date: week, period: 1, subject: '같은 교시 추가 수업', teacher: '교사', isChanged: true },
  { grade: 2, class: 3, date: week, period: 12, subject: '12교시 수업', teacher: null, isChanged: false },
  { grade: 2, class: 3, date: week, period: 20, subject: '20교시 수업', teacher: null, isChanged: false },
  { grade: 2, class: 3, date: week, period: 21, subject: '표시하지 않을 21교시', teacher: null, isChanged: false },
  { grade: 1, class: 3, date: week, period: 1, subject: '다른 학년 과목', teacher: null, isChanged: false },
  { grade: 2, class: 1, date: week, period: 1, subject: '다른 반 과목', teacher: null, isChanged: false },
  { grade: 1, class: 1, date: week, period: 1, subject: '다른 학년 다른 반', teacher: null, isChanged: false },
];

async function mockApi(page, timetableRecords = records) {
  await page.clock.setFixedTime(new Date(`${week}T03:00:00Z`));
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/schools') {
      return route.fulfill({ json: { schools: [school], stale: false } });
    }
    if (url.pathname === '/api/v1/timetable') {
      return route.fulfill({ json: {
        schoolId: school.id,
        weekStart: url.searchParams.get('week'),
        records: timetableRecords,
        sourceUpdatedAt: null,
        fetchedAt: `${week}T03:00:00Z`,
        stale: false,
      } });
    }
    return route.fulfill({ status: 404, json: { error: 'unexpected mocked API request' } });
  });
}

test('embed filters by grade and class and renders school and subject text safely', async ({ page }) => {
  await mockApi(page);
  const fragment = new URLSearchParams({
    school: school.id,
    name: school.name,
    region: school.region,
    grade: '2',
    class: '3',
  });
  await page.goto(`/embed.html#${fragment}`);

  await expect(page.locator('#widget-title')).toContainText(school.name);
  await expect(page.locator('#widget-table-wrap')).toBeVisible();
  await expect(page.locator('#widget-table-body .lesson-subject')).toHaveText([
    maliciousSubject,
    '같은 교시 추가 수업',
    '12교시 수업',
    '20교시 수업',
  ]);
  await expect(page.locator('#widget-table-body tr')).toHaveCount(20);
  await expect(page.locator('#widget-table-body')).not.toContainText('다른 학년 과목');
  await expect(page.locator('#widget-table-body')).not.toContainText('다른 반 과목');
  await expect(page.locator('#widget-table-body')).not.toContainText('다른 학년 다른 반');
  await expect(page.locator('#widget-root img, #widget-root svg, #widget-root script')).toHaveCount(0);
  expect(await page.evaluate(() => window.embedXss)).toBeUndefined();

  const originalLink = new URL(await page.locator('#widget-link').getAttribute('href'));
  const originalParams = new URLSearchParams(originalLink.hash.slice(1));
  expect(originalParams.get('school')).toBe(school.id);
  expect(originalParams.get('name')).toBe(school.name);
  expect(originalParams.get('region')).toBe(school.region);
});

test('embed rejects malformed fragments without requesting timetable data', async ({ page }) => {
  let timetableRequests = 0;
  await page.route('**/api/v1/timetable**', async (route) => {
    timetableRequests++;
    return route.fulfill({ json: { records: [], stale: false } });
  });
  await page.goto('/embed.html#school=invalid&grade=2&class=3');

  await expect(page.locator('#widget-message')).toHaveClass(/status-error/);
  await expect(page.locator('#widget-table-wrap')).toBeHidden();
  expect(timetableRequests).toBe(0);
});

test('builder generates a dimensioned iframe and URL for the selected school grade and class', async ({ page }) => {
  await mockApi(page);
  await page.goto('/embed-builder.html');
  await page.locator('#school-search-input').fill('학교');
  await expect(page.locator('#school-search-results .builder-search-item')).toHaveCount(1);
  const schoolResult = page.locator('#school-search-results .builder-search-item-button');
  await schoolResult.focus();
  await schoolResult.press('Enter');
  await expect(page.locator('#class-select')).toBeEnabled();

  await page.locator('#grade-select').selectOption('2');
  await page.locator('#class-select').selectOption('3');
  await page.locator('#week-select').selectOption('next');
  await page.locator('#theme-select').selectOption('dark');
  await page.locator('#width-input').fill('640');
  await page.locator('#height-input').fill('480');

  const snippet = await page.locator('#code-output').inputValue();
  expect(snippet).toContain('width="640px"');
  expect(snippet).toContain('height="480px"');
  expect(snippet).toContain('title="&lt;img src=x onerror=alert(1)&gt; &quot; &amp; 학교 2');
  expect(snippet).not.toContain('<img');

  const src = snippet.match(/src="([^"]+)"/)?.[1];
  expect(src).toBeTruthy();
  const generated = new URL(src.replaceAll('&amp;', '&'));
  expect(generated.pathname).toBe('/embed.html');
  expect(generated.search).toBe('');
  expect(generated.hash).toContain('school=' + encodeURIComponent(school.id));
  const params = new URLSearchParams(generated.hash.slice(1));
  expect(params.get('school')).toBe(school.id);
  expect(params.get('name')).toBe(school.name);
  expect(params.get('region')).toBe(school.region);
  expect(params.get('grade')).toBe('2');
  expect(params.get('class')).toBe('3');
  expect(params.get('week')).toBe('next');
  expect(params.get('theme')).toBe('dark');
  await expect(page.locator('#preview-iframe')).toHaveAttribute('src', generated.href);
});

test('builder disables grade and class when the selected school has no timetable records', async ({ page }) => {
  await mockApi(page, []);
  await page.goto('/embed-builder.html');
  await page.locator('#school-search-input').fill('학교');
  await page.locator('#school-search-results .builder-search-item-button').click();

  await expect(page.locator('#grade-select')).toBeDisabled();
  await expect(page.locator('#class-select')).toBeDisabled();
  await expect(page.locator('#class-select option')).toHaveCount(1);
  await expect(page.locator('#copy-code-btn')).toBeDisabled();
  await expect(page.locator('#code-output')).not.toContainText('embed.html#');
});

test('clearing a school ignores a late timetable response', async ({ page }) => {
  let releaseResponse;
  let requestStarted;
  const started = new Promise((resolve) => { requestStarted = resolve; });
  const pendingResponse = new Promise((resolve) => { releaseResponse = resolve; });
  await page.route('**/api/v1/schools**', (route) => route.fulfill({ json: { schools: [school], stale: false } }));
  await page.route('**/api/v1/timetable**', async (route) => {
    requestStarted();
    await pendingResponse;
    await route.fulfill({ json: {
      schoolId: school.id,
      weekStart: week,
      records,
      sourceUpdatedAt: null,
      fetchedAt: `${week}T03:00:00Z`,
      stale: false,
    } }).catch(() => {});
  });
  await page.goto('/embed-builder.html');
  await page.locator('#school-search-input').fill('학교');
  await page.locator('#school-search-results .builder-search-item-button').click();
  await started;
  await page.locator('#selected-school-clear').click();
  releaseResponse();

  await expect(page.locator('#selected-school-box')).toBeHidden();
  await expect(page.locator('#grade-select')).toBeDisabled();
  await expect(page.locator('#class-select')).toBeDisabled();
  await expect(page.locator('#copy-code-btn')).toBeDisabled();
  await expect(page.locator('#code-output')).not.toContainText('embed.html#');
});
