import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/export-png.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const personalizationSource = await readFile(new URL('../src/personalization.ts', import.meta.url), 'utf8');
const personalizationCompiled = ts.transpileModule(personalizationSource, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const personalization = {};
runInNewContext(personalizationCompiled, { exports: personalization });
const exports = {};
runInNewContext(compiled, { exports, require: (name) => {
  if (name === './personalization') return personalization;
  throw new Error(`Unexpected dependency: ${name}`);
} });
const { createExportGrid, buildExportFilename, wrappedText } = exports;

const lessons = [
  { grade: 1, class: 2, date: '2026-11-09', period: 1, subject: '긴 과목명', teacher: '김철수' },
  { grade: 1, class: 2, date: '2026-11-10', period: 3, subject: '수학Ⅱ', teacher: '이영희' },
  { grade: 1, class: 1, date: '2026-11-09', period: 1, subject: '과학', teacher: '김철수' },
  { grade: 1, class: 3, date: '2026-11-09', period: 1, subject: '미술', teacher: '김철수' },
];
const options = {
  view: 'week', schoolName: 'A고등학교', grade: 1, classroom: 2,
  selectedDay: '2026-11-09', week: '2026-11-09', teacherName: '', records: lessons, dark: false,
};

test('PNG layout uses the selected class and keeps empty intervening periods', () => {
  const grid = createExportGrid(options);
  assert.equal(grid.columns.length, 5);
  assert.deepEqual(Array.from(grid.periods), [1, 2, 3]);
  assert.equal(grid.rows[0][0][0].title, '긴 과목명');
  assert.equal(grid.rows[0][0].length, 1);
  assert.equal(grid.rows[1][0].length, 0);
  assert.equal(grid.rows[2][1][0].title, '수학Ⅱ');
});

test('teacher view retains all classes at the same period', () => {
  const grid = createExportGrid({ ...options, view: 'teacher', teacherName: '김철수' });
  assert.deepEqual(Array.from(grid.rows[0][0], (lesson) => lesson.title), ['1학년 2반', '1학년 1반', '1학년 3반']);
  assert.equal(grid.rows[0][1].length, 0);
  const unselected = createExportGrid({ ...options, view: 'teacher', teacherName: '김' });
  assert.equal(unselected.periods.length, 0);
});

test('today view exports only the chosen date', () => {
  const grid = createExportGrid({ ...options, view: 'today', selectedDay: '2026-11-10' });
  assert.equal(grid.columns.length, 1);
  assert.deepEqual(Array.from(grid.periods), [1, 2, 3]);
  assert.equal(grid.rows[2][0][0].title, '수학Ⅱ');
  assert.equal(grid.rows[0][0].length, 0);
});

test('PNG weekly headings respect the saved date visibility setting', () => {
  const hidden = { ...personalization.defaultDisplaySettings(), showDates: false };
  const weekly = createExportGrid({ ...options, displaySettings: hidden });
  assert.deepEqual(Array.from(weekly.columns), ['월', '화', '수', '목', '금']);
  assert.match(weekly.subtitle, /11\. 9/);
  assert.match(createExportGrid({ ...options, displaySettings: hidden, view: 'today' }).columns[0], /11\. 9/);
  assert.match(createExportGrid({ ...options }).columns[0], /11\. 9/);
});

test('export personalizes displayed labels without altering source records', () => {
  const settings = {
    ...personalization.defaultDisplaySettings(),
    colorMode: 'custom',
    subjectColors: { [lessons[0].subject]: '#ff0000' },
    subjectAliases: { [lessons[0].subject]: '짧은 과목' },
    teacherAliases: { [lessons[0].teacher]: '선생님 별칭' },
    teacherSuffix: 'T',
  };
  const grid = createExportGrid({ ...options, displaySettings: settings });
  assert.equal(grid.rows[0][0][0].title, '짧은 과목');
  assert.equal(grid.rows[0][0][0].detail, '선생님 별칭T');
  assert.equal(grid.rows[0][0][0].color, '#ff0000');
  assert.equal(lessons[0].subject, Object.keys(settings.subjectAliases)[0]);
  assert.equal(createExportGrid({ ...options, displaySettings: { ...settings, showTeachers: false } }).rows[0][0][0].detail, '');
  const teacherGrid = createExportGrid({ ...options, view: 'teacher', teacherName: lessons[0].teacher, displaySettings: settings });
  assert.match(teacherGrid.subtitle, /선생님 별칭T/);
  assert.equal(teacherGrid.rows[0][0][0].detail, '짧은 과목');
});

function shareHarness(share, canShare, fileSupported = true) {
  let downloads = 0;
  let shareCount = 0;
  const context = new Proxy({ measureText: (value) => ({ width: value.length * 10 }) }, { get: (target, key) => target[key] ?? (() => {}) });
  const sandbox = {
    exports: {},
    require: (name) => name === './personalization' ? personalization : undefined,
    Blob,
    File: fileSupported ? class { constructor(parts, name, fileOptions) { this.parts = parts; this.name = name; this.type = fileOptions.type; } } : undefined,
    navigator: {
      share: share && (async (data) => { shareCount++; await share(data); }),
      canShare: canShare && ((data) => canShare(data)),
    },
    document: {
      fonts: { ready: Promise.resolve() },
      body: { append() {} },
      createElement: (type) => type === 'canvas'
        ? { getContext: () => context, toBlob: (callback) => callback(new Blob(['png'], { type: 'image/png' })) }
        : { click: () => { downloads++; }, remove() {} },
    },
    URL: { createObjectURL: () => 'blob:local', revokeObjectURL() {} },
    window: { setTimeout() {} },
  };
  runInNewContext(compiled, sandbox);
  return { share: () => sandbox.exports.shareTimetablePng(options), getDownloads: () => downloads, getShareCount: () => shareCount };
}

test('PNG share uses the native file share sheet when supported', async () => {
  const harness = shareHarness(async (data) => {
    assert.equal(data.files.length, 1);
    assert.equal(data.files[0].type, 'image/png');
    assert.match(data.files[0].name, /^Opencigan_.*\.png$/);
  }, (data) => data.files.length === 1);
  assert.equal(await harness.share(), 'shared');
  assert.equal(harness.getShareCount(), 1);
  assert.equal(harness.getDownloads(), 0);
});

test('cancelled image share does not download a file', async () => {
  const harness = shareHarness(async () => { throw Object.assign(new Error('cancelled'), { name: 'AbortError' }); }, () => true);
  assert.equal(await harness.share(), 'cancelled');
  assert.equal(harness.getDownloads(), 0);
});

test('unsupported share and share failures fall back to PNG download', async () => {
  for (const [harness, result] of [
    [shareHarness(null, null), 'unsupported'],
    [shareHarness(async () => {}, () => false), 'unsupported'],
    [shareHarness(async () => { throw new Error('NotAllowedError'); }, () => true), 'failed'],
    [shareHarness(async () => {}, () => true, false), 'unsupported'],
  ]) {
    assert.equal(await harness.share(), result);
    assert.equal(harness.getDownloads(), 1);
  }
});

test('buildExportFilename creates safe sanitized filenames for class and teacher views', () => {
  const classFilename = buildExportFilename(options);
  assert.equal(classFilename, 'Opencigan_A고등학교_1학년2반_week_2026-11-09.png');

  const teacherFilename = buildExportFilename({
    ...options,
    view: 'teacher',
    teacherName: '김철수/선생님*?',
  });
  assert.equal(teacherFilename, 'Opencigan_A고등학교_김철수선생님_teacher_2026-11-09.png');

  const specialCharsFilename = buildExportFilename({
    ...options,
    schoolName: '특수<학교>: "서울"',
    view: 'today',
    selectedDay: '2026-11-10',
  });
  assert.equal(specialCharsFilename, 'Opencigan_특수학교_서울_1학년2반_today_2026-11-10.png');

  const pdfFilename = buildExportFilename(options, 'pdf');
  assert.equal(pdfFilename, 'Opencigan_A고등학교_1학년2반_week_2026-11-09.pdf');

  const ultraLongSchool = '가'.repeat(200);
  const cappedFilename = buildExportFilename({ ...options, schoolName: ultraLongSchool });
  assert.ok(cappedFilename.length <= 120);
  assert.ok(cappedFilename.startsWith('Opencigan_'));
  assert.ok(cappedFilename.endsWith('_1학년2반_week_2026-11-09.png'));
  const longTeacher = buildExportFilename({ ...options, view: 'teacher', schoolName: '학교😀'.repeat(80), teacherName: '선생님😀'.repeat(80) });
  assert.ok(longTeacher.length <= 120);
  assert.ok(longTeacher.endsWith('_teacher_2026-11-09.png'));
  assert.doesNotMatch(longTeacher, /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u);
  assert.match(buildExportFilename({ ...options, view: 'teacher', teacherName: '///' }), /_선생님_teacher_/);
});

test('wrappedText preserves words when wrapping long labels and splits long tokens', () => {
  const dummyCtx = {
    measureText: (str) => ({ width: str.length * 10 }),
  };
  const wrapped = wrappedText(dummyCtx, '프로그래밍 실습 과목', 100);
  assert.deepEqual(Array.from(wrapped), ['프로그래밍 실습', '과목']);

  const longWordWrapped = wrappedText(dummyCtx, '아주긴단어과목명테스트용텍스트입니다', 80);
  assert.equal(longWordWrapped.length, 3);
  assert.equal(longWordWrapped[0], '아주긴단어과목명');
});

test('createTimetablePng handles empty periods and multiple lessons without throwing', async () => {
  const multipleLessons = [
    { grade: 1, class: 2, date: '2026-11-09', period: 1, subject: '인공지능 수학', teacher: '이순신', isChanged: false },
    { grade: 1, class: 2, date: '2026-11-09', period: 1, subject: '심화 정보통신', teacher: '강감찬', isChanged: true },
    { grade: 1, class: 2, date: '2026-11-09', period: 3, subject: '진로 활동', teacher: '권율', isChanged: false },
  ];
  const multiOptions = {
    ...options,
    records: multipleLessons,
  };
  let drawnLines = 0;
  let filledRects = 0;
  const filledTexts = [];
  let renderedCanvas;
  const mockContext = new Proxy({
    measureText: (val) => ({ width: val.length * 10 }),
    stroke: () => { drawnLines++; },
    fillRect: () => { filledRects++; },
    fillText: (text) => { filledTexts.push(text); },
    scale: () => {},
  }, { get: (target, key) => target[key] ?? (() => {}) });

  const sandbox = {
    exports: {},
    require: (name) => name === './personalization' ? personalization : undefined,
    Blob,
    document: {
      fonts: { ready: Promise.resolve() },
      createElement: () => (renderedCanvas = {
        getContext: () => mockContext,
        toBlob: (cb) => cb(new Blob(['png'], { type: 'image/png' })),
      }),
    },
  };
  runInNewContext(compiled, sandbox);
  const res = await sandbox.exports.createTimetablePng(multiOptions);
  assert.ok(res.blob);
  assert.equal(res.filename, 'Opencigan_A고등학교_1학년2반_week_2026-11-09.png');
  assert.ok(filledTexts.includes('—'), '빈 교시에 em-dash 플레이스홀더가 그려져야 합니다.');
  assert.ok(filledTexts.includes('인공지능 수학'));
  assert.ok(filledTexts.includes('심화 정보통신'));
  await sandbox.exports.createTimetablePng({ ...multiOptions, records: [
    { ...multipleLessons[0], subject: '가'.repeat(1000) },
  ] });
  assert.ok(renderedCanvas.width <= 4096 && renderedCanvas.height <= 4096, '긴 과목명도 캔버스 상한을 넘지 않는다');
  assert.ok(drawnLines > 0 && filledRects > 0);
});


test('PDF always uses a white canvas even when PNG follows dark mode', async () => {
  const backgrounds = [];
  let downloadedFilename = '';
  const context = new Proxy({
    measureText: (value) => ({ width: value.length * 10 }),
    fillRect(x, y) {
      if (x === 0 && y === 0) backgrounds.push(this.fillStyle);
    },
  }, { get: (target, key) => target[key] ?? (() => {}) });

  const mockPdfLib = {
    PDFDocument: { create: async () => ({
      embedPng: async () => ({ scaleToFit: () => ({ width: 300, height: 200 }) }),
      addPage: ([width, height]) => ({
        getWidth: () => width, getHeight: () => height, drawImage() {},
      }),
      save: async () => new Uint8Array([37, 80, 68, 70]),
    }) },
    PageSizes: { A4: [595, 842] },
  };
  const sandbox = {
    exports: {},
    require: (name) => {
      if (name === './personalization') return personalization;
      if (name === 'pdf-lib') return mockPdfLib;
      throw new Error('Unexpected dependency: ' + name);
    },
    Blob,
    document: {
      fonts: { ready: Promise.resolve() },
      body: { append() {} },
      createElement: (type) => type === 'canvas'
        ? {
          getContext: () => context,
          toBlob: (callback) => callback(new Blob(['png'], { type: 'image/png' })),
        }
        : {
          click() { downloadedFilename = this.download; },
          remove() {},
        },
    },
    URL: { createObjectURL: () => 'blob:local', revokeObjectURL() {} },
    window: { setTimeout() {} },
  };
  runInNewContext(compiled, sandbox);

  await sandbox.exports.saveTimetablePdf({ ...options, dark: true });
  assert.equal(backgrounds[0], '#ffffff');
  assert.match(downloadedFilename, /\.pdf$/);

  await sandbox.exports.createTimetablePng({ ...options, dark: true });
  assert.equal(backgrounds[1], '#111111');
});
