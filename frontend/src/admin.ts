import './admin.css';
import './standalone-theme';

interface Summary {
  visitors: number; sessions: number; pageViews: number; apiRequests: number;
  apiErrorRate: number; apiAverageMs: number; droppedApiEvents: number;
  cacheStatuses?: Record<string, number>; failureKinds?: Record<string, number>;
  refreshObservations?: Record<string, { result: 'success' | 'failure' | 'not_cached'; observedAt: string }>;
  apiHourly?: { hour: string; requests: number; errors: number; upstream_errors: number; overload_errors: number; cache_hits: number; stale_responses: number }[];
  daily: { day: string; visitors: number; sessions: number; page_views: number; api_requests: number }[];
  routes: { route: string; requests: number; errors: number; avg_ms: number; data_failures?: number; overload_errors?: number; unclassified_server_errors?: number }[];
}

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
const token = document.querySelector<HTMLInputElement>('#token')!;
const days = document.querySelector<HTMLSelectElement>('#days')!;
const button = document.querySelector<HTMLButtonElement>('#load')!;
const state = document.querySelector<HTMLParagraphElement>('#state')!;
const results = document.querySelector<HTMLElement>('#results')!;
const hourlyState = document.querySelector<HTMLElement>('#hourly-state')!;
const hourlyTable = document.querySelector<HTMLElement>('#hourly-table')!;
const refreshState = document.querySelector<HTMLElement>('#refresh-state')!;
const refreshTable = document.querySelector<HTMLElement>('#refresh-table')!;
let request: AbortController | undefined;

function rows(selector: string, values: (string | number)[][]) {
  const body = document.querySelector(selector)!;
  body.replaceChildren();
  for (const valuesRow of values) {
    const row = document.createElement('tr');
    for (const value of valuesRow) {
      const cell = document.createElement('td');
      cell.textContent = String(value);
      row.append(cell);
    }
    body.append(row);
  }
}

document.querySelector('#login')!.addEventListener('submit', async (event) => {
  event.preventDefault();
  request?.abort();
  const controller = new AbortController(); request = controller;
  button.disabled = true; results.hidden = true; state.textContent = '통계를 불러오는 중…';
  try {
    if (!base && location.hostname.endsWith('.github.io')) throw new Error('API가 연결된 배포 주소에서 이용해 주세요.');
    const response = await fetch(`${base}/api/v1/admin/analytics?days=${days.value}`, {
      headers: { Authorization: `Bearer ${token.value}`, Accept: 'application/json' },
      credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
    });
    if (!response.ok) throw new Error(response.status === 401 ? '관리자 토큰을 확인해 주세요.' : response.status === 503 ? '서버의 통계 설정이나 저장소 상태를 확인해 주세요.' : `조회에 실패했습니다. (${response.status})`);
    const data: Summary = await response.json();
    if (controller.signal.aborted) return;
    const metrics = document.querySelector('#metrics')!;
    metrics.replaceChildren();
    const cache = data.cacheStatuses;
    const cacheTotal = (cache?.hit ?? 0) + (cache?.miss ?? 0) + (cache?.stale ?? 0);
    const cards: [string, string | number][] = [
      ['방문 브라우저', data.visitors], ['세션', data.sessions], ['페이지 조회', data.pageViews],
      ['API 요청', data.apiRequests], ['API 오류율', `${(data.apiErrorRate * 100).toFixed(2)}%`],
      ['평균 처리 시간', `${data.apiAverageMs} ms`], ['이 프로세스의 누락 이벤트', data.droppedApiEvents],
      ['시간표 캐시 적중률', cacheTotal ? `${((cache?.hit ?? 0) / cacheTotal * 100).toFixed(1)}%` : '기록 없음'],
      ['시간표 캐시 적중', cache?.hit ?? 0], ['시간표 캐시 미스', cache?.miss ?? 0], ['이전 캐시 반환', cache?.stale ?? 0],
      ['데이터 조회 실패', data.failureKinds?.upstream_unavailable ?? 0], ['과부하 차단', data.failureKinds?.service_overloaded ?? 0],
    ];
    for (const [label, value] of cards) {
      const card = document.createElement('div');
      const heading = document.createElement('span'); heading.textContent = label;
      const number = document.createElement('strong'); number.textContent = typeof value === 'number' ? value.toLocaleString('ko-KR') : value;
      card.append(heading, number); metrics.append(card);
    }
    rows('#daily', data.daily.map((d) => [d.day, d.visitors, d.sessions, d.page_views, d.api_requests]));
    rows('#routes', data.routes.map((r) => [r.route, r.requests, r.errors, r.data_failures ?? '—', r.overload_errors ?? '—', r.unclassified_server_errors ?? '—', r.avg_ms]));
    const observations = data.refreshObservations;
    const resourceLabels = [['school_search', '시간표 학교 검색'], ['timetable', '시간표'], ['neis_school_search', '급식 학교 검색'], ['meals', '급식']];
    rows('#refresh-observations', observations ? resourceLabels.map(([key, label]) => {
      const entry = observations[key];
      return [label, entry ? entry.result === 'success' ? '성공' : entry.result === 'not_cached' ? '응답 수신 · 캐시 저장 불가' : '실패' : '아직 관측 없음', entry ? new Date(entry.observedAt).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '—'];
    }) : []);
    refreshTable.hidden = !observations;
    refreshState.textContent = observations ? '' : '현재 서버에서는 갱신 관측을 제공하지 않습니다.';
    const hourly = data.apiHourly;
    rows('#hourly', (hourly ?? []).map((h) => [h.hour.slice(0, 16).replace('T', ' '), h.requests, h.errors, h.upstream_errors, h.overload_errors, h.cache_hits, h.stale_responses]));
    hourlyTable.hidden = !hourly?.length;
    hourlyState.textContent = !hourly ? '현재 서버에서는 시간대별 통계를 제공하지 않습니다.' : hourly.length ? '' : '최근 24시간에 기록된 API 요청이 없습니다.';
    results.hidden = false;
    state.textContent = data.pageViews || data.apiRequests ? `조회 완료 · ${new Date().toLocaleTimeString('ko-KR')}` : '선택한 기간에 수집된 이용 기록이 없습니다.';
  } catch (error) {
    if (!controller.signal.aborted) state.textContent = error instanceof Error ? error.message : '통계를 불러오지 못했습니다.';
  } finally {
    if (request === controller) button.disabled = false;
  }
});

document.querySelector('#clear')!.addEventListener('click', () => {
  request?.abort(); request = undefined; button.disabled = false;
  token.value = ''; results.hidden = true;
  document.querySelector('#metrics')!.replaceChildren(); rows('#daily', []); rows('#routes', []); rows('#hourly', []);
  hourlyTable.hidden = true; hourlyState.textContent = '';
  rows('#refresh-observations', []); refreshTable.hidden = true; refreshState.textContent = '';
  state.textContent = '잠겼습니다. 다시 조회하려면 토큰을 입력하세요.'; token.focus();
});
