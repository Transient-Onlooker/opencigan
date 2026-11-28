export function mountSchoolUsage(container: HTMLElement, token: string, base: string): () => void {
  let activeToken = token;
  let controller: AbortController | undefined;
  let disposed = false;
  const heading = document.createElement('h2'); heading.textContent = '학교별 조회';
  const note = document.createElement('p'); note.textContent = '보존된 접속 로그의 조회 건수입니다. 시간표와 급식은 서로 다른 학교 식별자를 사용합니다.';
  const form = document.createElement('form');
  const label = document.createElement('label'); label.textContent = '조회 기간';
  const select = document.createElement('select');
  for (const [value, text] of [['', '기본 보존 기간'], ['1', '오늘'], ['3', '최근 3일'], ['7', '최근 7일']]) {
    const option = document.createElement('option'); option.value = value; option.textContent = text; select.append(option);
  }
  label.append(select);
  const button = document.createElement('button'); button.type = 'submit'; button.textContent = '조회'; form.append(label, button);
  const state = document.createElement('p'); state.setAttribute('role', 'status'); state.setAttribute('aria-live', 'polite');
  const results = document.createElement('div'); container.replaceChildren(heading, note, form, state, results);

  async function load() {
    controller?.abort(); controller = new AbortController(); const current = controller;
    const query = new URLSearchParams({ limit: '50' }); if (select.value) query.set('days', select.value);
    state.textContent = '불러오는 중…'; button.disabled = true; results.replaceChildren();
    try {
      const response = await fetch(`${base}/api/v1/admin/school-usage?${query}`, {
        headers: { Authorization: `Bearer ${activeToken}`, Accept: 'application/json' },
        credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
        signal: AbortSignal.any([current.signal, AbortSignal.timeout(10_000)]),
      });
      if (!response.ok) {
        let code = '';
        try { code = (await response.json()).code ?? ''; } catch { /* Keep the status-based message for non-JSON errors. */ }
        const message = response.status === 400 ? '선택한 기간이 로그 보존 기간을 초과합니다.'
          : response.status === 401 ? '관리자 토큰을 확인해 주세요.'
          : response.status === 429 ? '요청이 많아요. 잠시 후 다시 시도해 주세요.'
          : code === 'access_logs_disabled' ? '학교별 조회 통계가 이 배포에서 비활성화되어 있습니다.'
          : code === 'access_logs_unavailable' ? '학교별 조회 통계 저장소에 연결할 수 없습니다.'
          : '학교별 조회 통계를 사용할 수 없습니다.';
        throw new Error(message);
      }
      const data = await response.json();
      if (!Array.isArray(data.items)) throw new Error('통계 응답을 확인하지 못했습니다.');
      if (disposed || current.signal.aborted || controller !== current) return;
      if (!query.has('days') && Number.isInteger(data.period_days) && data.period_days > 0) {
        for (const option of Array.from(select.options)) {
          if (option.value && Number(option.value) > data.period_days) option.remove();
        }
      }
      state.textContent = `${data.start_day} ~ ${data.end_day} · ${data.items.length}개 항목${data.has_more ? ' (상위 50개)' : ''}`;
      if (!data.items.length) { results.textContent = '조회 기록이 없습니다.'; return; }
      const table = document.createElement('table');
      const header = document.createElement('tr');
      for (const text of ['자료', '학교', '식별자', '조회 수']) { const th = document.createElement('th'); th.scope = 'col'; th.textContent = text; header.append(th); }
      const head = document.createElement('thead'); head.append(header); table.append(head);
      const body = document.createElement('tbody');
      const maxRequests = Math.max(1, ...data.items.map((item: { requests: number }) => Number.isFinite(item.requests) ? item.requests : 0));
      for (const item of data.items) {
        const row = document.createElement('tr');
        for (const value of [item.datatype === 'timetable' ? '시간표' : '급식', item.school_name || '이름 미확인', item.school_id]) {
          const cell = document.createElement('td'); cell.textContent = String(value); row.append(cell);
        }
        const count = document.createElement('td'); count.textContent = String(item.requests);
        const bar = document.createElement('span'); bar.className = item.datatype === 'timetable' ? 'school-bar school-bar--timetable' : 'school-bar school-bar--meals';
        bar.style.width = `${Math.max(0, Math.min(100, Number(item.requests) / maxRequests * 100))}%`; bar.setAttribute('aria-hidden', 'true'); count.append(bar); row.append(count);
        body.append(row);
      }
      table.append(body); const wrapper = document.createElement('div'); wrapper.className = 'scroll'; wrapper.tabIndex = 0; wrapper.append(table); results.append(wrapper);
    } catch (error) {
      if (!disposed && !current.signal.aborted) state.textContent = error instanceof Error ? error.message : '통계를 불러오지 못했습니다.';
    } finally { if (!disposed && controller === current) button.disabled = false; }
  }
  form.addEventListener('submit', (event) => { event.preventDefault(); void load(); });
  void load();
  return () => { disposed = true; controller?.abort(); activeToken = ''; container.replaceChildren(); };
}
