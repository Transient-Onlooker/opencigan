import './admin.css';
import './standalone-theme';

interface AccessLogItem {
  id: number;
  timestamp: string;
  client_ip: string;
  method: string;
  route: string;
  school_id: string | null;
  grade: string | null;
  class_nm: string | null;
  week: string | null;
  dates: string | null;
  datatype: string | null;
  status: number;
  duration_ms: number;
  cache_status: string | null;
  referrer_origin: string;
  origin_class: 'frontend' | 'external' | 'unknown';
  user_agent?: string | null;
}

interface QueryResponse {
  items: AccessLogItem[];
  next_cursor: string | null;
  limit: number;
  has_more: boolean;
  dropped?: number;
}

const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');

const form = document.querySelector<HTMLFormElement>('#filter-form')!;
const tokenInput = document.querySelector<HTMLInputElement>('#token')!;
const clientIpInput = document.querySelector<HTMLInputElement>('#filter-client-ip')!;
const schoolIdInput = document.querySelector<HTMLInputElement>('#filter-school-id')!;
const gradeInput = document.querySelector<HTMLInputElement>('#filter-grade')!;
const classInput = document.querySelector<HTMLInputElement>('#filter-class')!;
const startDayInput = document.querySelector<HTMLInputElement>('#filter-start-day')!;
const endDayInput = document.querySelector<HTMLInputElement>('#filter-end-day')!;
const routeInput = document.querySelector<HTMLInputElement>('#filter-route')!;
const statusInput = document.querySelector<HTMLInputElement>('#filter-status')!;
const originClassSelect = document.querySelector<HTMLSelectElement>('#filter-origin-class')!;
const cacheStatusSelect = document.querySelector<HTMLSelectElement>('#filter-cache-status')!;
const limitInput = document.querySelector<HTMLInputElement>('#filter-limit')!;

const searchBtn = document.querySelector<HTMLButtonElement>('#search-btn')!;
const csvBtn = document.querySelector<HTMLButtonElement>('#csv-btn')!;
const lockBtn = document.querySelector<HTMLButtonElement>('#lock-btn')!;
const nextBtn = document.querySelector<HTMLButtonElement>('#next-btn')!;

const stateEl = document.querySelector<HTMLParagraphElement>('#state')!;
const resultsSection = document.querySelector<HTMLElement>('#results')!;
const logsBody = document.querySelector<HTMLTableSectionElement>('#logs-body')!;
const pageInfo = document.querySelector<HTMLSpanElement>('#page-info')!;
const anomalySection = document.querySelector<HTMLElement>('#anomaly-review')!;
const anomalyForm = document.querySelector<HTMLFormElement>('#anomaly-form')!;
const anomalyState = document.querySelector<HTMLElement>('#anomaly-state')!;
const anomalyResults = document.querySelector<HTMLElement>('#anomaly-results')!;
const anomalySubmit = document.querySelector<HTMLButtonElement>('#anomaly-submit')!;
let anomalyController: AbortController | undefined;
anomalySection.hidden = import.meta.env.VITE_ACCESS_ANOMALIES_ENABLED !== '1';

let activeAbortController: AbortController | undefined;
let nextCursor: string | null = null;
let currentLoadedCount = 0;

function clearAnomalies() {
  anomalyController?.abort();
  anomalyController = undefined;
  anomalySubmit.disabled = false;
  anomalyResults.replaceChildren();
  anomalyState.textContent = '';
}

