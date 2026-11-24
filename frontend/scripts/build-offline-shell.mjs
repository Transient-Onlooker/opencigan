import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';

const dist = new URL('../dist/', import.meta.url);
const docsUrl = new URL('api-docs.html', dist);
const docsHtml = await readFile(docsUrl, 'utf8');
const configuredApi = (process.env.VITE_API_BASE_URL || '').trim();
let apiOrigin = '';
if (configuredApi) {
  const parsed = new URL(configuredApi);
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error('VITE_API_BASE_URL must be an HTTP(S) origin');
  }
  apiOrigin = parsed.origin;
}
await writeFile(docsUrl, docsHtml.replace('content="__API_ORIGIN__"', `content="${apiOrigin.replaceAll('&', '&amp;').replaceAll('"', '&quot;')}"`));
const html = await readFile(new URL('index.html', dist), 'utf8');
const assets = [...new Set([...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((match) => match[1]))];
const manifest = JSON.parse(await readFile(new URL('.vite/manifest.json', dist), 'utf8'));
const exportChunk = manifest['src/export-png.ts'];
if (!exportChunk?.file || !exportChunk.isDynamicEntry) throw new Error('Missing timetable export chunk');
assets.push('/' + exportChunk.file);
const template = await readFile(new URL('./offline-shell.js', import.meta.url), 'utf8');
const version = createHash('sha256').update(html).update(JSON.stringify(assets)).update(template).digest('hex').slice(0, 16);
await writeFile(new URL('service-worker.js', dist), `const CACHE = 'opencigan-shell-${version}';\nconst ASSETS = ${JSON.stringify(assets)};\n${template}`);
