import { expect, test } from '@playwright/test';

test('direct webhook entry returns to settings on mobile and desktop', async ({ page }) => {
  for (const width of [320, 1366]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/webhooks.html');
    const link = page.getByRole('link', { name: '설정으로 돌아가기' });
    await expect(link).toHaveAttribute('href', './?view=settings');
    expect((await link.boundingBox()).height).toBeGreaterThanOrEqual(44);
    await link.focus();
    await expect(link).toHaveCSS('outline-style', 'solid');
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\?view=settings$/);
    await expect(page.locator('#settings-panel')).toBeVisible();
    await page.reload();
    await expect(page.locator('#settings-panel')).toBeVisible();
  }
});

test('webhook page shares the app brand and supports light, dark and system themes', async ({ page }) => {
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.goto('/webhooks.html');
  for (const [preference, expected] of [['light', 'light'], ['dark', 'dark'], ['system', 'dark']]) {
    await page.evaluate((value) => localStorage.setItem('opensigan-theme', value), preference);
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', expected);
    const brand = page.getByRole('link', { name: 'Opencigan', exact: true });
    await expect(brand.locator('svg')).toBeVisible();
    await expect(brand).toHaveAttribute('href', './');
    await page.keyboard.press('Tab');
    await brand.focus();
    await expect(brand).toHaveCSS('outline-style', 'solid');
    for (const width of [320, 390, 800, 1366]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      expect((await page.getByLabel('Webhook 주소', { exact: true }).boundingBox()).height).toBeGreaterThanOrEqual(44);
    }
  }
});

test('subscription management uses bearer token and keeps secrets out of storage', async ({ page }) => {
  const id = 'a'.repeat(24), token = 'b'.repeat(43), calls = [];
  await page.route('**/api/v1/webhooks**', async (route) => {
    const request = route.request(), url = new URL(request.url());
    calls.push({ path: url.pathname, method: request.method(), headers: request.headers(), body: request.postDataJSON() });
    if (url.pathname === '/api/v1/webhooks') return route.fulfill({ json: { id, token, provider: 'discord' } });
    if (url.pathname.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [{ event_id: 'test_1', state: 'delivered', attempts: 1, last_status: 204 }] } });
    if (url.pathname.endsWith('/test')) return route.fulfill({ json: { eventId: 'test_1' } });
    if (request.method() === 'PUT') return route.fulfill({ json: { updated: true } });
    if (request.method() === 'DELETE') return route.fulfill({ json: { deleted: true } });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });
  await page.goto('/webhooks.html');
  await page.getByLabel('학교 ID').fill('2:예시학교');
  await page.getByLabel('학년', { exact: true }).fill('2');
  await page.getByLabel('반', { exact: true }).fill('3');
  await page.getByLabel('Webhook 주소', { exact: true }).fill('https://discord.com/api/webhooks/123/secret');
  await page.getByRole('button', { name: '구독 만들기' }).click();
  await expect(page.getByLabel('관리 토큰')).toHaveValue(token);
  await expect(page.getByLabel('Webhook 주소', { exact: true })).toHaveValue('');
  await expect(page.getByRole('status')).toContainText('안전한 곳');
  await page.getByRole('button', { name: '구독 불러오기' }).click();
  await expect(page.getByText('2:예시학교 · 2학년 3반')).toBeVisible();
  await page.getByLabel('과목 포함').fill('수학');
  await page.getByLabel('방해 금지 시작').fill('22:00');
  await page.getByLabel('방해 금지 종료').fill('07:00');
  await page.getByRole('button', { name: '조건 저장' }).click();
  await expect(page.getByRole('status')).toContainText('저장');
  expect(calls.find((call) => call.method === 'PUT').body.filters).toEqual({ subject: '수학', quietHours: { start: '22:00', end: '07:00' } });
  await page.getByLabel('새 Webhook 주소').fill('https://discord.com/api/webhooks/456/new_secret');
  await page.getByRole('button', { name: '전송 주소 변경' }).click();
  await expect(page.getByRole('status')).toContainText('전송 주소를 변경했어요');
  await expect(page.getByLabel('새 Webhook 주소')).toHaveValue('');
  expect(calls.find((call) => call.body?.destination?.includes('new_secret')).headers.authorization).toBe(`Bearer ${token}`);
  expect(await page.evaluate(() => JSON.stringify({ local: localStorage, session: sessionStorage, url: location.href }))).not.toContain('new_secret');
  await page.getByRole('button', { name: '테스트 알림' }).click();
  await expect(page.getByRole('status')).toContainText('대기열');
  expect(calls.filter((call) => call.path !== '/api/v1/webhooks').every((call) => call.headers.authorization === `Bearer ${token}`)).toBeTruthy();
  expect(await page.evaluate(() => JSON.stringify({ local: localStorage, session: sessionStorage, url: location.href }))).not.toContain(token);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '구독 삭제' }).click();
  await expect(page.getByLabel('관리 토큰')).toHaveValue('');
  await expect(page.getByRole('status')).toContainText('삭제');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize().width);
});