tokenInput.addEventListener('input', clearAnomalies);
anomalyForm.addEventListener('submit', (event) => {
  event.preventDefault();
  clearAnomalies();
  const token = tokenInput.value;
  if (!token.trim()) { anomalyState.textContent = '관리자 토큰을 입력해 주세요.'; return; }
  if (!base && location.hostname.endsWith('.github.io')) { anomalyState.textContent = 'API가 연결된 배포 주소에서 이용해 주세요.'; return; }
  const params = new URLSearchParams({
    window_hours: document.querySelector<HTMLInputElement>('#anomaly-window')!.value,
    max_requests_per_ip: document.querySelector<HTMLInputElement>('#anomaly-volume')!.value,
    max_error_ratio: document.querySelector<HTMLInputElement>('#anomaly-ratio')!.value,
    max_distinct_schools: document.querySelector<HTMLInputElement>('#anomaly-schools')!.value,
    min_requests: document.querySelector<HTMLInputElement>('#anomaly-minimum')!.value,
  });
  const statusLimit = document.querySelector<HTMLInputElement>('#anomaly-status-limit')!.value;
  if (statusLimit) params.set('max_status_errors', statusLimit);
  const controller = new AbortController();
  anomalyController = controller;
  anomalySubmit.disabled = true;
  anomalyState.textContent = '검토 중…';
  void (async () => {
    try {
      const response = await fetch(`${base}/api/v1/admin/access-anomalies?${params}`, {
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
      });
      if (!response.ok) throw new Error(response.status === 401 ? '관리자 토큰을 확인해 주세요.' : response.status === 429 ? '요청이 많아요. 잠시 후 다시 시도해 주세요.' : response.status === 404 || response.status === 503 ? '이상 조회 검토를 사용할 수 없습니다.' : `검토에 실패했습니다. (${response.status})`);
      const data = await response.json();
      if (controller.signal.aborted || anomalyController !== controller || tokenInput.value !== token) return;
      if (!Array.isArray(data.findings)) throw new Error('서버의 검토 응답이 올바르지 않습니다.');
      for (const item of data.findings) {
        if (!item || typeof item.client_ip !== 'string' || typeof item.kind !== 'string' || typeof item.observed !== 'number' || typeof item.threshold !== 'number') throw new Error('서버의 검토 응답이 올바르지 않습니다.');
        const row = document.createElement('li');
        row.textContent = `${item.client_ip} · ${item.kind}${typeof item.status_group === 'string' ? ` (${item.status_group})` : ''} · ${item.observed} / 기준 ${item.threshold}`;
        anomalyResults.append(row);
      }
      anomalyState.textContent = data.findings.length ? `${data.findings.length}건의 검토 신호` : '기준을 초과한 검토 신호가 없습니다.';
    } catch (error) {
      if (!controller.signal.aborted) { anomalyResults.replaceChildren(); anomalyState.textContent = error instanceof Error ? error.message : '검토에 실패했습니다.'; }
    } finally {
      if (anomalyController === controller) { anomalyController = undefined; anomalySubmit.disabled = false; }
    }
  })();
});

function formatKst(isoString: string): string {
  if (!isoString) return '';
  return isoString.replace('T', ' ').replace(/\+09:00$/, '');
}

function buildFilterParams(includePagination: boolean = true): URLSearchParams {
  const params = new URLSearchParams();

  const clientIp = clientIpInput.value.trim();
  if (clientIp) params.set('client_ip', clientIp);

  const schoolId = schoolIdInput.value.trim();
  if (schoolId) params.set('school_id', schoolId);

  const grade = gradeInput.value.trim();
  if (grade) params.set('grade', grade);

  const cls = classInput.value.trim();
  if (cls) params.set('class', cls);

  const startDay = startDayInput.value.trim();
  if (startDay) params.set('start_day', startDay);

  const endDay = endDayInput.value.trim();
  if (endDay) params.set('end_day', endDay);

  const route = routeInput.value.trim();
  if (route) params.set('route', route);

  const status = statusInput.value.trim();
  if (status) params.set('status', status);

  const originClass = originClassSelect.value.trim();
  if (originClass) params.set('origin_class', originClass);

  const cacheStatus = cacheStatusSelect.value.trim();
  if (cacheStatus) params.set('cache_status', cacheStatus);

  if (includePagination) {
    const limit = limitInput.value.trim();
    if (limit) params.set('limit', limit);
  }

  return params;
}

function renderRows(items: AccessLogItem[], append: boolean) {
  if (!append) {
    logsBody.replaceChildren();
  }

  for (const item of items) {
    const row = document.createElement('tr');

    const fields: (string | number)[] = [
      formatKst(item.timestamp),
      item.client_ip || '',
      item.method || '',
      item.route || '',
      item.school_id ?? '-',
      item.grade ?? '-',
      item.class_nm ?? '-',
      item.week ?? '-',
      item.dates ?? '-',
      item.datatype ?? '-',
      item.status,
      `${item.duration_ms} ms`,
      item.cache_status ?? '-',
      item.referrer_origin || '-',
      item.origin_class || '-',
      item.user_agent || '-',
    ];

    for (const val of fields) {
      const cell = document.createElement('td');
      cell.textContent = String(val);
      row.append(cell);
    }

    logsBody.append(row);
  }
}

