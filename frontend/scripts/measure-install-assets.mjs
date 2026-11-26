import { chromium } from '@playwright/test';

const target = new URL(process.argv[2] || 'http://127.0.0.1:4174/');
if (target.protocol !== 'http:' || target.hostname !== '127.0.0.1' || target.username || target.password) {
  throw new Error('Use an isolated loopback HTTP preview URL');
}

const browser = await chromium.launch({ headless: true });
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  try {
    const pending = [];
    const requests = [];
    context.on('requestfinished', request => {
      const url = new URL(request.url());
      if (url.origin !== target.origin || !url.pathname.startsWith('/assets/')) return;
      pending.push(request.sizes().then(sizes => requests.push({ path: url.pathname, bytes: sizes.responseBodySize, worker: !!request.serviceWorker() })));
    });
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.origin !== target.origin || url.pathname.startsWith('/api/') ? route.abort() : route.continue();
    });
    const page = await context.newPage();
    await page.goto(target.href, { waitUntil: 'networkidle' });
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.waitForTimeout(250);
    await Promise.all(pending);
    const totals = {};
    for (const { path, bytes } of requests) {
      const kind = path.match(/\.(js|css|woff2)$/)?.[1];
      if (kind) totals[kind] = (totals[kind] || 0) + bytes;
    }
    console.log(JSON.stringify({ totals, workerRequests: requests.filter(request => request.worker).length }));
  } finally {
    await context.close();
  }
} finally {
  await browser.close();
}
