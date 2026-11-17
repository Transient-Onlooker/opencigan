import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';

test('playground sends timetable filters and timed calendar parameters safely', async ({ page }) => {
  const requests = [];
  await page.route('https://api.example.test/api/v1/**', async (route) => {
    requests.push(new URL(route.request().url()));
    await route.fulfill({ status: 200, headers: { 'Access-Control-Allow-Origin': '*' },
      body: requests.at(-1).pathname.endsWith('.ics') ? 'BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n' : '{"records":[]}' });
  });
  await page.goto('/api-docs.html');
  await page.getByLabel('API server origin (optional)').fill('https://api.example.test');
  const timetable = page.locator('[data-path="/api/v1/timetable"]');
  await timetable.getByLabel('Grade (optional)').fill('2');
  await timetable.getByLabel('Class (optional)').fill('11');
  await timetable.getByLabel('Teacher contains (optional)').fill('김');
  await timetable.getByRole('button', { name: 'Try request' }).click();
  await expect(timetable.locator('.result')).toContainText('"records": []');
  expect(requests[0].searchParams.get('teacher')).toBe('김');
  expect(requests[0].searchParams.get('class')).toBe('11');
  const calendar = page.locator('[data-path="/api/v1/timetable.ics"]');
  await calendar.getByLabel('Mode', { exact: true }).fill('timed');
  await calendar.getByLabel('Times for timed mode (optional)').fill('1:0900-0950');
  await calendar.getByRole('button', { name: 'Try request' }).click();
  await expect(calendar.locator('.result')).toContainText('BEGIN:VCALENDAR');
  expect(requests[1].searchParams.get('times')).toBe('1:0900-0950');
  await page.getByLabel('API server origin (optional)').fill('https://user:secret@api.example.test');
  await timetable.getByRole('button', { name: 'Try request' }).click();
  await expect(timetable.locator('.result')).toContainText('Enter a valid API server origin');
  expect(requests).toHaveLength(2);
});

test('Cloudflare custom domain uses same-origin API without an explicit origin', async ({ page }) => {
  const hostname = 'opencigan.mcv.kr';
  const requestUrls = [];

  await page.route(`https://${hostname}/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api-docs.html') {
      return route.fulfill({
        status: 200,
        contentType: 'text/html; charset=utf-8',
        body: readFileSync(new URL('../public/api-docs.html', import.meta.url), 'utf8'),
      });
    }
    if (url.pathname === '/api/v1/status') {
      requestUrls.push(url.toString());
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: '{"status":"ok","scope":"process liveness"}',
      });
    }
    return route.fulfill({ status: 200, body: '' });
  });

  await page.goto(`https://${hostname}/api-docs.html`);
  await expect(page.getByLabel('API server origin (optional)')).toHaveValue('');
  const statusEndpoint = page.locator('[data-path="/api/v1/status"]');
  await statusEndpoint.getByRole('button', { name: 'Try request' }).click();
  await expect(statusEndpoint.locator('.result')).toContainText('HTTP 200');
  expect(requestUrls).toEqual([`https://${hostname}/api/v1/status`]);
});
