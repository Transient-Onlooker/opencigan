import { expect, test } from '@playwright/test';

const id = 'a'.repeat(24);
const token = 'b'.repeat(43);

async function mockSubscription(page, enabled, calls) {
  await page.route('**/api/v1/webhooks/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith('/schedule')) {
      calls.push({ method: request.method(), body: request.postDataJSON(), authorization: request.headers().authorization });
      if (!enabled) return route.fulfill({ status: 503, json: { code: 'scheduler_disabled' } });
      if (request.method() === 'GET') return route.fulfill({ json: { schedule: null } });
      if (request.method() === 'PUT') return route.fulfill({ json: { schedule: request.postDataJSON() } });
      return route.fulfill({ json: { deleted: true } });
    }
    if (path.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [] } });
    if (path.endsWith('/template')) return route.fulfill({ status: 503 });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });
  await page.goto(`/webhooks.html#id=${id}&token=${token}`);
  await expect(page.locator('#manage')).toBeVisible();
}

test('disabled scheduler does not expose a nonworking form', async ({ page }) => {
  const calls = [];
  await mockSubscription(page, false, calls);
  await expect(page.locator('#schedule-editor')).toBeHidden();
  await expect(page.getByRole('button', { name: '조건 저장' })).toBeVisible();
});

test('schedule can be saved and canceled with the management token', async ({ page }) => {
  const calls = [];
  await mockSubscription(page, true, calls);
  await page.getByLabel('알림 방식').selectOption('subject_prep');
  await page.getByLabel('예약 시각').fill('07:20');
  await page.getByLabel('준비할 과목').fill('체육');
  await page.getByRole('button', { name: '일정 저장' }).click();
  await expect(page.locator('#state')).toContainText('저장');
  expect(calls.find(call => call.method === 'PUT')).toEqual({
    method: 'PUT', body: { mode: 'subject_prep', time: '07:20', subject: '체육' }, authorization: `Bearer ${token}`,
  });
  await page.getByRole('button', { name: '일정 사용 안 함' }).click();
  await expect(page.locator('#state')).toContainText('껐어요');
  expect(calls.some(call => call.method === 'DELETE' && call.authorization === `Bearer ${token}`)).toBeTruthy();
  await expect(page.getByLabel('예약 시각')).toBeHidden();
});

test('late schedule response is not shown after changing subscriptions', async ({ page }) => {
  let release, started;
  const waiting = new Promise(resolve => { release = resolve; });
  const requested = new Promise(resolve => { started = resolve; });
  await page.route('**/api/v1/webhooks/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/schedule')) {
      started();
      await waiting;
      return route.fulfill({ json: { schedule: { mode: 'daily_summary', time: '07:30', subject: null } } });
    }
    if (path.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [] } });
    if (path.endsWith('/template')) return route.fulfill({ status: 503 });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });
  await page.goto(`/webhooks.html#id=${id}&token=${token}`);
  await requested;
  await expect(page.locator('#manage')).toBeVisible();
  await page.getByLabel('구독 ID').fill('c'.repeat(24));
  const response = page.waitForResponse(result => result.url().endsWith('/schedule'));
  release();
  await response;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator('#schedule-editor')).toBeHidden();
});
