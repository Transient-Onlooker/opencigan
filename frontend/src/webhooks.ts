import './admin.css';
import './webhooks.css';
import './standalone-theme';

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const input = (id: string) => document.querySelector<HTMLInputElement>(`#${id}`)!;
const select = (id: string) => document.querySelector<HTMLSelectElement>(`#${id}`)!;
const state = document.querySelector<HTMLElement>('#state')!;
const manage = document.querySelector<HTMLElement>('#manage')!;
const table = document.querySelector<HTMLElement>('#deliveries')!;
const templateBody = document.querySelector<HTMLTextAreaElement>('#template-body')!;
const templateFormat = select('template-format');
const templateErrors = document.querySelector<HTMLElement>('#template-errors')!;
const templatePreview = document.querySelector<HTMLElement>('#template-preview')!;
const templatePreviewFormat = document.querySelector<HTMLElement>('#template-preview-format')!;
const templateSave = document.querySelector<HTMLButtonElement>('#template-save')!;
const templateDefaults = '{school} {grade}학년 {classroom}반 · {date} {period}교시 ({type})\n{before} → {after}';
const templateVariables = new Set(['school', 'grade', 'classroom', 'date', 'period', 'type', 'before', 'after']);
const buttons = [...document.querySelectorAll<HTMLButtonElement>('button')];
let templateProvider = '';
let previewTimer = 0;
let previewRevision = 0;
let controller = new AbortController();
let rotationToken = '';

async function call(path: string, method = 'GET', payload?: unknown, authenticated = true) {
  if (!base && location.hostname.endsWith('.github.io')) throw new Error('API가 연결된 배포 주소에서 이용해 주세요.');
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (authenticated) headers.Authorization = `Bearer ${input('token').value}`;
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`${base}/api/v1/webhooks${path}`, { method, headers, body: payload === undefined ? undefined : JSON.stringify(payload),
    credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer', signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]) });
  if (!response.ok) throw new Error(response.status === 401 ? '구독 ID와 관리 토큰을 확인해 주세요.' : response.status === 429 ? '요청이 많아요. 잠시 후 다시 시도해 주세요.' : response.status === 503 ? '서버에서 알림 기능을 사용할 수 없어요.' : `요청을 처리하지 못했어요. (${response.status})`);
  return response.json();
}

function subscriptionPath() {
  const id = input('id').value.trim();
  if (!/^[A-Za-z0-9_-]{24}$/.test(id) || !/^[A-Za-z0-9_-]{43}$/.test(input('token').value)) throw new Error('구독 ID와 관리 토큰을 확인해 주세요.');
  return `/${id}`;
}

async function run(action: () => Promise<void>) {
  buttons.forEach((button) => { if (button.id !== 'lock') button.disabled = true; });
  const active = controller;
  try { await action(); } catch (error) { if (!active.signal.aborted) state.textContent = error instanceof Error ? error.message : '요청을 처리하지 못했어요.'; }
  finally { if (active === controller) buttons.forEach((button) => { button.disabled = false; }); }
}

function reset() {
  controller.abort(); controller = new AbortController();
  window.clearTimeout(previewTimer);
  previewRevision += 1;
  input('id').value = ''; input('token').value = ''; input('destination').value = '';
  clearRotation();
  manage.hidden = true; table.replaceChildren();
  document.querySelector<HTMLFormElement>('#filters')!.reset(); document.querySelector('#scope')!.textContent = '';
  templateProvider = ''; templateBody.value = templateDefaults; templateFormat.value = 'text';
  templateFormat.disabled = false; templateSave.disabled = true; templateErrors.textContent = '';
  templateBody.removeAttribute('aria-invalid'); templatePreview.textContent = '';
  templatePreview.dataset.format = 'text'; templatePreview.dataset.invalid = 'false'; templatePreviewFormat.textContent = '';
  buttons.forEach((button) => { button.disabled = false; });
}

function clearRotation() {
  rotationToken = ''; input('rotation-link').value = ''; input('rotation-saved').checked = false;
  document.querySelector<HTMLElement>('#rotation')!.hidden = true;
}

async function loadDeliveries(path: string) {
  const result = await call(`${path}/deliveries`);
  table.replaceChildren();
  const states: Record<string, string> = { pending: '대기', leased: '전송 중', delivered: '성공', failed: '실패' };
  for (const item of result.deliveries) {
    const row = document.createElement('tr');
    for (const value of [item.event_id, states[item.state] ?? item.state, item.attempts, item.last_status ?? '—']) {
      const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell);
    }
    const nextAt = document.createElement('td');
    if (item.state === 'pending' && typeof item.next_at === 'number') {
      const timestamp = new Date(item.next_at * 1000);
      if (!Number.isNaN(timestamp.getTime())) {
        const time = document.createElement('time');
        time.dateTime = timestamp.toISOString();
        const localTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(timestamp);
        time.textContent = localTime;
        time.setAttribute('aria-label', `다음 처리 시각: ${localTime}`);
        nextAt.append(time);
      }
    }
    row.append(nextAt);
    table.append(row);
  }
}

