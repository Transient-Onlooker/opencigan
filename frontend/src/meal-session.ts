import type { Meal, MealsResponse, NeisSchool, School } from './api';

type MealState = {
  neis: NeisSchool | null; candidates: NeisSchool[]; searchState: string; neisLoading: boolean;
  meals: Meal[]; hasMeals: boolean; stale: boolean; error: string; loading: boolean;
  dataKey: string; requestKey: string; refreshAt: number;
};

export function createMealSession(onChange: (state: MealState) => void) {
  let state: MealState = {
    neis: null, candidates: [], searchState: '', neisLoading: false,
    meals: [], hasMeals: false, stale: false, error: '', loading: false, dataKey: '', requestKey: '', refreshAt: 0,
  };
  let neisRequest: AbortController | undefined;
  let mealRequest: AbortController | undefined;
  const session = {
    update(change: Partial<MealState>) { state = { ...state, ...change }; onChange({ ...state }); },
    cancelNeis() { neisRequest?.abort(); },
    cancelMeals() { mealRequest?.abort(); },
    cancel() { session.cancelNeis(); session.cancelMeals(); },
    reset() {
      session.cancel();
      session.update({ neis: null, candidates: [], searchState: '', neisLoading: false, meals: [], hasMeals: false, stale: false, error: '', loading: false, dataKey: '', requestKey: '' });
    },
    choose(school: NeisSchool, save: (school: NeisSchool) => void, load: () => void) {
      session.cancelNeis();
      session.update({ neis: school, candidates: [], neisLoading: false, searchState: '급식도 ' + school.name + '로 연결했어요.' });
      try { save(school); } catch { /* The current connection still works without storage. */ }
      load();
    },
    async connect(
      school: School, currentSchoolId: () => string | undefined,
      search: (name: string, signal: AbortSignal) => Promise<{ schools: NeisSchool[]; stale: boolean }>,
      resolve: (school: School, candidates: NeisSchool[]) => NeisSchool | null | undefined,
      candidates: (school: School, candidates: NeisSchool[]) => NeisSchool[],
      choose: (school: NeisSchool) => void, errorText: (error: unknown) => string,
    ) {
      session.cancelNeis();
      const controller = new AbortController(); neisRequest = controller;
      session.update({ neisLoading: true, candidates: [], searchState: '같은 학교의 급식을 연결하고 있어요.' });
      try {
        const result = await search(school.name, controller.signal);
        if (controller.signal.aborted || currentSchoolId() !== school.id) return;
        const match = resolve(school, result.schools);
        if (match) choose(match);
        else {
          const found = candidates(school, result.schools);
          session.update({ candidates: found, searchState: found.length ? '같은 이름의 학교가 여러 곳이에요. 주소만 확인해 주세요.' : '같은 학교의 급식 정보를 찾지 못했어요.' });
        }
      } catch (error) {
        if (!controller.signal.aborted && currentSchoolId() === school.id) session.update({ searchState: errorText(error) });
      } finally {
        if (!controller.signal.aborted && neisRequest === controller) session.update({ neisLoading: false });
      }
    },
    load(neisId: string, from: string, to: string, preserve: boolean, now: () => number, interval: number,
      fetch: (school: string, from: string, to: string, signal: AbortSignal) => Promise<MealsResponse>, errorText: (error: unknown) => string) {
      const key = neisId + ':' + from;
      if (!preserve && state.hasMeals && state.dataKey === key && !state.loading && now() < state.refreshAt) return;
      if (state.loading && state.requestKey === key && !mealRequest?.signal.aborted) return;
      session.cancelMeals();
      if (!preserve || state.dataKey !== key) session.update({ meals: [], stale: false, hasMeals: false });
      const controller = new AbortController(); mealRequest = controller;
      session.update({ error: '', refreshAt: now() + interval, loading: true, requestKey: key });
      void fetch(neisId, from, to, controller.signal)
        .then((data) => { if (!controller.signal.aborted) session.update({ meals: data.meals, stale: data.stale, hasMeals: true, dataKey: key }); })
        .catch((error) => { if (!controller.signal.aborted) session.update({ error: errorText(error), stale: state.hasMeals && state.dataKey === key }); })
        .finally(() => { if (!controller.signal.aborted) session.update({ loading: false }); });
    },
  };
  return session;
}
