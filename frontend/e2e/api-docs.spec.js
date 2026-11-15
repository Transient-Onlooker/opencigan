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
