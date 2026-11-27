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
const selectionStorage = readFileSync(new URL('../../src/selection-storage.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(selectionStorage, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm });
const cache = readFileSync(new URL('../../src/timetable-cache.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(cache, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm, AbortController });
const timetableView = readFileSync(new URL('../../src/timetable-view.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(timetableView, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm });
personalizationVm.countObservedClasses = personalizationVm.observedClassCount;
personalizationVm.findTeacherSuggestions = personalizationVm.teacherSuggestions;
personalizationVm.findSelectedTeacherName = personalizationVm.selectedTeacherName;
const history = readFileSync(new URL('../../src/history-session.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(history, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm, AbortController });
const meal = readFileSync(new URL('../../src/meal-session.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(meal, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm, AbortController });
const preferences = readFileSync(new URL('../../src/preferences.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(preferences, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm });
const schoolSearch = readFileSync(new URL('../../src/school-search-session.ts', import.meta.url), 'utf8');
runInNewContext(ts.transpileModule(schoolSearch, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { exports: personalizationVm, AbortController, setTimeout, clearTimeout });
