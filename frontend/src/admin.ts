import './admin.css';
import './standalone-theme';

interface Summary {
  visitors: number; sessions: number; pageViews: number; apiRequests: number;
  apiErrorRate: number; apiAverageMs: number; droppedApiEvents: number;
  cacheStatuses?: Record<string, number>; failureKinds?: Record<string, number>;
  refreshObservations?: Record<string, { result: 'success' | 'failure' | 'not_cached'; observedAt: string; lastSuccessAt?: string; lastFailureAt?: string; durationMs?: number; origin?: 'timetable' | 'calendar' | null }>;
  cacheWaitObservations?: Record<string, { waitMs: number; observedAt: string }>;
  apiHourly?: { hour: string; requests: number; errors: number; upstream_errors: number; overload_errors: number; cache_hits: number; stale_responses: number }[];
  daily: { day: string; visitors: number; sessions: number; page_views: number; api_requests: number }[];
  routes: { route: string; requests: number; errors: number; avg_ms: number; data_failures?: number; overload_errors?: number; unclassified_server_errors?: number }[];
}

interface HistoryStatsResponse {
  observed: boolean;
  totalChanges: number | null;
  byType?: { added: number; changed: number; deleted: number } | null;
  affectedClasses?: number | null;
  lastObservedAt?: string | null;
  retainedSince?: string | null;
  comparisonCoverage?: string | null;
  changesByObservedDay?: { date: string; count: number }[] | null;
  subjectPeriods?: { subject: string; classPeriods: number }[] | null;
  teacherOverlaps?: { date: string; period: number; teacher: string; classes: { grade: number; class: number }[] }[] | null;
  sourceUpdateObservations?: { distinctTimestamps: number; intervalCount: number; meanIntervalSeconds: number | null; firstSourceAt: string; lastSourceAt: string } | null;
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

const historyStatsEnabled = import.meta.env.VITE_HISTORY_STATS_ENABLED === '1';
const historySection = document.querySelector<HTMLElement>('#history-stats-section');
const historyForm = document.querySelector<HTMLFormElement>('#history-stats-form');
const historySchool = document.querySelector<HTMLInputElement>('#history-school');
const historyWeek = document.querySelector<HTMLInputElement>('#history-week');
const historyButton = document.querySelector<HTMLButtonElement>('#history-stats-load');
const historyState = document.querySelector<HTMLElement>('#history-stats-state');
const historyResults = document.querySelector<HTMLElement>('#history-stats-results');
let historyRequest: AbortController | undefined;

if (historySection && historyStatsEnabled) {
  historySection.hidden = false;
}

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
      const wait = data.cacheWaitObservations?.[key];
      return [label, entry?.origin === 'timetable' ? '시간표 조회' : entry?.origin === 'calendar' ? '캘린더 구독' : '—', entry ? entry.result === 'success' ? '성공' : entry.result === 'not_cached' ? '응답 수신 · 캐시 저장 불가' : '실패' : '아직 관측 없음', entry ? new Date(entry.observedAt).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '—', entry?.lastSuccessAt ? new Date(entry.lastSuccessAt).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '—', entry?.lastFailureAt ? new Date(entry.lastFailureAt).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '—', typeof entry?.durationMs === 'number' ? `${entry.durationMs.toLocaleString('ko-KR')} ms` : '—', typeof wait?.waitMs === 'number' ? `${wait.waitMs.toLocaleString('ko-KR')} ms` : '—', wait?.observedAt ? new Date(wait.observedAt).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '—'];
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
  historyRequest?.abort(); historyRequest = undefined;
  if (historyButton) historyButton.disabled = false;
  if (historyResults) { historyResults.hidden = true; historyResults.replaceChildren(); }
  if (historyState) historyState.textContent = '';
  token.value = ''; results.hidden = true;
  document.querySelector('#metrics')!.replaceChildren(); rows('#daily', []); rows('#routes', []); rows('#hourly', []);
  hourlyTable.hidden = true; hourlyState.textContent = '';
  rows('#refresh-observations', []); refreshTable.hidden = true; refreshState.textContent = '';
  state.textContent = '잠겼습니다. 다시 조회하려면 토큰을 입력하세요.'; token.focus();
});

