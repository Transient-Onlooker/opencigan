import { expect, test } from '@playwright/test';

test.use({ serviceWorkers: 'block' });

const id = 'a'.repeat(24);
const token = 'b'.repeat(43);
const basePath = `/api/v1/webhooks/${id}`;

test('edits, validates, previews, saves, and resets a Discord template', async ({ page }) => {
  const requests = [];
  await page.route('**/api/v1/webhooks/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({ method: request.method(), path, body: request.postData() ? request.postDataJSON() : null, authorization: request.headers().authorization });

    if (path === basePath) return route.fulfill({ json: { school: '예시고', grade: 2, classroom: 3, provider: 'discord', dropped_events: 0, filters: {} } });
    if (path === `${basePath}/deliveries`) return route.fulfill({ json: { deliveries: [] } });
    if (path === `${basePath}/template` && request.method() === 'GET') return route.fulfill({ json: { template: null, discordEmbed: false, provider: 'discord' } });
    if (path === `${basePath}/template` && request.method() === 'DELETE') return route.fulfill({ json: { reset: true } });
    if (path === `${basePath}/template` && request.method() === 'PUT') return route.fulfill({ json: { ...request.postDataJSON(), provider: 'discord' } });
    if (path === `${basePath}/template/preview`) {
      const { template, discordEmbed } = request.postDataJSON();
      const content = template.replaceAll('{school}', '예시고').replaceAll('{period}', '3');
      return route.fulfill({ json: { payload: discordEmbed ? { embeds: [{ description: content }] } : { content } } });
    }
    return route.fulfill({ status: 404, json: { error: 'unexpected request' } });
  });

  await page.goto('/webhooks.html');
  await page.getByLabel('구독 ID').fill(id);
  await page.getByLabel('관리 토큰').fill(token);
  await page.getByRole('button', { name: '구독 불러오기' }).click();
  await expect(page.locator('#manage')).toBeVisible();
  await expect(page.locator('#template-preview')).toContainText('예시고');

  const previewCount = () => requests.filter((item) => item.path.endsWith('/template/preview')).length;
  const beforeInvalid = previewCount();
  await page.getByLabel('템플릿 내용').fill('{unknown}');
  await expect(page.locator('#template-errors')).toContainText('지원하지 않는 변수');
  await expect.poll(previewCount).toBe(beforeInvalid);

  await page.getByLabel('템플릿 내용').fill('{school} {period}교시');
  await page.getByLabel('메시지 형식').selectOption('embed');
  await expect(page.locator('#template-preview')).toContainText('예시고 3교시');
  await page.getByRole('button', { name: '템플릿 저장' }).click();
  await expect(page.locator('#state')).toContainText('템플릿을 저장');
  const save = requests.find((item) => item.method === 'PUT' && item.path === `${basePath}/template`);
  expect(save.body).toEqual({ template: '{school} {period}교시', discordEmbed: true });
  expect(save.authorization).toBe(`Bearer ${token}`);

  await page.getByRole('button', { name: '초기화' }).click();
  await expect(page.locator('#template-body')).toHaveValue('{school} {grade}학년 {classroom}반 · {date} {period}교시 ({type})\n{before} → {after}');
  expect(requests.some((item) => item.method === 'DELETE' && item.path === `${basePath}/template`)).toBe(true);
  expect(requests.every((item) => !item.path.endsWith('/test'))).toBe(true);
});

test('Google Chat remains on text format and inserts available variables', async ({ page }) => {
  await page.route('**/api/v1/webhooks/**', async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === basePath) return route.fulfill({ json: { school: '예시고', grade: 2, classroom: 3, provider: 'google-chat', dropped_events: 0, filters: {} } });
    if (pathname === `${basePath}/deliveries`) return route.fulfill({ json: { deliveries: [] } });
    if (pathname === `${basePath}/template`) return route.fulfill({ json: { template: null, discordEmbed: false, provider: 'google-chat' } });
    if (pathname === `${basePath}/template/preview`) return route.fulfill({ json: { payload: { text: '예시고 2학년' } } });
    return route.fulfill({ status: 404 });
  });

  await page.goto('/webhooks.html');
  await page.getByLabel('구독 ID').fill(id);
  await page.getByLabel('관리 토큰').fill(token);
  await page.getByRole('button', { name: '구독 불러오기' }).click();
  await expect(page.getByLabel('메시지 형식')).toBeDisabled();
  await page.locator('[data-template-variable="school"]').click();
  await expect(page.locator('#template-body')).toHaveValue(/\{school\}/);
  await expect(page.locator('#template-preview')).toContainText('예시고 2학년');
});