async function load() {
  manage.hidden = true; table.replaceChildren();
  const path = subscriptionPath();
  const result = await call(path);
  const templateEditor = document.querySelector<HTMLElement>('#template-editor')!;
  templateEditor.hidden = true;
  try {
    await loadTemplate(path, result.provider);
    templateEditor.hidden = false;
  } catch {
    // Older servers may not provide template management yet.
  }
  const f = result.filters ?? {};
  input('subject').value = f.subject ?? ''; input('teacher').value = f.teacher ?? '';
  select('weekday').value = String(f.weekday ?? ''); input('period').value = String(f.period ?? ''); select('kind').value = f.type ?? '';
  input('quiet-start').value = f.quietHours?.start ?? ''; input('quiet-end').value = f.quietHours?.end ?? '';
  document.querySelector('#scope')!.textContent = `${result.school} · ${result.grade}학년 ${result.classroom}반 · ${result.provider} · 누락 ${result.dropped_events}건`;
  await loadDeliveries(path); manage.hidden = false;
  state.textContent = '구독 정보를 불러왔어요.';
}

async function copyLink() {
  const id = input('id').value.trim();
  const token = input('token').value.trim();
  if (!/^[A-Za-z0-9_-]{24}$/.test(id) || !/^[A-Za-z0-9_-]{43}$/.test(token)) {
    throw new Error('구독 ID와 관리 토큰을 확인해 주세요.');
  }
  const link = `${location.origin}${location.pathname}#id=${id}&token=${token}`;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(link);
    state.textContent = '관리 링크를 클립보드에 복사했어요. 링크나 토큰을 공유하거나 북마크하면 관리 권한이 노출될 수 있으니 주의하세요.';
  } else {
    throw new Error('클립보드를 사용할 수 없는 환경입니다.');
  }
}

function validateTemplate(value: string) {
  if (!value.trim()) return '템플릿 내용을 입력해 주세요.';
  if (value.length > 1200) return '템플릿은 1,200자 이내로 입력해 주세요.';
  for (let index = 0; index < value.length;) {
    if (value[index] === '{') {
      if (value[index + 1] === '{') { index += 2; continue; }
      const end = value.indexOf('}', index + 1);
      if (end < 0) return '닫는 중괄호가 없는 변수가 있어요.';
      if (!templateVariables.has(value.slice(index + 1, end))) return `지원하지 않는 변수예요: ${value.slice(index, end + 1)}`;
      index = end + 1;
    } else if (value[index] === '}') {
      if (value[index + 1] !== '}') return '짝이 맞지 않는 중괄호가 있어요.';
      index += 2;
    } else index += 1;
  }
  return '';
}

function templatePayload() {
  return { template: templateBody.value, discordEmbed: templateProvider === 'discord' && templateFormat.value === 'embed' };
}

function setPreview(payload: Record<string, unknown>) {
  const embed = Array.isArray(payload.embeds);
  const content = payload.content ?? payload.text ?? (Array.isArray(payload.embeds)
    ? (payload.embeds[0] as Record<string, unknown> | undefined)?.description
    : '');
  templatePreview.textContent = typeof content === 'string' ? content : '';
  templatePreview.dataset.format = embed ? 'embed' : 'text';
  templatePreview.dataset.invalid = 'false';
  templatePreviewFormat.textContent = embed ? 'Discord 임베드 미리보기' : templateProvider === 'google-chat' ? 'Google Chat 메시지 미리보기' : 'Discord 메시지 미리보기';
}

