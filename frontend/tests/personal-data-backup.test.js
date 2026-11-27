import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import ts from 'typescript';

async function loadBackupModule(storagePrefix = 'personal_timetable_v1:') {
  const source = await readFile(new URL('../src/personal-data-backup.ts', import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  runInNewContext(compiled, {
    exports,
    require: (path) => path === './personal-timetable' ? { PERSONAL_STORAGE_PREFIX: storagePrefix } : undefined,
  });
  return exports;
}

function createStorage(values) {
  return Object.assign(Object.create({
    getItem(key) { return values[key] ?? null; },
  }), values);
}

test('detects personal data only under the existing storage prefix', async () => {
  const backup = await loadBackupModule();
  assert.equal(backup.hasPersonalData(createStorage({ 'opensigan-theme': 'dark' })), false);
  assert.equal(backup.hasPersonalData(createStorage({ 'personal_timetable_v1:school:1:2': '{}' })), true);
});

test('backup keeps matching raw keys and values in the existing version-one envelope', async () => {
  const backup = await loadBackupModule();
  const storage = createStorage({
    'personal_timetable_v1:B10:1234:2:3': '{"version":1,"entries":[]}',
    'personal_timetable_v1:다른학교:1:1': '{손상된 기존 원문',
    'opensigan-theme': 'dark',
  });

  assert.equal(backup.createPersonalDataBackup(storage), JSON.stringify({
    format: 'opencigan-personal-data',
    version: 1,
    entries: [
      { key: 'personal_timetable_v1:B10:1234:2:3', value: '{"version":1,"entries":[]}' },
      { key: 'personal_timetable_v1:다른학교:1:1', value: '{손상된 기존 원문' },
    ],
  }, null, 2));
});

test('storage read errors propagate to the settings screen error handler', async () => {
  const backup = await loadBackupModule();
  const storage = Object.create({
    getItem() { throw new Error('storage blocked'); },
  });
  storage['personal_timetable_v1:school:1:1'] = '{}';

  assert.throws(() => backup.createPersonalDataBackup(storage), /storage blocked/);
});
