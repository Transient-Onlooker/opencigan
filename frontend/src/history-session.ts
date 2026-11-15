import type { TimetableChange, TimetableHistoryResponse } from './api';

type HistoryState = { loading: boolean; disabled: boolean; error: string; changes: TimetableChange[]; cursor: string | null };

export function createHistorySession(onChange: (state: HistoryState) => void) {
  let state: HistoryState = { loading: false, disabled: false, error: '', changes: [], cursor: null };
  let request: AbortController | undefined;
  let requestKey = '';
  const session = {
    update(change: Partial<HistoryState>) { state = { ...state, ...change }; onChange({ ...state }); },
    cancel() { request?.abort(); request = undefined; requestKey = ''; },
    reset() {
      session.cancel();
      session.update({ loading: false, disabled: false, error: '', changes: [], cursor: null });
    },
    async load(
      schoolId: string | undefined, week: string, append: boolean,
      current: () => { schoolId: string | undefined; week: string },
      fetch: (schoolId: string, week: string, cursor: string | null, signal: AbortSignal) => Promise<TimetableHistoryResponse>,
      errorText: (error: unknown) => string,
    ) {
      if (!schoolId || state.disabled || state.loading) return;
      const key = schoolId + '\u0000' + week;
      session.cancel();
      const controller = new AbortController(); request = controller; requestKey = key;
      session.update({ loading: true, error: '' });
      const active = () => !controller.signal.aborted && requestKey === key && current().schoolId === schoolId && current().week === week;
      try {
        const data = await fetch(schoolId, week, append ? state.cursor : null, controller.signal);
        if (active()) session.update({ changes: append ? [...state.changes, ...data.changes] : data.changes, cursor: data.nextCursor });
      } catch (error) {
        if (active()) {
          if (typeof error === 'object' && error !== null && 'code' in error && error.code === 'history_disabled') session.update({ disabled: true });
          else session.update({ error: errorText(error) });
        }
      } finally {
        if (active()) session.update({ loading: false });
      }
    },
  };
  return session;
}
