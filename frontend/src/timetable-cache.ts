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
    invalidate(key: string) { weeks.delete(key); },
  };
}

export type TimetableSessionState = { data: TimetableResponse | null; fromDevice: boolean; loading: boolean; error: string; refreshAt: number };
type TimetableLoad = {
  schoolId: string | undefined; week: string; preserve: boolean; reuseCachedWeek: boolean; validateClass: boolean;
  refreshInterval: number; now: () => number; storage: () => Storage;
  current: () => { schoolId: string | undefined; week: string };
  fetch: (schoolId: string, week: string, signal: AbortSignal) => Promise<TimetableResponse>;
  validate: () => void; classError: () => boolean; errorText: (error: unknown) => string;
  onSuccess: (data: TimetableResponse) => void; onFailure: () => void;
};

export function createTimetableSession(onChange: (state: TimetableSessionState) => void = () => {}) {
  const cache = createTimetableCache();
  let request: AbortController | undefined;
  let state: TimetableSessionState = { data: null, fromDevice: false, loading: false, error: '', refreshAt: 0 };
  const session = {
    cache,
    update(change: Partial<TimetableSessionState>) {
      state = { ...state, ...change };
      onChange({ ...state });
    },
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
    fetch(schoolId: string, week: string, current: () => { schoolId: string | undefined; week: string }, load: (schoolId: string, week: string, signal: AbortSignal) => Promise<TimetableResponse>, accept: (data: TimetableResponse) => void) {
      const controller = session.begin();
      const result = load(schoolId, week, controller.signal).then((data) => {
        if (controller.signal.aborted) return;
        const selected = current();
        if (data.schoolId !== selected.schoolId || data.weekStart !== selected.week) throw new Error('선택한 학교·주차와 다른 시간표가 도착했어요.');
        accept(data);
      });
      return { controller, result };
    },
    load(options: TimetableLoad) {
      session.cancel();
      session.update({ ...(options.preserve ? {} : { data: null, fromDevice: false }), error: '', loading: false });
      if (!options.schoolId) return;
      const key = options.schoolId + '\u0000' + options.week;
      if (options.reuseCachedWeek) {
        const cached = cache.get(key, options.now());
        if (cached) {
          session.update({ data: cached.data, fromDevice: false });
          if (options.validateClass) options.validate();
          if (options.current().schoolId !== cached.data.schoolId || options.classError()) return;
          session.update({ refreshAt: cached.expires });
          return;
        }
      }
      session.update({ refreshAt: options.now() + options.refreshInterval });
      const { controller, result } = session.fetch(options.schoolId, options.week, options.current, options.fetch, (data) => {
        if (data.stale) cache.invalidate(key);
        session.update({ data, fromDevice: false });
        if (options.validateClass) options.validate();
        if (controller.signal.aborted || options.classError()) return;
        options.onSuccess(data);
        session.saveFresh(key, data, options.now() + options.refreshInterval, options.storage);
      });
      session.update({ loading: true });
      void result.catch((error) => {
        if (controller.signal.aborted) return;
        cache.invalidate(key);
        const selected = options.current();
        if (state.data && state.data.schoolId === selected.schoolId && state.data.weekStart === selected.week) {
          session.update({ data: { ...state.data, stale: true } });
        } else {
          const saved = selected.schoolId && session.restoreOffline(selected.schoolId, selected.week, options.storage);
          session.update({ data: saved || null, fromDevice: !!saved });
        }
        if (options.validateClass) options.validate();
        if (controller.signal.aborted) return;
        session.update({ error: options.errorText(error) });
        options.onFailure();
      }).finally(() => { if (!controller.signal.aborted) session.update({ loading: false }); });
    },
  };
  return session;
}
