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
    cancel() { request?.abort(); },
    begin() {
      request?.abort();
      request = new AbortController();
      return request;
    },
  };
}
