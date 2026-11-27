import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

class Element {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName;
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.textContent = '';
    this.value = '';
    this.hidden = false;
    this.disabled = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  dispatch(name) {
    const event = { preventDefault() {} };
    return this.listeners[name]?.(event);
  }
}

function createDocument() {
  return { createElement(tagName) { return new Element(tagName, this); } };
}

function descendants(element, predicate, result = []) {
  if (predicate(element)) result.push(element);
  for (const child of element.children) descendants(child, predicate, result);
  return result;
}

function buttonWithText(root, text) {
  return descendants(root, (element) => element.tagName === 'button' && element.textContent === text)[0];
}

async function loadModule(fetchImpl, confirm = () => true) {
  const source = await readFile(new URL('../src/admin-suggestions.ts', import.meta.url), 'utf8');
  const exports = {};
  runInNewContext(ts.transpile(source, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }), {
    exports, fetch: fetchImpl, URLSearchParams, AbortController, AbortSignal, encodeURIComponent, JSON, Error, Set,
    window: { confirm },
  });
  return exports.mountSuggestions;
}

function suggestion(overrides = {}) {
  return {
    id: 'a'.repeat(24), title: '<img src=x onerror=alert(1)>', description: '<script>unsafe()</script>',
    context: '<b>context</b>', status: 'pending', created_at: '2026-11-27T10:00:00+09:00',
    reviewed_at: null, merged_into: null, reviewer_note: null, ...overrides,
  };
}

function response(status, data) {
  return { ok: status >= 200 && status < 300, status, async json() { return data; } };
}

async function settle() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

test('loads admin suggestions safely and sends confirmed status changes with the bearer token', async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    if (options.method === 'PATCH') return response(200, {});
    return response(200, { suggestions: calls.some((call) => call.options.method === 'PATCH') ? [] : [suggestion()], nextCursor: null });
  };
  const mount = await loadModule(fetchImpl);
  const doc = createDocument();
  const container = new Element('div', doc);
  mount(container, 'admin-secret', 'https://api.example/');
  await settle();

  assert.match(calls[0].url, /^https:\/\/api\.example\/api\/v1\/admin\/suggestions\?/);
  assert.equal(calls[0].options.headers.Authorization, 'Bearer admin-secret');
  assert.equal(calls[0].options.credentials, 'omit');
  assert.equal(calls[0].options.cache, 'no-store');
  assert.equal(calls[0].options.referrerPolicy, 'no-referrer');
  const paragraphs = descendants(container, (element) => element.tagName === 'p').map((element) => element.textContent);
  assert.ok(paragraphs.includes('<script>unsafe()</script>'));
  assert.equal(descendants(container, (element) => element.tagName === 'script').length, 0);
  assert.equal(descendants(container, (element) => element.tagName === 'img').length, 0);

  buttonWithText(container, '승인').dispatch('click');
  await settle();
  const patch = calls.find((call) => call.options.method === 'PATCH');
  assert.ok(patch);
  assert.equal(patch.options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(patch.options.body), { status: 'approved', reviewer_note: null });
  assert.equal(calls.filter((call) => !call.options.method).length, 2);
});

test('paginates with the returned cursor and omits mutations when confirmation is declined', async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return response(200, { suggestions: [suggestion()], nextCursor: calls.length === 1 ? '51' : null });
  };
  const mount = await loadModule(fetchImpl, () => false);
  const doc = createDocument();
  const container = new Element('div', doc);
  mount(container, 'token', '');
  await settle();

  buttonWithText(container, '더 보기').dispatch('click');
  await settle();
  assert.match(calls[1].url, /cursor=51/);
  buttonWithText(container, '삭제').dispatch('click');
  await settle();
  assert.equal(calls.length, 2);
});

test('cleanup aborts active requests, clears rendered DOM, and prevents later rendering', async () => {
  let requestSignal;
  let resolveFetch;
  const fetchImpl = (_url, options) => {
    requestSignal = options.signal;
    return new Promise((resolve) => { resolveFetch = resolve; });
  };
  const mount = await loadModule(fetchImpl);
  const doc = createDocument();
  const container = new Element('div', doc);
  const cleanup = mount(container, 'sensitive-admin-token', '');
  await settle();
  cleanup();

  assert.equal(requestSignal.aborted, true);
  assert.deepEqual(container.children, []);
  resolveFetch(response(200, { suggestions: [suggestion()], nextCursor: null }));
  await settle();
  assert.deepEqual(container.children, []);
  cleanup();
});

test('reports authentication and malformed response failures in the status region', async () => {
  for (const [result, expected] of [
    [response(401, {}), '관리자 토큰을 확인해 주세요.'],
    [response(200, { suggestions: 'invalid', nextCursor: null }), '서버 응답 형식이 올바르지 않습니다.'],
  ]) {
    const mount = await loadModule(async () => result);
    const doc = createDocument();
    const container = new Element('div', doc);
    mount(container, 'token', '');
    await settle();
    assert.equal(descendants(container, (element) => element.attributes.role === 'status')[0].textContent, expected);
  }
});
