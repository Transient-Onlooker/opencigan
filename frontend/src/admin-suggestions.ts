type SuggestionStatus = 'pending' | 'approved' | 'rejected' | 'merged';

interface Suggestion {
  id: string;
  title: string;
  description: string;
  context: string | null;
  status: SuggestionStatus;
  created_at: string;
  reviewed_at: string | null;
  merged_into: string | null;
  reviewer_note: string | null;
}

interface SuggestionPage {
  suggestions: Suggestion[];
  nextCursor: string | null;
}

const statuses: { value: SuggestionStatus | ''; label: string }[] = [
  { value: '', label: '전체 상태' },
  { value: 'pending', label: '검토 대기' },
  { value: 'approved', label: '승인' },
  { value: 'rejected', label: '거절' },
  { value: 'merged', label: '병합' },
];

const statusLabels: Record<SuggestionStatus, string> = {
  pending: '검토 대기',
  approved: '승인',
  rejected: '거절',
  merged: '병합',
};

export function mountSuggestions(container: HTMLElement, token: string, base: string): () => void {
  let adminToken = token;
  let cursor: string | null = null;
  let selectedStatus: SuggestionStatus | '' = '';
  let busy = false;
  let disposed = false;
  const controllers = new Set<AbortController>();
  const doc = container.ownerDocument;

  const root = doc.createElement('section');
  root.setAttribute('aria-label', '기능 제안 관리');
  const heading = doc.createElement('h2');
  heading.textContent = '기능 제안 관리';
  const form = doc.createElement('form');
  const statusLabel = doc.createElement('label');
  statusLabel.textContent = '상태 필터';
  const statusSelect = doc.createElement('select');
  statusSelect.setAttribute('aria-label', '상태 필터');
  for (const optionData of statuses) {
    const option = doc.createElement('option');
    option.value = optionData.value;
    option.textContent = optionData.label;
    statusSelect.append(option);
  }
  statusLabel.append(statusSelect);
  const refreshButton = doc.createElement('button');
  refreshButton.type = 'submit';
  refreshButton.textContent = '조회';
  form.append(statusLabel, refreshButton);

  const state = doc.createElement('p');
  state.setAttribute('role', 'status');
  state.setAttribute('aria-live', 'polite');
  const list = doc.createElement('div');
  const moreButton = doc.createElement('button');
  moreButton.type = 'button';
  moreButton.textContent = '더 보기';
  moreButton.hidden = true;
  root.append(heading, form, state, list, moreButton);
  container.replaceChildren(root);

  function makeButton(label: string, action: () => void) {
    const button = doc.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', action);
    return button;
  }

  function render(items: Suggestion[], append: boolean) {
    if (!append) list.replaceChildren();
    for (const item of items) {
      const article = doc.createElement('article');
      const title = doc.createElement('h3');
      title.textContent = item.title;
      const meta = doc.createElement('p');
      meta.textContent = `${statusLabels[item.status] ?? '알 수 없는 상태'} · ${item.created_at}`;
      const description = doc.createElement('p');
      description.textContent = item.description;
      article.append(title, meta, description);
      if (item.context) {
        const context = doc.createElement('p');
        context.textContent = `사용 맥락: ${item.context}`;
        article.append(context);
      }
      if (item.reviewer_note) {
        const note = doc.createElement('p');
        note.textContent = `검토 메모: ${item.reviewer_note}`;
        article.append(note);
      }

      const noteInput = doc.createElement('input');
      noteInput.type = 'text';
      noteInput.maxLength = 500;
      noteInput.setAttribute('aria-label', `${item.title} 검토 메모`);
      article.append(noteInput);

      if (item.status === 'pending') {
        article.append(
          makeButton('승인', () => void transition(item, 'approved', noteInput.value)),
          makeButton('거절', () => void transition(item, 'rejected', noteInput.value)),
        );
        const targetSelect = doc.createElement('select');
        targetSelect.setAttribute('aria-label', `${item.title} 병합 대상`);
        const placeholder = doc.createElement('option');
        placeholder.value = '';
        placeholder.textContent = '병합 대상 선택';
        targetSelect.append(placeholder);
        for (const target of visibleItems.filter((candidate) => candidate.id !== item.id && candidate.status !== 'rejected' && candidate.status !== 'merged')) {
          const option = doc.createElement('option');
          option.value = target.id;
          option.textContent = target.title;
          targetSelect.append(option);
        }
        article.append(targetSelect, makeButton('병합', () => {
          if (!targetSelect.value) { state.textContent = '병합할 제안을 선택해 주세요.'; return; }
          void transition(item, 'merged', noteInput.value, targetSelect.value);
        }));
      } else if (item.status === 'approved') {
        article.append(makeButton('거절', () => void transition(item, 'rejected', noteInput.value)));
      } else if (item.status === 'rejected') {
        article.append(makeButton('승인', () => void transition(item, 'approved', noteInput.value)));
      }
      article.append(makeButton('삭제', () => void remove(item)));
      list.append(article);
    }
  }

  let visibleItems: Suggestion[] = [];

  function beginRequest() {
    const controller = new AbortController();
    controllers.add(controller);
    return controller;
  }

  async function load(append = false) {
    if (busy || disposed) return;
    busy = true;
    statusSelect.disabled = true;
    refreshButton.disabled = true;
    moreButton.disabled = true;
    state.textContent = '제안을 불러오는 중…';
    const controller = beginRequest();
    const params = new URLSearchParams({ limit: '50' });
    if (selectedStatus) params.set('status', selectedStatus);
    if (append && cursor) params.set('cursor', cursor);
    try {
      const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/admin/suggestions?${params}`, {
        headers: { Authorization: `Bearer ${adminToken}`, Accept: 'application/json' },
        credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
      });
      if (!response.ok) throw new Error(response.status === 401 ? '관리자 토큰을 확인해 주세요.' : `제안을 불러오지 못했습니다. (${response.status})`);
      const data = await response.json() as SuggestionPage;
      if (!Array.isArray(data.suggestions) || (data.nextCursor !== null && typeof data.nextCursor !== 'string')) {
        throw new Error('서버 응답 형식이 올바르지 않습니다.');
      }
      if (disposed || controller.signal.aborted) return;
      visibleItems = append ? [...visibleItems, ...data.suggestions] : data.suggestions;
      cursor = data.nextCursor;
      render(data.suggestions, append);
      moreButton.hidden = !cursor;
      state.textContent = visibleItems.length ? `${visibleItems.length}건의 제안을 표시하고 있습니다.` : '제안이 없습니다.';
    } catch (error) {
      if (!disposed && !controller.signal.aborted) state.textContent = error instanceof Error ? error.message : '제안을 불러오지 못했습니다.';
    } finally {
      controllers.delete(controller);
      busy = false;
      if (!disposed) { refreshButton.disabled = false; moreButton.disabled = false; statusSelect.disabled = false; }
    }
  }

  async function transition(item: Suggestion, status: SuggestionStatus, reviewerNote: string, mergedInto?: string) {
    const action = status === 'approved' ? '승인' : status === 'rejected' ? '거절' : '병합';
    if (!window.confirm(`이 제안을 ${action}할까요?`)) return;
    await mutate(item, 'PATCH', { status, reviewer_note: reviewerNote.trim() || null, ...(mergedInto ? { merged_into: mergedInto } : {}) }, `${action}했습니다.`);
  }

  async function remove(item: Suggestion) {
    if (!window.confirm(`“${item.title}” 제안을 삭제할까요? 이 작업은 되돌릴 수 없습니다.`)) return;
    await mutate(item, 'DELETE', undefined, '제안을 삭제했습니다.');
  }

  async function mutate(item: Suggestion, method: 'PATCH' | 'DELETE', payload: unknown, success: string) {
    if (busy || disposed) return;
    busy = true;
    statusSelect.disabled = true;
    refreshButton.disabled = true;
    moreButton.disabled = true;
    state.textContent = '변경 사항을 저장하는 중…';
    const controller = beginRequest();
    let shouldReload = false;
    try {
      const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/admin/suggestions/${encodeURIComponent(item.id)}`, {
        method,
        headers: { Authorization: `Bearer ${adminToken}`, Accept: 'application/json', ...(payload ? { 'Content-Type': 'application/json' } : {}) },
        ...(payload ? { body: JSON.stringify(payload) } : {}),
        credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
      });
      if (!response.ok) throw new Error(response.status === 401 ? '관리자 토큰을 확인해 주세요.' : response.status === 404 ? '제안을 찾을 수 없습니다.' : response.status === 400 ? '상태 변경 조건을 확인해 주세요.' : `변경을 저장하지 못했습니다. (${response.status})`);
      if (disposed || controller.signal.aborted) return;
      state.textContent = success;
      shouldReload = true;
    } catch (error) {
      if (!disposed && !controller.signal.aborted) state.textContent = error instanceof Error ? error.message : '변경을 저장하지 못했습니다.';
    } finally {
      controllers.delete(controller);
      busy = false;
      if (!disposed) { refreshButton.disabled = false; moreButton.disabled = false; statusSelect.disabled = false; }
    }
    if (shouldReload && !disposed) await load();
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    selectedStatus = statusSelect.value as SuggestionStatus | '';
    cursor = null;
    visibleItems = [];
    void load();
  });
  moreButton.addEventListener('click', () => void load(true));
  void load();

  return () => {
    if (disposed) return;
    disposed = true;
    for (const controller of controllers) controller.abort();
    controllers.clear();
    adminToken = '';
    visibleItems = [];
    cursor = null;
    container.replaceChildren();
  };
}
