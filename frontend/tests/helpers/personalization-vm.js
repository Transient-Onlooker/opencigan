import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../../src/personalization.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

export const personalizationVm = {};
runInNewContext(compiled, { exports: personalizationVm });
const selection = readFileSync(new URL('../../src/selection.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(selection, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm, AbortController });
const cache = readFileSync(new URL('../../src/timetable-cache.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(cache, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm, AbortController });
const timetableView = readFileSync(new URL('../../src/timetable-view.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(timetableView, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm });
