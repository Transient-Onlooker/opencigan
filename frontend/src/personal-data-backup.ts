import { PERSONAL_STORAGE_PREFIX } from './personal-timetable';

export interface PersonalDataBackupEntry {
  key: string;
  value: string | null;
}

export function hasPersonalData(storage: Storage): boolean {
  return Object.keys(storage).some((key) => key.startsWith(PERSONAL_STORAGE_PREFIX));
}

export function createPersonalDataBackup(storage: Storage): string {
  const entries: PersonalDataBackupEntry[] = Object.keys(storage)
    .filter((key) => key.startsWith(PERSONAL_STORAGE_PREFIX))
    .map((key) => ({ key, value: storage.getItem(key) }));

  return JSON.stringify({ format: 'opencigan-personal-data', version: 1, entries }, null, 2);
}
