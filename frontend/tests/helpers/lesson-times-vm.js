import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../../src/lesson-times.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

export const lessonTimesVm = {};
runInNewContext(compiled, { exports: lessonTimesVm, Intl });
const backupSource = readFileSync(new URL('../../src/settings-backup.ts', import.meta.url), 'utf8');
const backupCompiled = ts.transpileModule(backupSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const backupExports = {};
runInNewContext(backupCompiled, { exports: backupExports, require: (path) => path === './lesson-times' ? lessonTimesVm : {} });
lessonTimesVm.readSourceLessonPreference = backupExports.readSourceLessonPreference;
