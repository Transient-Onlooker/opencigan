import type { School } from './api';

export function createSchoolSearchSession(onChange: (results: School[], message: string) => void) {
  let timer: ReturnType<typeof setTimeout>;
  let request: AbortController | undefined;
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
          const result = await search(query().trim(), controller.signal);
          if (!controller.signal.aborted) onChange(result.schools, result.stale ? '저장된 검색 결과예요. 최신 정보가 아닐 수 있습니다.' : result.schools.length ? '' : '검색 결과가 없어요. 컴시간에서 시간표를 제공하지 않는 학교는 검색되지 않을 수 있습니다.');
        } catch (error) { if (!controller.signal.aborted) onChange([], errorText(error)); }
      }, 250);
    },
  };
  return session;
}