test('custom domain uses the same-origin gateway when no API base is configured', async ({ page, baseURL }) => {
  await page.route('https://opencigan.mcv.kr/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/v1/webhooks') {
      return route.fulfill({ json: { id: 'a'.repeat(24), token: 'b'.repeat(43), provider: 'discord' } });
    }
    const response = await route.fetch({ url: new URL(url.pathname + url.search, baseURL).href });
    return route.fulfill({ response });
  });
  await page.goto('https://opencigan.mcv.kr/webhooks.html');
  await page.getByLabel('학교 ID').fill('2:예시학교');
  await page.getByLabel('학년', { exact: true }).fill('2');
  await page.getByLabel('반', { exact: true }).fill('3');
  await page.getByLabel('Webhook 주소', { exact: true }).fill('https://discord.com/api/webhooks/123/secret');
  await page.getByRole('button', { name: '구독 만들기' }).click();
  await expect(page.getByLabel('관리 토큰')).toHaveValue('b'.repeat(43));
  await page.unrouteAll({ behavior: 'wait' });
});

test('management link auto-authenticates via fragment, strips fragment immediately, and copies link', async ({ page }) => {
  const id = 'a'.repeat(24), token = 'b'.repeat(43), calls = [];
  await page.route('**/api/v1/webhooks**', async (route) => {
    const request = route.request(), url = new URL(request.url());
    calls.push({ path: url.pathname, url: request.url(), method: request.method(), headers: request.headers() });
    if (url.pathname.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [] } });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });

  await page.goto('/webhooks.html#invalid-fragment');
  expect(page.url()).not.toContain('invalid-fragment');
  expect(page.url()).not.toContain('#');
  await expect(page.getByRole('status')).toContainText('관리 링크의 형식');
  expect(calls.length).toBe(0);

  await page.goto(`/webhooks.html#id=${id}&token=${token}`);
  await expect(page).toHaveURL(/\/webhooks\.html$/);
  expect(page.url()).not.toContain(token);
  expect(page.url()).not.toContain('#');
  await expect(page.getByText('2:예시학교 · 2학년 3반')).toBeVisible();
  await expect(page.getByRole('status')).toContainText('구독 정보');

  expect(calls.every((call) => !call.url.includes(token) && !(call.headers.referer ?? '').includes(token))).toBeTruthy();
  expect(calls.every((call) => call.headers.authorization === `Bearer ${token}`)).toBeTruthy();
  expect(await page.evaluate(() => JSON.stringify({ local: localStorage, session: sessionStorage, url: location.href }))).not.toContain(token);

  await page.evaluate(() => {
    window._copied = '';
    const mock = { writeText: async (text) => { window._copied = text; } };
    try {
      Object.defineProperty(navigator, 'clipboard', { value: mock, configurable: true });
    } catch {
      navigator.clipboard.writeText = mock.writeText;
    }
  });
  await page.getByRole('button', { name: '관리 링크 복사' }).click();
  await expect(page.getByRole('status')).toContainText('복사');
  await expect(page.getByRole('status')).toContainText('공유하거나 북마크');
  expect(await page.evaluate(() => window._copied)).toContain(`#id=${id}&token=${token}`);
});

