import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

class Element {
  constructor(name) {
    this.name = name;
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.textContent = '';
  }
  append(...elements) { this.children.push(...elements); }
  setAttribute(name, value) { this.attributes[name] = value; }
  get className() { return this.attributes.class ?? ''; }
  set className(value) { this.attributes.class = value; }
}

async function chartApi() {
  const source = await readFile(new URL('../src/admin-charts.ts', import.meta.url), 'utf8');
  const context = {
    exports: {},
    document: { createElement: (name) => new Element(name), createElementNS: (_namespace, name) => new Element(name) },
    Intl, Date, Math, Number, String, Object,
  };
  runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), context);
  return { create: context.exports.createAnalyticsCharts, doc: context.document };
}

function descendants(element, name, output = []) {
  if (element.name === name) output.push(element);
  for (const child of element.children) descendants(child, name, output);
  return output;
}

test('builds labelled, colored SVG charts with Korea-local date and hour labels', async () => {
  const { create, doc } = await chartApi();
  const charts = create({
    daily: [{ day: '2026-11-18', visitors: 4, sessions: 3, page_views: 8, api_requests: 2 }],
    apiHourly: [{ hour: '2026-11-18T11:00:00+09:00', requests: 2, errors: 1, upstream_errors: 1, overload_errors: 0 }],
    routes: [{ route: '/api/v1/<img>', requests: 2, errors: 0 }],
  }, doc);

  assert.equal(charts.length, 7);
  const svgs = charts.map((chart) => descendants(chart, 'svg')[0]);
  assert.equal(svgs.length, 7);
  assert.ok(svgs.every((svg) => svg.attributes.role === 'img'));
  assert.match(svgs[0].attributes['aria-label'], /일별 이용/);
  assert.ok(descendants(svgs[0], 'rect').some((bar) => bar.attributes.fill === '#2563eb'));
  assert.match(descendants(svgs[0], 'text').map((node) => node.textContent).join(' '), /11\. 18\./);
  assert.match(descendants(svgs[1], 'text').map((node) => node.textContent).join(' '), /11\. 18\..*11시/);
  assert.equal(descendants(svgs[4], 'text').some((node) => node.textContent === '/api/v1/<img>'), true);
  assert.equal(descendants(svgs[4], 'rect').length, 1);
  assert.equal(descendants(svgs[4], 'circle').length, 1);
});

test('cache percentages use only responses with recorded cache status', async () => {
  const { create, doc } = await chartApi();
  const charts = create({ routes: [{ route: '/recorded', requests: 20, errors: 0, cache_observed: 10, cache_hits: 6, cache_misses: 3, stale_responses: 1 }, { route: '/missing', requests: 4, errors: 0 }] }, doc);
  const text = descendants(charts[2], 'text').map((node) => node.textContent);
  assert.ok(text.includes('60'));
  assert.ok(text.includes('30'));
  assert.ok(text.includes('10'));
  assert.ok(text.some((value) => value.includes('자료 없음')));
});

test('shows missing values separately from zero and handles empty/zero denominators safely', async () => {
  const { create, doc } = await chartApi();
  const [hourly, , , routes] = create({
    apiHourly: [{ hour: '2026-11-18T11:00:00+09:00', requests: 0, errors: null }],
    routes: [{ route: '/empty', requests: 0, errors: 0 }],
  }, doc);
  const hourlySvg = descendants(hourly, 'svg')[0];
  const routesSvg = descendants(routes, 'svg')[0];

  assert.ok(descendants(hourlySvg, 'circle').length >= 1, 'zero has a visible baseline marker');
  assert.ok(descendants(hourlySvg, 'text').some((node) => node.textContent === '오류: 자료 없음'));
  assert.ok(descendants(routesSvg, 'circle').length >= 1);
  assert.ok(descendants(routesSvg, 'rect').length === 0, 'zero denominator does not create invalid-width bars');
  assert.ok(descendants(routesSvg, 'text').some((node) => node.textContent === '0'));
});

test('omits a chart only when its response field is absent and renders present empty arrays safely', async () => {
  const { create, doc } = await chartApi();
  assert.equal(create({ daily: [] }, doc).length, 1);
  assert.equal(create({}, doc).length, 0);
  assert.doesNotThrow(() => create({ daily: [], apiHourly: [], routes: [] }, doc));
});