async function previewTemplate() {
  const revision = ++previewRevision;
  const invalid = validateTemplate(templateBody.value);
  templateErrors.textContent = invalid;
  templateBody.setAttribute('aria-invalid', String(Boolean(invalid)));
  if (invalid) {
    templatePreview.textContent = '입력한 템플릿을 확인해 주세요.';
    templatePreview.dataset.invalid = 'true';
    return;
  }
  try {
    const result = await call(`${subscriptionPath()}/template/preview`, 'POST', templatePayload());
    if (revision === previewRevision) setPreview(result.payload);
  } catch (error) {
    if (!controller.signal.aborted && revision === previewRevision) {
      templatePreview.textContent = error instanceof Error ? error.message : '미리보기를 불러오지 못했어요.';
      templatePreview.dataset.invalid = 'true';
    }
  }
}

function queuePreview() {
  window.clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => { void previewTemplate(); }, 250);
}

async function loadTemplate(path: string, provider: string) {
  const result = await call(`${path}/template`);
  if ((result.template !== null && typeof result.template !== 'string') || typeof result.discordEmbed !== 'boolean') {
    throw new Error('템플릿 응답을 확인하지 못했어요.');
  }
  templateProvider = result.provider ?? provider ?? '';
  templateBody.value = result.template ?? templateDefaults;
  templateFormat.value = result.discordEmbed === true ? 'embed' : 'text';
  templateFormat.disabled = templateProvider !== 'discord';
  templateSave.disabled = false;
  await previewTemplate();
}

templateBody.addEventListener('input', queuePreview);
templateFormat.addEventListener('change', queuePreview);
document.querySelectorAll<HTMLButtonElement>('[data-template-variable]').forEach((button) => {
  button.addEventListener('click', () => {
    const variable = `{${button.dataset.templateVariable}}`;
    templateBody.setRangeText(variable, templateBody.selectionStart, templateBody.selectionEnd, 'end');
    templateBody.focus();
    queuePreview();
  });
});
document.querySelector('#template-reset')!.addEventListener('click', () => {
  void run(async () => {
    const path = subscriptionPath();
    await call(`${path}/template`, 'DELETE');
    templateBody.value = templateDefaults; templateFormat.value = 'text';
    await previewTemplate();
    state.textContent = '기본 템플릿으로 초기화했어요.';
  });
});
templateSave.addEventListener('click', () => {
  void run(async () => {
    const invalid = validateTemplate(templateBody.value);
    templateErrors.textContent = invalid;
    templateBody.setAttribute('aria-invalid', String(Boolean(invalid)));
    if (invalid) return;
    await call(`${subscriptionPath()}/template`, 'PUT', templatePayload());
    await previewTemplate();
    state.textContent = '알림 템플릿을 저장했어요.';
  });
});

