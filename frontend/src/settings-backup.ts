import { parseDisplaySettings, type DisplaySettings } from './personalization';
import { parseLessonTimes, parseWeekdayLessonTimes, type LessonTimes, type WeekdayLessonTimes } from './lesson-times';

export const MAX_SETTINGS_BACKUP_BYTES = 64 * 1024;

function rollbackWritten(storage: Storage, written: Array<[string, string]>, previous: Map<string, string | null>): boolean {
  let restored = true;
  for (const [key, value] of written.reverse()) {
    try {
      if (storage.getItem(key) !== value) { restored = false; continue; }
      const old = previous.get(key);
      if (old == null) storage.removeItem(key);
      else storage.setItem(key, old);
    } catch { restored = false; }
  }
  return restored;
}

export function saveLessonTimePreferences(storage: Storage, schoolId: string, lessonTimes: LessonTimes, weekdayLessonTimes: WeekdayLessonTimes, sourcePreference?: unknown) {
  const key = 'opensigan-lesson-times:' + schoolId;
  const weekdayKey = 'opensigan-weekday-lesson-times:' + schoolId;
  const preferenceKey = 'opensigan-source-lesson-preference:' + schoolId;
  const keys = sourcePreference === undefined ? [key, weekdayKey] : [key, weekdayKey, preferenceKey];
  const previous = new Map<string, string | null>(keys.map((storageKey): [string, string | null] => [storageKey, storage.getItem(storageKey)]));
  const written: Array<[string, string]> = [];
  try {
    const value = JSON.stringify(lessonTimes), weekdayValue = JSON.stringify(weekdayLessonTimes);
    storage.setItem(key, value);
    written.push([key, value]);
    storage.setItem(weekdayKey, weekdayValue);
    written.push([weekdayKey, weekdayValue]);
    if (sourcePreference !== undefined) {
      const preferenceValue = JSON.stringify(sourcePreference);
      storage.setItem(preferenceKey, preferenceValue);
      written.push([preferenceKey, preferenceValue]);
    }
  } catch {
    const restored = rollbackWritten(storage, written, previous);
    throw new Error(restored
      ? '브라우저 저장소에 설정을 저장하지 못했어요. 이전 저장값은 유지했어요.'
      : '설정 저장에 실패했고 일부 이전 값을 복구하지 못했어요. 브라우저 저장소를 확인해 주세요.');
  }
}

export function saveSchoolSettingsBackup(storage: Storage, schoolId: string, displaySettings: DisplaySettings, lessonTimes: LessonTimes, weekdayLessonTimes?: WeekdayLessonTimes) {
  const displayKey = 'opensigan-display:' + schoolId;
  const timesKey = 'opensigan-lesson-times:' + schoolId;
  const weekdayKey = 'opensigan-weekday-lesson-times:' + schoolId;
  const keys = weekdayLessonTimes === undefined ? [displayKey, timesKey] : [displayKey, timesKey, weekdayKey];
  const previous = new Map<string, string | null>(keys.map((key): [string, string | null] => [key, storage.getItem(key)]));
  const written: Array<[string, string]> = [];
  try {
    const display = JSON.stringify(displaySettings), times = JSON.stringify(lessonTimes);
    storage.setItem(displayKey, display); written.push([displayKey, display]);
    storage.setItem(timesKey, times); written.push([timesKey, times]);
    if (weekdayLessonTimes !== undefined) {
      const weekdays = JSON.stringify(weekdayLessonTimes);
      storage.setItem(weekdayKey, weekdays); written.push([weekdayKey, weekdays]);
    }
  } catch {
    const restored = rollbackWritten(storage, written, previous);
    throw new Error(restored
      ? '브라우저 저장소에 설정을 저장하지 못했어요.'
      : '설정 저장에 실패했고 일부 이전 값을 복구하지 못했어요. 브라우저 저장소를 확인해 주세요.');
  }
}

type ClassroomScope = { grade: number; classroom: number };

export function createSettingsBackup(schoolId: string, displaySettings: DisplaySettings, lessonTimes: LessonTimes, scope?: ClassroomScope, weekdayTimes?: WeekdayLessonTimes): string {
  const overrides = weekdayTimes === undefined ? undefined : parseWeekdayLessonTimes(weekdayTimes, lessonTimes);
  if (overrides === null) throw new Error('요일별 교시 시각이 잘못되었거나 서로 겹쳐요.');
  return JSON.stringify({
    format: 'opencigan-settings',
    version: !scope && overrides && Object.keys(overrides).length ? 2 : 1,
    schoolId,
    displaySettings: parseDisplaySettings(displaySettings),
    ...(scope ? { scope } : { lessonTimes: parseLessonTimes(lessonTimes) }),
    ...(!scope && overrides && Object.keys(overrides).length ? { weekdayLessonTimes: overrides } : {}),
  }, null, 2);
}

export function parseSettingsBackup(text: string, schoolId: string, scope?: ClassroomScope): { displaySettings: DisplaySettings; lessonTimes: LessonTimes; weekdayLessonTimes?: WeekdayLessonTimes; scoped?: true } {
  if (new TextEncoder().encode(text).length > MAX_SETTINGS_BACKUP_BYTES) throw new Error('설정 파일은 64KB 이하여야 해요.');
  let raw: unknown;
  try { raw = JSON.parse(text); } catch { throw new Error('올바른 JSON 설정 파일이 아니에요.'); }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Opencigan 설정 파일이 아니에요.');
  const backup = raw as Record<string, unknown>;
  if (backup.format !== 'opencigan-settings' || (backup.version !== 1 && backup.version !== 2)) throw new Error('지원하지 않는 설정 파일 형식이에요.');
  if (backup.version === 2 && backup.scope !== undefined) throw new Error('지원하지 않는 설정 파일 형식이에요.');
  if (backup.schoolId !== schoolId) throw new Error('현재 선택한 학교의 설정 파일만 불러올 수 있어요.');
  if (backup.scope !== undefined) {
    const target = backup.scope as Partial<ClassroomScope> | null;
    if (!target || !scope || target.grade !== scope.grade || target.classroom !== scope.classroom) {
      throw new Error('현재 선택한 학급의 설정 파일만 불러올 수 있어요.');
    }
  }
  if (!backup.displaySettings || typeof backup.displaySettings !== 'object' || Array.isArray(backup.displaySettings) ||
      (backup.scope === undefined && (!backup.lessonTimes || typeof backup.lessonTimes !== 'object' || Array.isArray(backup.lessonTimes)))) {
    throw new Error('시간표 표시 설정이나 교시 시각 정보가 누락되었어요.');
  }
  const display = backup.displaySettings as Record<string, unknown>;
  if (!('colorMode' in display) || !('showTeachers' in display)) throw new Error('표시 설정이 불완전해요.');
  if (backup.scope !== undefined) return { displaySettings: parseDisplaySettings(display), lessonTimes: {}, scoped: true };
  const lessonTimes = parseLessonTimes(backup.lessonTimes);
  if (Object.keys(lessonTimes).length !== Object.keys(backup.lessonTimes as object).length) {
    throw new Error('교시 시각이 잘못되었거나 서로 겹쳐요.');
  }
  if (backup.version === 2) {
    const weekdayLessonTimes = parseWeekdayLessonTimes(backup.weekdayLessonTimes, lessonTimes);
    if (!weekdayLessonTimes) throw new Error('요일별 교시 시각이 잘못되었거나 서로 겹쳐요.');
    return { displaySettings: parseDisplaySettings(display), lessonTimes, weekdayLessonTimes };
  }
  return { displaySettings: parseDisplaySettings(display), lessonTimes };
}
