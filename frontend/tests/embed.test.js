import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import vm from 'node:vm';

function loadModule(relPath) {
  const code = readFileSync(new URL(relPath, import.meta.url), 'utf8');
  const clean = code
    .replace(/^import\s+['"][^'"]+\.css['"];?/gm, '')
    .replace(/^import\s+.*\s+from\s+['"][^'"]+['"];?/gm, (m) => {
      if (m.includes('timetable-slots') || m.includes('date') || m.includes('api')) return '// ' + m;
      return m;
    });
  const js = ts.transpile(clean, { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 });
  const context = {
    exports: {},
    require: () => ({}),
    URL,
    URLSearchParams,
    currentKoreaDate: () => '2026-11-16',
    monday: () => '2026-11-16',
    addDays: (d, n) => {
      const date = new Date(d + 'T00:00:00Z');
      date.setUTCDate(date.getUTCDate() + n);
      return date.toISOString().slice(0, 10);
    },
    slotLessons: (records, date, p, c) => records.filter(r => r.date === date && Number(r.period) === p && (c === undefined || Number(r.class) === c))
  };
  vm.runInNewContext(js, context);
  return context.exports;
}

const embed = loadModule('../src/embed.ts');
const builder = loadModule('../src/embed-builder.ts');

test('parseEmbedFragment parses valid fragments and default values', () => {
  const good = '#school=123%3ASchool&grade=2&class=5&week=next&theme=dark';
  const parsed = embed.parseEmbedFragment(good);
  assert.notEqual(parsed, null);
  assert.equal(parsed.school, '123:School');
  assert.equal(parsed.name, 'School');
  assert.equal(parsed.grade, 2);
  assert.equal(parsed.classroom, 5);
  assert.equal(parsed.weekOffset, 1);
  assert.equal(parsed.theme, 'dark');
});

test('parseEmbedFragment rejects duplicate parameters (both required and optional)', () => {
  const base = 'school=123%3ASchool&grade=2&class=5';
  assert.equal(embed.parseEmbedFragment('#' + base + '&grade=3'), null);
  assert.equal(embed.parseEmbedFragment('#' + base + '&class=6'), null);
  assert.equal(embed.parseEmbedFragment('#' + base + '&school=123%3AOther'), null);
  assert.equal(embed.parseEmbedFragment('#' + base + '&week=current&week=next'), null);
  assert.equal(embed.parseEmbedFragment('#' + base + '&theme=dark&theme=light'), null);
  assert.equal(embed.parseEmbedFragment('#' + base + '&name=A&name=B'), null);
  assert.equal(embed.parseEmbedFragment('#' + base + '&region=R1&region=R2'), null);
});

test('parseEmbedFragment rejects malformed and out-of-range parameters', () => {
  assert.equal(embed.parseEmbedFragment(''), null);
  assert.equal(embed.parseEmbedFragment('#'), null);
  assert.equal(embed.parseEmbedFragment('#school=badformat&grade=2&class=1'), null);
  assert.equal(embed.parseEmbedFragment('#school=123:School&grade=0&class=1'), null);
  assert.equal(embed.parseEmbedFragment('#school=123:School&grade=7&class=1'), null);
  assert.equal(embed.parseEmbedFragment('#school=123:School&grade=2&class=0'), null);
  assert.equal(embed.parseEmbedFragment('#school=123:School&grade=2&class=100'), null);
  assert.equal(embed.parseEmbedFragment('#school=123:School&grade=2&class=1&week=yesterday'), null);
  assert.equal(embed.parseEmbedFragment('#school=123:School&grade=2&class=1&theme=blue'), null);
  assert.equal(embed.parseEmbedFragment('x'.repeat(4097)), null);
});

test('filterClassRecords strictly filters by both grade and class to prevent cross-grade leakage', () => {
  const records = [
    { grade: 1, class: 2, period: 1, date: '2026-11-16', subject: '1학년2반수학', teacher: null, isChanged: false },
    { grade: 2, class: 2, period: 1, date: '2026-11-16', subject: '2학년2반국어', teacher: null, isChanged: false },
    { grade: 3, class: 2, period: 1, date: '2026-11-16', subject: '3학년2반영어', teacher: null, isChanged: false },
    { grade: 2, class: 1, period: 1, date: '2026-11-16', subject: '2학년1반과학', teacher: null, isChanged: false }
  ];
  const filtered = embed.filterClassRecords(records, 2, 2);
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].subject, '2학년2반국어');

  const empty = embed.filterClassRecords(records, 2, 5);
  assert.equal(empty.length, 0);
});

test('builder sanitizeDimension allows valid px, % and numbers while falling back on invalid inputs', () => {
  assert.equal(builder.sanitizeDimension('100%', '300px'), '100%');
  assert.equal(builder.sanitizeDimension('50%', '300px'), '50%');
  assert.equal(builder.sanitizeDimension('400px', '300px'), '400px');
  assert.equal(builder.sanitizeDimension('380', '300px'), '380px');
  assert.equal(builder.sanitizeDimension('javascript:alert(1)', '300px'), '300px');
  assert.equal(builder.sanitizeDimension('100%" onclick="alert(1)', '300px'), '300px');
  assert.equal(builder.sanitizeDimension('-50px', '300px'), '300px');
  assert.equal(builder.sanitizeDimension('', '100%'), '100%');
});

test('builder escapeHtml escapes dangerous characters including quotes and brackets', () => {
  const escaped = builder.escapeHtml('<script>alert("xss" & \'test\')</script>');
  assert.equal(escaped, '&lt;script&gt;alert(&quot;xss&quot; &amp; &#39;test&#39;)&lt;/script&gt;');
});

test('builder buildIframeSnippet creates valid escaped iframe HTML', () => {
  const url = 'https://example.com/embed.html#school=1%3ASchool&grade=1&class=1';
  const title = '학교 & "시간표" <위젯>';
  const snippet = builder.buildIframeSnippet(url, title, '100%', '400');
  assert.ok(snippet.startsWith('<iframe '));
  assert.ok(snippet.includes('width="100%"'));
  assert.ok(snippet.includes('height="400px"'));
  assert.ok(snippet.includes('loading="lazy"'));
  assert.ok(snippet.includes('title="학교 &amp; &quot;시간표&quot; &lt;위젯&gt;"'));
  assert.ok(!snippet.includes('<script>'));
});

test('builder extractAvailableClasses correctly returns sorted distinct class numbers', () => {
  const records = [
    { grade: 1, class: 3, period: 1, date: '2026-11-16', subject: 'A' },
    { grade: 1, class: 1, period: 1, date: '2026-11-16', subject: 'B' },
    { grade: 1, class: 3, period: 2, date: '2026-11-16', subject: 'C' },
    { grade: 2, class: 2, period: 1, date: '2026-11-16', subject: 'D' }
  ];
  const classes = builder.extractAvailableClasses(records, 1);
  assert.deepEqual(Array.from(classes), [1, 3]);
});