if (historyStatsEnabled && historyForm && historySchool && historyWeek && historyButton && historyState && historyResults) {
  historyForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const adminToken = token.value.trim();
    if (!adminToken) {
      historyState.textContent = '상단의 관리자 토큰을 먼저 입력해 주세요.';
      token.focus();
      return;
    }
    const school = historySchool.value.trim();
    const week = historyWeek.value.trim();
    if (!school) {
      historyState.textContent = '학교 ID를 입력해 주세요.';
      historySchool.focus();
      return;
    }
    if (!week) {
      historyState.textContent = '주 시작일을 입력해 주세요.';
      historyWeek.focus();
      return;
    }
    historyRequest?.abort();
    const controller = new AbortController();
    historyRequest = controller;
    historyButton.disabled = true;
    historyResults.hidden = true;
    historyResults.replaceChildren();
    historyState.textContent = '이력 통계를 불러오는 중…';

    try {
      if (!base && location.hostname.endsWith('.github.io')) throw new Error('API가 연결된 배포 주소에서 이용해 주세요.');
      const query = new URLSearchParams({ school, week }).toString();
      const response = await fetch(`${base}/api/v1/admin/history-stats?${query}`, {
        headers: { Authorization: `Bearer ${adminToken}`, Accept: 'application/json' },
        credentials: 'omit',
        cache: 'no-store',
        referrerPolicy: 'no-referrer',
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10_000)]),
      });
      if (!response.ok) {
        throw new Error(
          response.status === 401
            ? '관리자 토큰을 확인해 주세요.'
            : response.status === 400
            ? '조회 조건이 올바르지 않습니다. 학교 ID 및 월요일 날짜(YYYY-MM-DD)를 확인해 주세요.'
            : response.status === 503
            ? '서버의 이력 통계 설정이나 저장소 상태를 확인해 주세요.'
            : `조회에 실패했습니다. (${response.status})`
        );
      }
      const data: HistoryStatsResponse = await response.json();
      if (controller.signal.aborted) return;

      historyResults.replaceChildren();
      if (!data.observed) {
        const unobservedCard = document.createElement('div');
        const noticeHeading = document.createElement('strong');
        noticeHeading.textContent = '미관측 (유효한 최근 관측 기록 없음)';
        const noticeDesc = document.createElement('p');
        noticeDesc.textContent = '선택한 학교 및 주차에 대한 최근 30일 이내 관측 기록이 존재하지 않거나 보존 기한이 만료되었습니다.';
        unobservedCard.append(noticeHeading, noticeDesc);
        if (data.retainedSince) {
          const limitInfo = document.createElement('p');
          limitInfo.textContent = `30일 보존 한계: ${new Date(data.retainedSince).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })} 이후 기록만 반영`;
          unobservedCard.append(limitInfo);
        }
        historyResults.append(unobservedCard);
        historyResults.hidden = false;
        historyState.textContent = '조회 완료 (미관측)';
      } else {
        const metricsContainer = document.createElement('div');
        metricsContainer.className = 'metrics';

        if (!Number.isInteger(data.totalChanges) || data.totalChanges === null || data.totalChanges < 0) {
          throw new Error('서버의 통계 응답이 올바르지 않습니다.');
        }
        const total = data.totalChanges;
        const changeCard = document.createElement('div');
        const changeLabel = document.createElement('span');
        changeLabel.textContent = '보존된 관측 변경';
        const changeVal = document.createElement('strong');
        changeVal.textContent = `${total.toLocaleString('ko-KR')}건`;
        changeCard.append(changeLabel, changeVal);
        metricsContainer.append(changeCard);

        const classCard = document.createElement('div');
        const classLabel = document.createElement('span');
        classLabel.textContent = '영향 학급 수';
        const classVal = document.createElement('strong');
        classVal.textContent = typeof data.affectedClasses === 'number' ? `${data.affectedClasses.toLocaleString('ko-KR')}개 학급` : '—';
        classCard.append(classLabel, classVal);
        metricsContainer.append(classCard);

        if (data.byType) {
          const addedCard = document.createElement('div');
          const addedLabel = document.createElement('span');
          addedLabel.textContent = '추가';
          const addedVal = document.createElement('strong');
          addedVal.textContent = `${(data.byType.added ?? 0).toLocaleString('ko-KR')}건`;
          addedCard.append(addedLabel, addedVal);
          metricsContainer.append(addedCard);

          const modCard = document.createElement('div');
          const modLabel = document.createElement('span');
          modLabel.textContent = '변경';
          const modVal = document.createElement('strong');
          modVal.textContent = `${(data.byType.changed ?? 0).toLocaleString('ko-KR')}건`;
          modCard.append(modLabel, modVal);
          metricsContainer.append(modCard);

          const delCard = document.createElement('div');
          const delLabel = document.createElement('span');
          delLabel.textContent = '삭제';
          const delVal = document.createElement('strong');
          delVal.textContent = `${(data.byType.deleted ?? 0).toLocaleString('ko-KR')}건`;
          delCard.append(delLabel, delVal);
          metricsContainer.append(delCard);
        }

        const infoDiv = document.createElement('div');
        infoDiv.style.marginTop = '12px';

        if (total === 0) {
          const zeroNotice = document.createElement('p');
          zeroNotice.textContent = '저장된 변경 기록 0건 · 비교 횟수와 관측 공백은 알 수 없음';
          infoDiv.append(zeroNotice);
        }

        if (data.lastObservedAt) {
          const obsP = document.createElement('p');
          obsP.textContent = `마지막 관측 시각 (한국): ${new Date(data.lastObservedAt).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })}`;
          infoDiv.append(obsP);
        }
        if (data.retainedSince) {
          const retainP = document.createElement('p');
          retainP.textContent = `30일 보존 한계: ${new Date(data.retainedSince).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })} 이후 관측된 변경만 포함`;
          infoDiv.append(retainP);
        }
        const noteP = document.createElement('p');
        noteP.textContent = '최근 30일 이내에 저장된 관측 변경만 집계하며 수집 사이 변경이나 보존 기한이 지난 변경은 포함되지 않습니다.';
        infoDiv.append(noteP);

        historyResults.append(metricsContainer, infoDiv);
        if (data.changesByObservedDay != null) {
          if (!Array.isArray(data.changesByObservedDay) || data.changesByObservedDay.some(item =>
            !item || typeof item.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(item.date) || !Number.isInteger(item.count) || item.count < 1)) {
            throw new Error('서버의 관측일별 통계 응답이 올바르지 않습니다.');
          }
          const section = document.createElement('section');
          const heading = document.createElement('h3');
          heading.textContent = '관측일별 변경 (한국 시간)';
          const description = document.createElement('p');
          description.textContent = '변경을 발견한 날짜별 건수입니다. 실제 변경 시각이나 관측하지 못한 변경은 알 수 없습니다.';
          section.append(heading, description);
          if (!data.changesByObservedDay.length) {
            const empty = document.createElement('p');
            empty.textContent = '보존된 관측 변경이 없습니다.';
            section.append(empty);
          } else {
            const list = document.createElement('ul');
            for (const item of data.changesByObservedDay) {
              const row = document.createElement('li');
              row.textContent = `${item.date}: ${item.count.toLocaleString('ko-KR')}건`;
              list.append(row);
            }
            section.append(list);
          }
          historyResults.append(section);
        }
        if (data.subjectPeriods !== undefined && data.subjectPeriods !== null) {
          if (!Array.isArray(data.subjectPeriods) || data.subjectPeriods.some(item => !item || typeof item.subject !== 'string' || !item.subject.trim() || !Number.isInteger(item.classPeriods) || item.classPeriods < 1)) {
            throw new Error('서버의 과목별 통계 응답이 올바르지 않습니다.');
          }
          const section = document.createElement('section');
          const heading = document.createElement('h3');
          heading.textContent = '최근 관측 시간표의 과목별 학급 교시';
          const description = document.createElement('p');
          description.textContent = '학급·날짜·교시별 과목을 한 번씩 집계합니다. 한 교시에 여러 과목이 있으면 각각 포함하며, 제공되지 않은 수업은 포함되지 않습니다.';
          section.append(heading, description);
          if (data.subjectPeriods.length === 0) {
            const empty = document.createElement('p');
            empty.textContent = '관측된 과목이 없습니다.';
            section.append(empty);
          } else {
            const list = document.createElement('ul');
            for (const item of data.subjectPeriods) {
              const row = document.createElement('li');
              row.textContent = `${item.subject}: ${item.classPeriods.toLocaleString('ko-KR')}학급 교시`;
              list.append(row);
            }
            section.append(list);
          }
          historyResults.append(section);
        }
        if (data.sourceUpdateObservations !== undefined) {
          const section = document.createElement('section');
          const heading = document.createElement('h3');
          heading.textContent = '원본 갱신 시각 관측';
          section.append(heading);
          const stats = data.sourceUpdateObservations;
          if (stats === null) {
            const empty = document.createElement('p');
            empty.textContent = '기록된 원본 갱신 시각이 없어 간격을 알 수 없습니다.';
            section.append(empty);
          } else {
            if (!stats || !Number.isInteger(stats.distinctTimestamps) || stats.distinctTimestamps < 1 ||
                !Number.isInteger(stats.intervalCount) || stats.intervalCount !== stats.distinctTimestamps - 1 ||
                (stats.intervalCount === 0 ? stats.meanIntervalSeconds !== null :
                  typeof stats.meanIntervalSeconds !== 'number' || !Number.isFinite(stats.meanIntervalSeconds) || stats.meanIntervalSeconds <= 0) ||
                typeof stats.firstSourceAt !== 'string' || Number.isNaN(Date.parse(stats.firstSourceAt)) ||
                typeof stats.lastSourceAt !== 'string' || Number.isNaN(Date.parse(stats.lastSourceAt))) {
              throw new Error('서버의 원본 갱신 관측 응답이 올바르지 않습니다.');
            }
            const summary = document.createElement('p');
            summary.textContent = stats.meanIntervalSeconds === null
              ? `서로 다른 원본 시각 ${stats.distinctTimestamps}개 · 간격을 계산하려면 2개 이상 필요합니다.`
              : `서로 다른 원본 시각 ${stats.distinctTimestamps}개 · 관측된 시각 사이 평균 ${(stats.meanIntervalSeconds / 3600).toLocaleString('ko-KR', { maximumFractionDigits: 2 })}시간`;
            section.append(summary);
          }
          const note = document.createElement('p');
          note.textContent = '최근 30일에 관측된 원본 표시 시각만 사용합니다. 수집 사이의 갱신이나 원본의 실제 갱신 주기는 알 수 없습니다.';
          section.append(note);
          historyResults.append(section);
        }
        if (data.teacherOverlaps !== undefined && data.teacherOverlaps !== null) {
          if (!Array.isArray(data.teacherOverlaps) || data.teacherOverlaps.some(item =>
            !item || typeof item.teacher !== 'string' || !item.teacher.trim() || typeof item.date !== 'string' ||
            !/^\d{4}-\d{2}-\d{2}$/.test(item.date) || !Number.isInteger(item.period) || item.period < 1 ||
            !Array.isArray(item.classes) || item.classes.length < 2 || item.classes.some(room =>
              !room || !Number.isInteger(room.grade) || room.grade < 1 || !Number.isInteger(room.class) || room.class < 1))) {
            throw new Error('서버의 교사 일정 응답이 올바르지 않습니다.');
          }
          const section = document.createElement('section');
          const heading = document.createElement('h3');
          heading.textContent = '확인이 필요한 교사 일정 겹침';
          const description = document.createElement('p');
          description.textContent = '같은 이름이 같은 날짜·교시에 여러 학급에 표시된 관측입니다. 합반 수업이나 동명이인일 수 있어 실제 충돌로 확정할 수 없습니다.';
          section.append(heading, description);
          if (data.teacherOverlaps.length === 0) {
            const empty = document.createElement('p');
            empty.textContent = '관측된 일정 겹침이 없습니다.';
            section.append(empty);
          } else {
            const list = document.createElement('ul');
            for (const item of data.teacherOverlaps) {
              const row = document.createElement('li');
              const classes = item.classes.map(room => `${room.grade}학년 ${room.class}반`).join(', ');
              row.textContent = `${item.date} ${item.period}교시 · ${item.teacher} · ${classes}`;
              list.append(row);
            }
            section.append(list);
          }
          historyResults.append(section);
        }
        historyResults.hidden = false;
        historyState.textContent = `조회 완료 · ${new Date().toLocaleTimeString('ko-KR')}`;
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        historyState.textContent = error instanceof Error ? error.message : '이력 통계를 불러오지 못했습니다.';
      }
    } finally {
      if (historyRequest === controller) historyButton.disabled = false;
    }
  });
}
