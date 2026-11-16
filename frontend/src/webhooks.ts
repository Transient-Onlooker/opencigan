import './admin.css';
import './standalone-theme';

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const input = (id: string) => document.querySelector<HTMLInputElement>(`#${id}`)!;
const select = (id: string) => document.querySelector<HTMLSelectElement>(`#${id}`)!;
const state = document.querySelector<HTMLElement>('#state')!;
const manage = document.querySelector<HTMLElement>('#manage')!;
const table = document.querySelector<HTMLElement>('#deliveries')!;
const buttons = [...document.querySelectorAll<HTMLButtonElement>('button')];
let controller = new AbortController();

async function call(path: string, method = 'GET', payload?: unknown, authenticated = true) {
  if (!base && (location.hostname.endsWith('.github.io') || location.hostname === 'opencigan.mcv.kr')) throw new Error('API가 연결된 배포 주소에서 이용해 주세요.');
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
  input('id').value = ''; input('token').value = ''; input('destination').value = '';
  manage.hidden = true; table.replaceChildren();
  document.querySelector<HTMLFormElement>('#filters')!.reset(); document.querySelector('#scope')!.textContent = '';
  buttons.forEach((button) => { button.disabled = false; });
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
    table.append(row);
  }
}

async function load() {
  manage.hidden = true; table.replaceChildren();
  const path = subscriptionPath();
  const result = await call(path);
  const f = result.filters ?? {};
  input('subject').value = f.subject ?? ''; input('teacher').value = f.teacher ?? '';
  select('weekday').value = String(f.weekday ?? ''); input('period').value = String(f.period ?? ''); select('kind').value = f.type ?? '';
  input('quiet-start').value = f.quietHours?.start ?? ''; input('quiet-end').value = f.quietHours?.end ?? '';
  document.querySelector('#scope')!.textContent = `${result.school} · ${result.grade}학년 ${result.classroom}반 · ${result.provider} · 누락 ${result.dropped_events}건`;
  await loadDeliveries(path); manage.hidden = false;
  state.textContent = '구독 정보를 불러왔어요.';
}

document.querySelector('#create')!.addEventListener('submit', (event) => {
  event.preventDefault();
  void run(async () => {
    const result = await call('', 'POST', { school: input('school').value.trim(), grade: Number(input('grade').value), class: Number(input('classroom').value), destination: input('destination').value }, false);
    input('destination').value = ''; input('id').value = result.id; input('token').value = result.token; input('token').type = 'text';
    state.textContent = '구독을 만들었어요. 아래 ID와 관리 토큰을 안전한 곳에 따로 저장하세요. 토큰은 다시 표시되지 않아요.';
  });
});
document.querySelector('#connect')!.addEventListener('submit', (event) => { event.preventDefault(); input('token').type = 'password'; void run(load); });
for (const id of ['id', 'token']) input(id).addEventListener('input', () => { manage.hidden = true; table.replaceChildren(); });
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
