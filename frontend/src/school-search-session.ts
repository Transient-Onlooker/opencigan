import type { School } from './api';

export function createSchoolSearchSession(onChange: (results: School[], message: string, retryable?: boolean) => void, storage?: () => Storage) {
  let timer: ReturnType<typeof setTimeout>;
  let request: AbortController | undefined;
  const cache = new Map<string, { schools: School[]; savedAt: number }>();
  const storageKey = 'opencigan-school-search-cache-v1';
  try {
    const raw = storage?.().getItem(storageKey);
    if (raw && raw.length <= 200_000) {
      const entries: unknown = JSON.parse(raw);
      if (Array.isArray(entries)) for (const entry of entries.slice(-10)) {
        if (!Array.isArray(entry) || typeof entry[0] !== 'string' || entry[0].trim() !== entry[0] || entry[0].length < 2 || entry[0].length > 50) continue;
        const value = entry[1];
        if (!value || !Number.isFinite(value.savedAt) || value.savedAt <= 0 || value.savedAt > Date.now() || !Array.isArray(value.schools) || !value.schools.length || value.schools.length > 100) continue;
        if (!value.schools.every((school: unknown) => school && typeof school === 'object' && ['id', 'name', 'region'].every((key) => typeof (school as Record<string, unknown>)[key] === 'string' && ((school as Record<string, string>)[key]).length <= 500))) continue;
        cache.set(entry[0], { savedAt: value.savedAt, schools: value.schools.map((school: School) => ({ id: school.id, name: school.name, region: school.region })) });
      }
    }
  } catch { /* 저장소를 사용할 수 없으면 화면 내 캐시만 사용합니다. */ }
  const session = {
    cancel() { clearTimeout(timer); request?.abort(); },
    clear() { session.cancel(); onChange([], ''); },
    find(query: () => string, search: (value: string, signal: AbortSignal) => Promise<{ schools: School[]; stale: boolean }>, errorText: (error: unknown) => string) {
      session.clear();
      const text = query().trim();
      if (text.length < 2) { onChange([], query().length ? '학교 이름을 두 글자 이상 입력해 주세요.' : ''); return; }
      if (text.length > 50) { onChange([], '학교 이름은 최대 50자까지 검색할 수 있어요.'); return; }
      onChange([], '검색 중…');
      timer = setTimeout(async () => {
        const controller = new AbortController(); request = controller;
        try {
          const result = await search(text, controller.signal);
          if (controller.signal.aborted || query().trim() !== text) return;
          if (!result.stale && result.schools.length) {
            cache.delete(text);
            cache.set(text, { schools: result.schools.slice(), savedAt: Date.now() });
            if (cache.size > 10) cache.delete(cache.keys().next().value!);
            try { storage?.().setItem(storageKey, JSON.stringify([...cache])); } catch { /* 현재 화면의 캐시는 유지합니다. */ }
          }
          onChange(result.schools, result.stale ? '저장된 검색 결과예요. 최신 정보가 아닐 수 있습니다.' : result.schools.length ? '' : '검색 결과가 없어요. 컴시간에서 시간표를 제공하지 않는 학교는 검색되지 않을 수 있습니다.', result.stale);
        } catch (error) {
          if (controller.signal.aborted || query().trim() !== text) return;
          const saved = cache.get(text);
          const notice = errorText(error);
          if (saved) {
            const time = new Date(saved.savedAt).toLocaleString('ko-KR');
            onChange(saved.schools.slice(), `${notice} 이 기기에 저장된 검색 결과(${time})예요. 최신 정보가 아닐 수 있습니다.`, true);
          } else onChange([], `${notice} 이 검색어의 저장된 결과가 없어요.`, true);
        }
      }, 250);
    },
  };
  return session;
}