async function loadLogs(cursor: string | null = null) {
  const isAppend = Boolean(cursor);
  activeAbortController?.abort();
  const controller = new AbortController();
  activeAbortController = controller;

  searchBtn.disabled = true;
  csvBtn.disabled = true;
  if (nextBtn) nextBtn.disabled = true;

  if (!isAppend) {
    resultsSection.hidden = true;
    logsBody.replaceChildren();
    currentLoadedCount = 0;
  }
  stateEl.textContent = isAppend ? '추가 로그를 불러오는 중…' : '접속 로그를 불러오는 중…';

  try {
    if (!base && location.hostname.endsWith('.github.io')) {
      throw new Error('API가 연결된 배포 주소에서 이용해 주세요.');
    }

    const token = tokenInput.value;
    if (!token.trim()) {
      throw new Error('관리자 토큰을 입력해 주세요.');
    }

    const params = buildFilterParams(true);
    if (cursor) {
      params.set('cursor', cursor);
    }

    const response = await fetch(`${base}/api/v1/admin/access-logs?${params.toString()}`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
      },
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
    });

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('관리자 토큰을 확인해 주세요.');
      } else if (response.status === 503) {
        throw new Error('접속 로그 저장소가 비활성화되어 있거나 상태를 확인해 주세요.');
      } else if (response.status === 400) {
        throw new Error('입력한 조회 조건이 올바르지 않습니다.');
      } else {
        throw new Error(`조회에 실패했습니다. (${response.status})`);
      }
    }

    const data: QueryResponse = await response.json();
    if (controller.signal.aborted) return;

    renderRows(data.items, isAppend);
    currentLoadedCount += data.items.length;
    nextCursor = data.next_cursor;

    resultsSection.hidden = false;
    pageInfo.textContent = `현재 ${currentLoadedCount.toLocaleString('ko-KR')}건 표시 중${data.dropped ? ` (유실: ${data.dropped}건)` : ''}`;

    if (data.has_more && data.next_cursor) {
      nextBtn.hidden = false;
      nextBtn.disabled = false;
    } else {
      nextBtn.hidden = true;
    }

    stateEl.textContent = data.items.length > 0 || currentLoadedCount > 0
      ? `조회 완료 · ${new Date().toLocaleTimeString('ko-KR')}`
      : '조건에 해당하는 접속 로그가 없습니다.';
  } catch (error) {
    if (!controller.signal.aborted) {
      stateEl.textContent = error instanceof Error ? error.message : '접속 로그를 불러오지 못했습니다.';
    }
  } finally {
    if (activeAbortController === controller) {
      searchBtn.disabled = false;
      csvBtn.disabled = false;
      if (nextBtn && nextCursor) nextBtn.disabled = false;
    }
  }
}

async function downloadCsv() {
  activeAbortController?.abort();
  const controller = new AbortController();
  activeAbortController = controller;

  searchBtn.disabled = true;
  csvBtn.disabled = true;
  stateEl.textContent = 'CSV 파일을 생성하여 다운로드하는 중…';

  try {
    if (!base && location.hostname.endsWith('.github.io')) {
      throw new Error('API가 연결된 배포 주소에서 이용해 주세요.');
    }

    const token = tokenInput.value;
    if (!token.trim()) {
      throw new Error('관리자 토큰을 입력해 주세요.');
    }

    const params = buildFilterParams(false);
    params.set('format', 'csv');

    const response = await fetch(`${base}/api/v1/admin/access-logs?${params.toString()}`, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'text/csv, application/json',
      },
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
    });

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('관리자 토큰을 확인해 주세요.');
      } else if (response.status === 503) {
        throw new Error('접속 로그 저장소가 비활성화되어 있거나 상태를 확인해 주세요.');
      } else if (response.status === 400) {
        throw new Error('입력한 조회 조건이 올바르지 않습니다.');
      } else {
        throw new Error(`CSV 다운로드에 실패했습니다. (${response.status})`);
      }
    }

    const blob = await response.blob();
    if (controller.signal.aborted) return;

    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'opencigan-access.csv';
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);

    stateEl.textContent = `CSV 다운로드 완료 · ${new Date().toLocaleTimeString('ko-KR')}`;
  } catch (error) {
    if (!controller.signal.aborted) {
      stateEl.textContent = error instanceof Error ? error.message : 'CSV 다운로드에 실패했습니다.';
    }
  } finally {
    if (activeAbortController === controller) {
      searchBtn.disabled = false;
      csvBtn.disabled = false;
    }
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  loadLogs(null);
});

csvBtn.addEventListener('click', () => {
  downloadCsv();
});

nextBtn.addEventListener('click', () => {
  if (nextCursor) {
    loadLogs(nextCursor);
  }
});

lockBtn.addEventListener('click', () => {
  clearAnomalies();
  activeAbortController?.abort();
  activeAbortController = undefined;
  searchBtn.disabled = false;
  csvBtn.disabled = false;
  nextBtn.hidden = true;
  nextCursor = null;
  currentLoadedCount = 0;

  tokenInput.value = '';
  resultsSection.hidden = true;
  logsBody.replaceChildren();
  pageInfo.textContent = '';

  stateEl.textContent = '잠겼습니다. 다시 조회하려면 토큰을 입력하세요.';
  tokenInput.focus();
});