for (const heldStage of ['subscription', 'template']) test(`changing credentials while loading ${heldStage} does not show the previous subscription`, async ({ page }) => {
  const oldId = 'a'.repeat(24), newId = 'c'.repeat(24), token = 'b'.repeat(43);
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  let requested;
  const started = new Promise((resolve) => { requested = resolve; });
  await page.route('**/api/v1/webhooks**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if ((heldStage === 'subscription' && path.endsWith(oldId)) ||
        (heldStage === 'template' && path.endsWith(`${oldId}/template`))) { requested(); await waiting; }
    try {
      if (path.endsWith('/deliveries')) return await route.fulfill({ json: { deliveries: [] } });
      if (path.endsWith('/template')) return await route.fulfill({ json: { template: null, discordEmbed: false, provider: 'discord' } });
      if (path.endsWith('/template/preview')) return await route.fulfill({ json: { payload: { content: 'preview' } } });
      if (path.endsWith('/schedule')) return await route.fulfill({ json: { schedule: null } });
      await route.fulfill({ json: { school: path.endsWith(oldId) ? '이전 학교' : '새 학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
    } catch { /* The browser may cancel the held request. */ }
  });
  await page.goto(`/webhooks.html#id=${oldId}&token=${token}`);
  await started;
  await page.locator('#id').fill(newId);
  release();
  await expect(page.locator('#manage')).toBeHidden();
  await expect(page.getByText('이전 학교')).toHaveCount(0);
  await page.locator('#connect').evaluate((form) => form.requestSubmit());
  await expect(page.locator('#scope')).toContainText('새 학교');
  await expect(page.locator('#manage')).toBeVisible();
});

test('shows next_at in local time only for pending deliveries', async ({ page }) => {
  const nextAt = Date.UTC(2026, 10, 22, 3, 4) / 1000;
  await page.route('**/api/v1/webhooks**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [
      { event_id: 'pending', state: 'pending', attempts: 2, next_at: nextAt },
      { event_id: 'leased', state: 'leased', attempts: 3, next_at: nextAt },
      { event_id: 'delivered', state: 'delivered', attempts: 1, next_at: nextAt },
      { event_id: 'failed', state: 'failed', attempts: 4, next_at: nextAt },
    ] } });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });
  await page.goto(`/webhooks.html#id=${'a'.repeat(24)}&token=${'b'.repeat(43)}`);
  const expected = await page.evaluate((value) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value * 1000)), nextAt);
  const rows = page.locator('#deliveries tr');
  await expect(rows.nth(0).locator('time')).toHaveText(expected);
  await expect(rows.nth(0).locator('time')).toHaveAttribute('aria-label', `다음 처리 시각: ${expected}`);
  await expect(rows.nth(0).locator('time')).toHaveAttribute('datetime', new Date(nextAt * 1000).toISOString());
  for (const index of [1, 2, 3]) await expect(rows.nth(index).locator('td').nth(4)).toBeEmpty();
});

test('management link does not authenticate if the fragment cannot be removed', async ({ page }) => {
  let requests = 0;
  await page.route('**/api/v1/webhooks**', async (route) => { requests++; await route.abort(); });
  await page.addInitScript(() => { history.replaceState = () => { throw new Error('blocked'); }; });
  await page.goto(`/webhooks.html#id=${'a'.repeat(24)}&token=${'b'.repeat(43)}`);
  await expect(page.getByRole('status')).toContainText('주소에서 관리 정보를 지우지 못했어요');
  expect(requests).toBe(0);
});

