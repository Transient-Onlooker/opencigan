import type { TimetableResponse } from './api';

export function createTimetableCache(limit = 4) {
  const weeks = new Map<string, { data: TimetableResponse; expires: number }>();
  return {
    get(key: string, now: number) {
      const cached = weeks.get(key);
      if (cached && cached.expires > now) return cached;
      weeks.delete(key);
      return undefined;
    },
    put(key: string, data: TimetableResponse, expires: number) {
      weeks.delete(key);
      weeks.set(key, { data, expires });
      if (weeks.size > limit) weeks.delete(weeks.keys().next().value!);
    },
  };
}

export function createTimetableSession() {
  const cache = createTimetableCache();
  let request: AbortController | undefined;
  return {
    cache,
    saveFresh(key: string, data: TimetableResponse, expires: number, storage: () => Storage) {
      if (data.stale) return;
      try { storage().setItem('opensigan-offline-timetable', JSON.stringify(data)); } catch { /* Memory cache still works without storage. */ }
      cache.put(key, data, expires);
    },
    restoreOffline(schoolId: string, week: string, storage: () => Storage): TimetableResponse | null {
      try {
        const saved = JSON.parse(storage().getItem('opensigan-offline-timetable') || 'null') as TimetableResponse | null;
        return saved && saved.schoolId === schoolId && saved.weekStart === week && Array.isArray(saved.records) ? saved : null;
      } catch { return null; }
    },
    cancel() { request?.abort(); },
    begin() {
      request?.abort();
      request = new AbortController();
      return request;
    },
  };
}
