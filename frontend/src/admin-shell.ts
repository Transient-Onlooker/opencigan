import './admin.css';
import './standalone-theme';
import { mountSuggestions } from './admin-suggestions';
import { mountSchoolUsage } from './admin-school-usage';

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const form = document.querySelector<HTMLFormElement>('#admin-login')!;
const input = document.querySelector<HTMLInputElement>('#admin-token')!;
const state = document.querySelector<HTMLElement>('#admin-state')!;
const workspace = document.querySelector<HTMLElement>('#admin-workspace')!;
const content = document.querySelector<HTMLElement>('#admin-content')!;
const submit = form.querySelector<HTMLButtonElement>('button')!;
let token = '';
let generation = 0;
let loginRequest: AbortController | undefined;
let disposeContent: (() => void) | undefined;

function clearContent() {
  disposeContent?.();
  disposeContent = undefined;
  const frame = content.querySelector<HTMLIFrameElement>('iframe');
  frame?.contentWindow?.dispatchEvent(new Event('opencigan-admin-lock'));
  content.replaceChildren();
}

function lock() {
  generation++;
  loginRequest?.abort();
  loginRequest = undefined;
  token = '';
  input.value = '';
  clearContent();
  workspace.hidden = true;
  form.hidden = false;
  submit.disabled = false;
  state.textContent = '잠겼습니다.';
  input.focus();
}

function showPage(page: string) {
  if (!token || !['analytics', 'logs', 'anomalies', 'history', 'suggestions', 'status', 'schools'].includes(page)) return;
  const current = ++generation;
  clearContent();
  document.querySelectorAll<HTMLButtonElement>('[data-page]').forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.page === page));
  });
  if (page === 'suggestions') {
    disposeContent = mountSuggestions(content, token, base);
    return;
  }
  if (page === 'schools') {
    disposeContent = mountSchoolUsage(content, token, base);
    return;
  }
  if ((page === 'history' && import.meta.env.VITE_HISTORY_STATS_ENABLED !== '1') || (page === 'anomalies' && import.meta.env.VITE_ACCESS_ANOMALIES_ENABLED !== '1')) {
    const notice = document.createElement('p'); notice.setAttribute('role', 'status');
    notice.textContent = page === 'history' ? '시간표 관측 통계가 이 배포에서 활성화되지 않았습니다.' : '이상 접근 검토가 이 배포에서 활성화되지 않았습니다.';
    content.append(notice); return;
  }
  if (page === 'status') {
    const controller = new AbortController();
    disposeContent = () => controller.abort();
    const heading = document.createElement('h2'); heading.textContent = '서비스 상태';
    const message = document.createElement('p'); message.setAttribute('role', 'status'); message.textContent = '확인 중…';
    const description = document.createElement('p'); description.textContent = '백엔드 프로세스의 응답 상태입니다. 원본 시간표 서버의 상태는 이용 통계의 갱신 관측에서 확인하세요.';
    content.append(heading, message, description);
    void fetch(`${base}/api/v1/status`, { credentials: 'omit', cache: 'no-store', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]) })
      .then(async (response) => {
        const data = await response.json();
        if (!controller.signal.aborted) message.textContent = response.ok && data.status === 'ok' && data.scope === 'process liveness' ? '백엔드 프로세스 응답 정상' : '백엔드 응답을 확인하지 못했습니다.';
      })
      .catch(() => { if (!controller.signal.aborted) message.textContent = '백엔드 응답을 확인하지 못했습니다.'; });
    return;
  }
  const frame = document.createElement('iframe');
  const isAnalytics = page === 'analytics' || page === 'history';
  frame.title = page === 'history' ? '시간표 관측' : page === 'anomalies' ? '이상 접근' : isAnalytics ? '이용 통계' : '접속 로그';
  frame.className = 'admin-frame';
  frame.addEventListener('load', () => {
    if (generation !== current || !token || !frame.isConnected) return;
    const doc = frame.contentDocument;
    const field = doc?.querySelector<HTMLInputElement>('#token');
    if (!doc || !field) { state.textContent = '관리 화면을 불러오지 못했습니다.'; return; }
    field.value = token;
    field.closest('label')?.setAttribute('hidden', '');
    doc.querySelector('header')?.setAttribute('hidden', '');
    const oldLock = doc.querySelector<HTMLButtonElement>(isAnalytics ? '#clear' : '#lock-btn');
    oldLock?.addEventListener('click', (event) => { event.stopImmediatePropagation(); lock(); }, { capture: true });
    if (page === 'analytics') doc.querySelector<HTMLFormElement>('#login')?.requestSubmit();
    if (page === 'history') {
      doc.querySelector('#login')?.setAttribute('hidden', '');
      doc.querySelector('#state')?.setAttribute('hidden', '');
    }
    if (page === 'anomalies') {
      doc.querySelector('#filter-form')?.setAttribute('hidden', '');
      doc.querySelector('#state')?.setAttribute('hidden', '');
    }
  }, { once: true });
  frame.src = isAnalytics ? '/analytics.html' : '/access-logs.html';
  content.append(frame);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const candidate = input.value.trim();
  if (!candidate) return;
  loginRequest?.abort();
  const controller = new AbortController();
  loginRequest = controller;
  const current = ++generation;
  submit.disabled = true;
  state.textContent = '인증 중…';
  try {
    let verified = false;
    for (const path of ['/api/v1/admin/analytics?days=7', '/api/v1/admin/access-logs?limit=1']) {
      const response = await fetch(`${base}${path}`, {
        headers: { Authorization: `Bearer ${candidate}`, Accept: 'application/json' },
        credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
      });
      if (response.status === 401) throw new Error('관리자 토큰을 확인해 주세요.');
      if (response.status === 429) throw new Error('요청이 많아요. 잠시 후 다시 시도해 주세요.');
      if (response.ok) {
        const data = await response.json();
        verified = path.includes('/analytics?') ? Array.isArray(data.daily) && Array.isArray(data.routes) : Array.isArray(data.items);
        if (verified) break;
      }
    }
    if (!verified) throw new Error('관리자 인증을 확인할 수 없습니다. 관리자 기능 상태를 확인해 주세요.');
    if (controller.signal.aborted || current !== generation) return;
    token = candidate;
    input.value = '';
    form.hidden = true;
    workspace.hidden = false;
    state.textContent = '';
    showPage('analytics');
  } catch (error) {
    if (!controller.signal.aborted && current === generation) state.textContent = error instanceof Error ? error.message : '인증을 확인하지 못했습니다.';
  } finally {
    if (current === generation) submit.disabled = false;
  }
});
document.querySelector('#admin-lock')!.addEventListener('click', lock);
document.querySelectorAll<HTMLButtonElement>('[data-page]').forEach((button) => button.addEventListener('click', () => showPage(button.dataset.page ?? '')));
window.addEventListener('pagehide', lock);
