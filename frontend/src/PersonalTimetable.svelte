<script lang="ts">
  import type { TimetableRecord } from './api';
  import { type DisplaySettings, defaultDisplaySettings } from './personalization';
  import {
    type PersonalTimetableEntry,
    type PersonalEvent,
    type PersonalTimetableStore,
    loadPersonalStore,
    savePersonalStore,
    validatePersonalEntry,
    validatePersonalEvent,
    personalEntriesToTimetableRecords,
    MAX_STORE_ENTRIES,
  } from './personal-timetable';
  import { saveTimetablePng } from './export-png';
  import { addDays } from './date';

  let {
    schoolId = '',
    schoolName = '개인 시간표',
    grade = 1,
    classroom = 1,
    week = '',
    dark = false,
    displaySettings = undefined,
  }: {
    schoolId?: string;
    schoolName?: string;
    grade?: number;
    classroom?: number | string;
    week?: string;
    dark?: boolean;
    displaySettings?: DisplaySettings;
  } = $props();

  let store = $state<PersonalTimetableStore>({
    version: 1,
    entries: [],
    events: [],
    updatedAt: '',
  });

  let feedbackMessage = $state('');
  let feedbackType = $state<'info' | 'error' | 'success'>('info');
  let exportBusy = $state(false);

  let newWeekday = $state(1);
  let newPeriod = $state(1);
  let newSubject = $state('');
  let newTeacher = $state('');
  let newSpecificDate = $state('');

  let newEventDate = $state('');
  let newEventTime = $state('');
  let newEventTitle = $state('');
  let newEventType = $state<'event' | 'exam' | 'reminder'>('event');

  let activeTab = $state<'table' | 'events'>('table');

  function showFeedback(msg: string, type: 'info' | 'error' | 'success' = 'info') {
    feedbackMessage = msg;
    feedbackType = type;
  }

  $effect(() => {
    store = loadPersonalStore(schoolId, grade, classroom);
  });

  function handleAddEntry(e: Event) {
    e.preventDefault();
    const candidate = {
      weekday: Number(newWeekday),
      period: Number(newPeriod),
      subject: newSubject,
      teacher: newTeacher || undefined,
      date: newSpecificDate || undefined,
    };
    const valid = validatePersonalEntry(candidate);
    if (!valid) {
      showFeedback('과목명(1~100자), 교시(1~20)를 올바르게 입력해 주세요.', 'error');
      return;
    }

    const filtered = store.entries.filter((entry) => {
      if (valid.date) {
        return !(entry.date === valid.date && entry.period === valid.period);
      }
      return !(entry.weekday === valid.weekday && entry.period === valid.period && !entry.date);
    });

    if (filtered.length + 1 > MAX_STORE_ENTRIES) {
      showFeedback(`최대 ${MAX_STORE_ENTRIES}개까지 등록할 수 있습니다.`, 'error');
      return;
    }

    const nextStore: PersonalTimetableStore = {
      ...store,
      entries: [...filtered, valid],
    };
    const res = savePersonalStore(schoolId, grade, classroom, nextStore);
    if (!res.success) {
      showFeedback(res.error || '저장에 실패했습니다.', 'error');
      return;
    }
    store = nextStore;
    newSubject = '';
    newTeacher = '';
    newSpecificDate = '';
    showFeedback('시간표 항목이 저장되었습니다.', 'success');
  }

  function handleDeleteEntry(id: string) {
    const nextStore: PersonalTimetableStore = {
      ...store,
      entries: store.entries.filter((entry) => entry.id !== id),
    };
    const res = savePersonalStore(schoolId, grade, classroom, nextStore);
    if (res.success) {
      store = nextStore;
      showFeedback('항목이 삭제되었습니다.', 'info');
    } else {
      showFeedback(res.error || '삭제 실패', 'error');
    }
  }

  function handleAddEvent(e: Event) {
    e.preventDefault();
    if (store.events.length >= MAX_STORE_ENTRIES) {
      showFeedback(`최대 ${MAX_STORE_ENTRIES}개까지 등록할 수 있습니다.`, 'error');
      return;
    }
    const candidate = {
      date: newEventDate,
      time: newEventTime || undefined,
      title: newEventTitle,
      type: newEventType,
    };
    const valid = validatePersonalEvent(candidate);
    if (!valid) {
      showFeedback('날짜(YYYY-MM-DD)와 제목(1~100자)을 올바르게 입력해 주세요.', 'error');
      return;
    }
    const nextStore: PersonalTimetableStore = {
      ...store,
      events: [...store.events, valid],
    };
    const res = savePersonalStore(schoolId, grade, classroom, nextStore);
    if (!res.success) {
      showFeedback(res.error || '저장 실패', 'error');
      return;
    }
    store = nextStore;
    newEventTitle = '';
    newEventTime = '';
    showFeedback('일정이 추가되었습니다.', 'success');
  }

  function handleDeleteEvent(id: string) {
    const nextStore: PersonalTimetableStore = {
      ...store,
      events: store.events.filter((ev) => ev.id !== id),
    };
    const res = savePersonalStore(schoolId, grade, classroom, nextStore);
    if (res.success) {
      store = nextStore;
      showFeedback('일정이 삭제되었습니다.', 'info');
    } else {
      showFeedback(res.error || '삭제 실패', 'error');
    }
  }

  async function handleExportPng() {
    if (!week) {
      showFeedback('내보낼 주간(week) 정보가 없습니다.', 'error');
      return;
    }
    exportBusy = true;
    try {
      const records = personalEntriesToTimetableRecords(store.entries, { week, grade, classroom });
      if (records.length === 0) {
        showFeedback('해당 주에 내보낼 개인 시간표 수업이 없습니다.', 'error');
        exportBusy = false;
        return;
      }
      await saveTimetablePng({
        view: 'week',
        schoolName: `${schoolName} (개인 시간표)`,
        grade,
        classroom: Number(classroom) || 1,
        selectedDay: week,
        week,
        teacherName: '',
        records,
        dark,
        displaySettings: displaySettings ?? defaultDisplaySettings(),
      });
      showFeedback('시간표 PNG 저장이 완료되었습니다.', 'success');
    } catch (err) {
      showFeedback(err instanceof Error ? err.message : 'PNG 생성 실패', 'error');
    } finally {
      exportBusy = false;
    }
  }

  const weekdays = [
    { num: 1, label: '월요일' },
    { num: 2, label: '화요일' },
    { num: 3, label: '수요일' },
    { num: 4, label: '목요일' },
    { num: 5, label: '금요일' },
  ];

  let maxPeriodInEntries = $derived.by(() => {
    if (store.entries.length === 0) return 7;
    return Math.max(7, ...store.entries.map((e) => e.period));
  });