function initFromFragment() {
  const hash = location.hash;
  if (!hash) return;
  try {
    history.replaceState(null, '', location.pathname + location.search);
  } catch {
    reset(); input('token').type = 'password';
    state.textContent = '주소에서 관리 정보를 지우지 못했어요. 주소를 직접 지우고 다시 시도해 주세요.';
    return;
  }
  const raw = hash.replace(/^#/, '');
  const params = new URLSearchParams(raw);
  const id = params.get('id')?.trim() ?? '';
  const token = params.get('token')?.trim() ?? '';
  if (params.size === 2 && params.getAll('id').length === 1 && params.getAll('token').length === 1 &&
      /^[A-Za-z0-9_-]{24}$/.test(id) && /^[A-Za-z0-9_-]{43}$/.test(token)) {
    reset(); input('token').type = 'password';
    input('id').value = id; input('token').value = token; void run(load);
  } else {
    reset(); input('token').type = 'password';
    state.textContent = '관리 링크의 형식이 올바르지 않아요.';
  }
}

document.querySelector('#create')!.addEventListener('submit', (event) => {
  event.preventDefault();
  void run(async () => {
    const result = await call('', 'POST', { school: input('school').value.trim(), grade: Number(input('grade').value), class: Number(input('classroom').value), destination: input('destination').value }, false);
    input('destination').value = ''; input('id').value = result.id; input('token').value = result.token; input('token').type = 'text';
    state.textContent = '구독을 만들었어요. 관리 링크 복사 버튼을 누르거나 아래 ID와 관리 토큰을 안전한 곳에 보관하세요. 관리 링크나 토큰을 공유하거나 북마크하면 관리 권한이 노출될 수 있어요. 토큰은 다시 표시되지 않아요.';
  });
});
document.querySelector('#connect')!.addEventListener('submit', (event) => { event.preventDefault(); input('token').type = 'password'; void run(load); });
document.querySelector('#copy-link')?.addEventListener('click', () => { void run(copyLink); });
for (const id of ['id', 'token']) input(id).addEventListener('input', () => { manage.hidden = true; table.replaceChildren(); clearRotation(); });
document.querySelector('#prepare-rotation')!.addEventListener('click', () => {
  try {
    subscriptionPath();
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    rotationToken = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    input('rotation-link').value = `${location.origin}${location.pathname}#id=${input('id').value.trim()}&token=${rotationToken}`;
    input('rotation-saved').checked = false;
    document.querySelector<HTMLElement>('#rotation')!.hidden = false;
    state.textContent = '새 링크를 안전하게 보관한 다음 교체하세요.';
  } catch { state.textContent = '새 관리 링크를 준비하지 못했어요.'; }
});
document.querySelector('#copy-rotation')!.addEventListener('click', () => { void run(async () => {
  await navigator.clipboard.writeText(input('rotation-link').value);
  state.textContent = '새 링크를 복사했어요. 다른 사람과 공유하지 마세요.';
}); });
document.querySelector('#rotate-token')!.addEventListener('click', () => {
  if (!rotationToken || !input('rotation-saved').checked) { state.textContent = '새 링크를 먼저 안전하게 보관해 주세요.'; return; }
  if (!window.confirm('기존 관리 링크가 작동하지 않게 됩니다. 교체할까요?')) return;
  void run(async () => {
    const newToken = rotationToken;
    const active = controller;
    const originalId = input('id').value;
    const originalToken = input('token').value;
    try {
      const result = await call(`${subscriptionPath()}/rotate`, 'POST', { newToken });
      if (active.signal.aborted) return;
      if (result?.rotated !== true) throw new Error('invalid rotation response');
      if (input('id').value !== originalId || input('token').value !== originalToken) {
        state.textContent = '이전 구독의 관리 링크가 교체됐어요. 보관한 새 링크를 사용해 주세요.';
        return;
      }
      input('token').value = newToken; input('token').type = 'password'; clearRotation();
      state.textContent = '관리 링크를 교체했어요. 이전 링크는 작동하지 않습니다.';
    } catch {
      if (!active.signal.aborted) state.textContent = '교체 결과를 확인하지 못했어요. 보관한 새 링크와 기존 링크로 각각 확인해 주세요.';
    }
  });
});
document.querySelector('#filters')!.addEventListener('submit', (event) => {
  event.preventDefault(); void run(async () => {
    const filters: Record<string, unknown> = {};
    for (const key of ['subject', 'teacher']) if (input(key).value.trim()) filters[key] = input(key).value.trim();
    if (select('weekday').value) filters.weekday = Number(select('weekday').value);
    if (input('period').value) filters.period = Number(input('period').value);
    if (select('kind').value) filters.type = select('kind').value;
    const start = input('quiet-start').value, end = input('quiet-end').value;
    if (start || end) { if (!start || !end || start === end) throw new Error('방해 금지 시작과 종료를 서로 다르게 입력해 주세요.'); filters.quietHours = { start, end }; }
    await call(subscriptionPath(), 'PUT', { filters }); state.textContent = '알림 조건을 저장했어요.';
  });
});
document.querySelector('#test')!.addEventListener('click', () => { void run(async () => { const path = subscriptionPath(); await call(`${path}/test`, 'POST'); await loadDeliveries(path); state.textContent = '테스트 알림을 대기열에 넣었어요. 전송 상태를 확인해 주세요.'; }); });
document.querySelector('#refresh')!.addEventListener('click', () => { void run(async () => { await loadDeliveries(subscriptionPath()); state.textContent = '전송 상태를 새로 불러왔어요.'; }); });
document.querySelector('#delete')!.addEventListener('click', () => { if (!window.confirm('이 구독과 대기 중인 알림을 삭제할까요?')) return; void run(async () => { await call(subscriptionPath(), 'DELETE'); reset(); state.textContent = '구독을 삭제했어요.'; }); });
document.querySelector('#lock')!.addEventListener('click', () => { reset(); input('token').type = 'password'; state.textContent = '관리 정보를 지웠어요.'; });

window.addEventListener('hashchange', initFromFragment);
initFromFragment();