test('rotation requires saving the new link before revoking the old token', async ({ page }) => {
  const id = 'a'.repeat(24), oldToken = 'b'.repeat(43), rotations = [];
  await page.route('**/api/v1/webhooks**', async (route) => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.endsWith('/rotate')) {
      rotations.push({ body: request.postDataJSON(), authorization: request.headers().authorization });
      if (rotations.length === 1) return route.abort();
      return route.fulfill({ json: rotations.length === 2 ? {} : { rotated: true } });
    }
    if (url.pathname.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [] } });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });
  await page.goto('/webhooks.html');
  await page.getByLabel('구독 ID').fill(id);
  await page.getByLabel('관리 토큰').fill(oldToken);
  await page.getByRole('button', { name: '구독 불러오기' }).click();
  await page.getByRole('button', { name: '새 관리 링크 준비' }).click();
  const link = await page.getByLabel('새 관리 링크', { exact: true }).inputValue();
  const newToken = new URLSearchParams(new URL(link).hash.slice(1)).get('token');
  expect(newToken).toMatch(/^[A-Za-z0-9_-]{43}$/);
  expect(newToken).not.toBe(oldToken);
  await page.getByRole('button', { name: '기존 링크 폐기하고 교체' }).click();
  expect(rotations).toHaveLength(0);
  await page.getByLabel('새 링크를 안전하게 보관했어요').check();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '기존 링크 폐기하고 교체' }).click();
  await expect(page.getByRole('status')).toContainText('결과를 확인하지 못했어요');
  await expect(page.getByLabel('관리 토큰')).toHaveValue(oldToken);
  await expect(page.getByLabel('새 관리 링크', { exact: true })).toHaveValue(link);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '기존 링크 폐기하고 교체' }).click();
  await expect(page.getByRole('status')).toContainText('결과를 확인하지 못했어요');
  await expect(page.getByLabel('새 관리 링크', { exact: true })).toHaveValue(link);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '기존 링크 폐기하고 교체' }).click();
  await expect(page.getByRole('status')).toContainText('교체했어요');
  expect(rotations).toEqual(Array(3).fill({ body: { newToken }, authorization: `Bearer ${oldToken}` }));
  await expect(page.getByLabel('관리 토큰')).toHaveValue(newToken);
  expect(await page.evaluate(() => JSON.stringify({ local: localStorage, session: sessionStorage, url: location.href }))).not.toContain(newToken);
});

test('rotation does not replace credentials edited while the request is in flight', async ({ page }) => {
  let release;
  const pending = new Promise((resolve) => { release = resolve; });
  let started;
  const requestStarted = new Promise((resolve) => { started = resolve; });
  await page.route('**/api/v1/webhooks**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/rotate')) { started(); await pending; return route.fulfill({ json: { rotated: true } }); }
    if (path.endsWith('/deliveries')) return route.fulfill({ json: { deliveries: [] } });
    return route.fulfill({ json: { school: '2:예시학교', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
  });
  await page.goto('/webhooks.html');
  await page.getByLabel('구독 ID').fill('a'.repeat(24));
  await page.getByLabel('관리 토큰').fill('b'.repeat(43));
  await page.getByRole('button', { name: '구독 불러오기' }).click();
  await page.getByRole('button', { name: '새 관리 링크 준비' }).click();
  await page.getByLabel('새 링크를 안전하게 보관했어요').check();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '기존 링크 폐기하고 교체' }).click();
  await requestStarted;
  await page.getByLabel('구독 ID').fill('c'.repeat(24));
  release();
  await expect(page.getByRole('status')).toContainText('진행 중이던 변경 요청은 처리 여부를 다시 확인');
  await expect(page.getByLabel('구독 ID')).toHaveValue('c'.repeat(24));
  await expect(page.getByLabel('관리 토큰')).toHaveValue('b'.repeat(43));
});