</script>

<section class="pt-container" aria-label="개인 시간표">
  <header class="pt-header">
    <div>
      <span class="pt-badge">로컬 개인 시간표</span>
      <h3>{schoolName} · {grade}학년 {classroom}반</h3>
      <p class="pt-desc">브라우저 로컬 저장소에만 보관되며 학교 공식 시간표 원본은 변경되지 않습니다.</p>
    </div>
    <button type="button" class="pt-btn" onclick={handleExportPng} disabled={exportBusy || store.entries.length === 0}>
      {exportBusy ? '내보내는 중...' : '시간표 PNG 저장'}
    </button>
  </header>

  {#if feedbackMessage}
    <div class="pt-feedback" class:error={feedbackType === 'error'} class:success={feedbackType === 'success'} role="status">
      {feedbackMessage}
    </div>
  {/if}

  <div class="pt-nav" role="group" aria-label="시간표 탭 선택">
    <button
      type="button"
      class="pt-nav-btn"
      aria-pressed={activeTab === 'table'}
      onclick={() => { activeTab = 'table'; }}
    >
      주간 시간표 ({store.entries.length})
    </button>
    <button
      type="button"
      class="pt-nav-btn"
      aria-pressed={activeTab === 'events'}
      onclick={() => { activeTab = 'events'; }}
    >
      일정 / 시험 오버레이 ({store.events.length})
    </button>
  </div>

  {#if activeTab === 'table'}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div class="pt-table-wrap" tabindex="0" role="region" aria-label="개인 시간표 주간 격자">
      <table class="pt-grid">
        <thead>
          <tr>
            <th scope="col" class="period-col">교시</th>
            {#each weekdays as day}
              <th scope="col">{day.label}</th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each Array.from({ length: maxPeriodInEntries }, (_, i) => i + 1) as p}
            <tr>
              <th scope="row" class="period-cell">{p}</th>
              {#each weekdays as day}
                {@const cellDate = addDays(week, day.num - 1)}
                {@const cellEntry = store.entries.find((e) => e.date === cellDate && e.period === p) ?? store.entries.find((e) => e.weekday === day.num && e.period === p && !e.date)}
                <td class="lesson-cell">
                  {#if cellEntry}
                    <div class="cell-content">
                      <span class="subject-title">{cellEntry.subject}</span>
                      {#if cellEntry.teacher}
                        <span class="teacher-name">{cellEntry.teacher}</span>
                      {/if}
                      <button
                        type="button"
                        class="pt-del-icon"
                        aria-label="{day.label} {p}교시 {cellEntry.subject} 삭제"
                        onclick={() => handleDeleteEntry(cellEntry.id)}
                      >
                        ×
                      </button>
                    </div>
                  {:else}
                    <span class="empty-slot">-</span>
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    {#if store.events.some((event) => event.date >= week && event.date <= addDays(week, 6))}
      <ul class="events-list" aria-label="이번 주 개인 일정">{#each store.events.filter((event) => event.date >= week && event.date <= addDays(week, 6)) as event}<li>{event.date} {event.time ?? ''} · {event.type === 'exam' ? '시험 · ' : ''}{event.title}</li>{/each}</ul>
    {/if}

    <form class="pt-form" onsubmit={handleAddEntry}>
      <h4>수업 추가 / 변경</h4>
      <div class="form-row">
        <label>
          요일
          <select bind:value={newWeekday}>
            {#each weekdays as day}
              <option value={day.num}>{day.label}</option>
            {/each}
          </select>
        </label>
        <label>
          교시
          <input type="number" min="1" max="20" bind:value={newPeriod} required />
        </label>
        <label class="grow">
          과목명
          <input type="text" maxlength="100" placeholder="예: 국어" bind:value={newSubject} required />
        </label>
        <label>
          교사 (선택)
          <input type="text" maxlength="60" placeholder="교사명" bind:value={newTeacher} />
        </label>
        <label>
          특정 일자 (선택)
          <input type="date" bind:value={newSpecificDate} />
        </label>
        <button type="submit" class="pt-submit-btn">저장</button>
      </div>
    </form>
  {:else}
    <div class="events-wrap">
      {#if store.events.length === 0}
        <p class="empty-msg">등록된 개인 일정 또는 시험이 없습니다.</p>
      {:else}
        <ul class="events-list">
          {#each store.events as ev}
            <li class="event-item">
              <span class="pt-tag">{ev.type === 'exam' ? '시험' : ev.type === 'reminder' ? '알림' : '일정'}</span>
              <div class="event-info">
                <strong>{ev.title}</strong>
                <span>{ev.date}{ev.time ? ` ${ev.time}` : ''}</span>
              </div>
              <button
                type="button"
                class="pt-btn"
                aria-label="{ev.title} 삭제"
                onclick={() => handleDeleteEvent(ev.id)}
              >
                삭제
              </button>
            </li>
          {/each}
        </ul>
      {/if}

      <form class="pt-form" onsubmit={handleAddEvent}>
        <h4>새 일정 / 시험 추가</h4>
        <div class="form-row">
          <label>
            구분
            <select bind:value={newEventType}>
              <option value="event">일정</option>
              <option value="exam">시험</option>
              <option value="reminder">알림</option>
            </select>
          </label>
          <label>
            날짜
            <input type="date" bind:value={newEventDate} required />
          </label>
          <label>
            시각 (선택)
            <input type="time" bind:value={newEventTime} />
          </label>
          <label class="grow">
            제목
            <input type="text" maxlength="100" placeholder="예: 중간고사 수학" bind:value={newEventTitle} required />
          </label>
          <button type="submit" class="pt-submit-btn">추가</button>
        </div>
      </form>
    </div>
  {/if}
</section>

<style>
  .pt-container {
    border: 1px solid var(--line, #d4d4d4);
    background: var(--surface, #ffffff);
    color: var(--ink, #111111);
    padding: 16px;
    margin: 16px 0;
  }
  .pt-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--line, #d4d4d4);
  }
  .pt-badge {
    font-size: 11px;
    font-weight: 700;
    padding: 2px 6px;
    background: var(--ink, #111111);
    color: var(--surface, #ffffff);
    display: inline-block;
  }
  .pt-header h3 {
    margin: 4px 0 0;
    font-size: 18px;
  }
  .pt-desc {
    margin: 4px 0 0;
    font-size: 13px;
    color: var(--muted, #555555);
  }
  .pt-btn {
    min-height: 38px;
    padding: 6px 12px;
    border: 1px solid var(--line, #d4d4d4);
    background: var(--surface, #ffffff);
    color: var(--ink, #111111);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .pt-btn:hover:not(:disabled) {
    background: var(--soft, #f5f5f5);
    border-color: var(--ink, #111111);
  }
  .pt-feedback {
    padding: 8px 12px;
    margin: 12px 0;
    font-size: 13px;
    border: 1px solid var(--line, #d4d4d4);
    background: var(--soft, #f5f5f5);
  }
  .pt-feedback.error { border-color: #d32f2f; color: #d32f2f; }
  .pt-feedback.success { border-color: #2e7d32; color: #2e7d32; }
  .pt-nav {
    display: flex;
    border-bottom: 1px solid var(--line, #d4d4d4);
    margin: 12px 0;
  }
  .pt-nav-btn {
    min-height: 38px;
    padding: 6px 14px;
    border: 1px solid transparent;
    border-bottom: none;
    background: transparent;
    color: var(--muted, #555555);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .pt-nav-btn[aria-pressed="true"] {
    border-color: var(--line, #d4d4d4);
    border-bottom: 2px solid var(--surface, #ffffff);
    background: var(--surface, #ffffff);
    color: var(--ink, #111111);
    margin-bottom: -1px;
  }
  .pt-table-wrap {
    overflow-x: auto;
    margin-bottom: 16px;
  }
  .pt-grid {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    text-align: center;
  }
  .pt-grid th, .pt-grid td {
    border: 1px solid var(--line, #d4d4d4);
    padding: 6px;
    min-width: 64px;
  }
  .pt-grid thead th, .period-col, .period-cell {
    background: var(--soft, #f5f5f5);
    font-weight: 700;
  }
  .lesson-cell {
    vertical-align: top;
    height: 48px;
  }
  .cell-content {
    display: flex;
    flex-direction: column;
    position: relative;
    padding-right: 12px;
    text-align: left;
  }
  .subject-title { font-weight: 600; font-size: 13px; overflow-wrap: anywhere; }
  .teacher-name { font-size: 11px; color: var(--muted, #555555); overflow-wrap: anywhere; }
  .pt-del-icon {
    position: absolute;
    top: -2px;
    right: -2px;
    width: 16px;
    height: 16px;
    border: none;
    background: transparent;
    color: var(--muted, #555555);
    cursor: pointer;
    font-size: 13px;
    padding: 0;
  }
  .empty-slot { color: var(--line, #d4d4d4); }
  .pt-form {
    border: 1px solid var(--line, #d4d4d4);
    padding: 12px;
    background: var(--soft, #f5f5f5);
    margin-top: 12px;
  }
  .pt-form h4 { margin: 0 0 10px; font-size: 14px; }
  .form-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: flex-end;
  }
  .form-row label {
    display: flex;
    flex-direction: column;
    font-size: 12px;
    font-weight: 600;
    gap: 4px;
  }
  .form-row label.grow { flex: 1; min-width: 120px; }
  .form-row input, .form-row select {
    min-height: 36px;
    padding: 6px 8px;
    border: 1px solid var(--line, #d4d4d4);
    background: var(--surface, #ffffff);
    color: var(--ink, #111111);
    font: inherit;
    font-size: 13px;
  }
  .pt-submit-btn {
    min-height: 36px;
    padding: 6px 14px;
    background: var(--ink, #111111);
    color: var(--surface, #ffffff);
    border: 1px solid var(--ink, #111111);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .empty-msg { font-size: 13px; color: var(--muted, #555555); padding: 8px 0; }
  .events-list {
    list-style: none;
    margin: 0 0 12px;
    padding: 0;
    border: 1px solid var(--line, #d4d4d4);
  }
  .event-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-bottom: 1px solid var(--line, #d4d4d4);
    gap: 8px;
  }
  .event-item:last-child { border-bottom: none; }
  .pt-tag {
    font-size: 11px;
    font-weight: 700;
    padding: 2px 6px;
    border: 1px solid var(--line, #d4d4d4);
    background: var(--soft, #f5f5f5);
  }
  .event-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    font-size: 13px;
  }
  .event-info span { font-size: 11px; color: var(--muted, #555555); }
</style>
