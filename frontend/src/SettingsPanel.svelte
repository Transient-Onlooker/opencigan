<script lang="ts">
  import { onMount, tick } from 'svelte';
  import Icon from './Icon.svelte';
  import BuildInfo from './BuildInfo.svelte';
  import { allergens } from './allergens';
  import { calculateLessonTimes, validateLessonTimeDrafts, type LessonTimes, type WeekdayLessonTimes } from './lesson-times';
  import type { School } from './api';
  import type { DisplaySettings } from './personalization';
  import type { MealAllergyFilter } from './meal-filter';
  export let view: 'timetable' | 'meals' | 'settings';
  export let school: School | null;
  export let useClassDisplay: boolean;
  export let classError: boolean;
  export let grade: number;
  export let classroom: number;
  export let theme: 'light' | 'dark' | 'system';
  export let animationsEnabled: boolean;
  export let displaySettings: DisplaySettings;
  export let subjectNames: string[];
  export let teacherNames: string[];
  export let lessonTimePeriods: number[];
  export let lessonTimeDrafts: Record<number, { start: string; end: string }>;
  export let weekdayTimeDrafts: WeekdayLessonTimes;
  export let lessonTimeState: string;
  export let settingsBackupState: string;
  export let mealTypes: string[];
  export let enabledMealTypes: string[];
  export let showAllergenNumbers: boolean;
  export let allergySelection: number[];
  export let mealAllergyFilter: MealAllergyFilter;
  export let setMealAllergyFilter: (value: string) => void;
  export let openAllergySettingsRequest: number;
  export let setClassDisplay: (value: boolean) => void;
  export let setTheme: (value: string) => void;
  export let setAnimationsEnabled: (value: boolean) => void;
  export let setColorMode: (value: string) => void;
  export let saveAlias: (kind: 'subject' | 'teacher', key: string, value: string) => void;
  export let saveSubjectColor: (subject: string, value: string) => void;
  export let clearSubjectColors: () => void;
  export let saveDisplaySettings: (value: DisplaySettings) => void;
  export let editLessonTime: (period: number, part: 'start' | 'end', value: string) => void;
  export let editWeekdayTime: (day: number, period: number, part: 'start' | 'end', value: string) => void;
  export let clearWeekdayTime: (day: number, period: number) => void;
  export let applyLessonTimeRules: (value: LessonTimes) => void;
  export let sourceLessonStarts: Record<string, string> | undefined;
  export let sourceLessonAutoEnabled: boolean;
  export let setSourceLessonAuto: (enabled: boolean) => void;
  export let useSourceStart: (period: number) => void;
  export let saveLessonTimes: () => void;
  export let clearLessonTimes: () => void;
  export let downloadSettingsBackup: (classOnly?: boolean) => void;
  export let importSettingsFile: (event: Event) => Promise<void>;
  export let resetDisplaySettings: () => void;
  export let toggleMealType: (type: string, checked: boolean) => void;
  export let setAllergenNumbersVisible: (value: boolean) => void;
  export let toggleAllergy: (id: number, checked: boolean) => void;
  let settingsQuery = '';
  let subjectQuery = '';
  let subjectSchool = '';
  $: if ((school?.id ?? '') !== subjectSchool) { subjectSchool = school?.id ?? ''; subjectQuery = ''; }
  $: managedSubjects = [...new Set([...subjectNames, ...Object.keys(displaySettings.subjectAliases), ...Object.keys(displaySettings.subjectColors)])].sort((a, b) => a.localeCompare(b, 'ko-KR'));
  $: visibleSubjects = managedSubjects.filter((name) => `${name} ${displaySettings.subjectAliases[name] ?? ''}`.toLocaleLowerCase('ko-KR').includes(subjectQuery.trim().toLocaleLowerCase('ko-KR')));
  let teacherAliasQuery = '';
  let teacherAliasSchool = '';
  $: if ((school?.id ?? '') !== teacherAliasSchool) { teacherAliasSchool = school?.id ?? ''; teacherAliasQuery = ''; }
  $: aliasTeachers = [...new Set([...teacherNames, ...Object.keys(displaySettings.teacherAliases)])].sort((a, b) => a.localeCompare(b, 'ko-KR'));
  $: visibleAliasTeachers = aliasTeachers.filter((name) => `${name} ${displaySettings.teacherAliases[name] ?? ''}`.toLocaleLowerCase('ko-KR').includes(teacherAliasQuery.trim().toLocaleLowerCase('ko-KR')));
  let settingsOpen = { general: false, display: false, advanced: false, times: false, backup: false, meals: false, allergies: false };
  let hasPersonalData = false;
  let personalExportState = '';
  onMount(() => {
    try { hasPersonalData = Object.keys(localStorage).some((key) => key.startsWith('personal_timetable_v1:')); }
    catch { hasPersonalData = false; }
  });
  function exportPersonalData() {
    try {
      const entries = Object.keys(localStorage).filter((key) => key.startsWith('personal_timetable_v1:'))
        .map((key) => ({ key, value: localStorage.getItem(key) }));
      const blob = new Blob([JSON.stringify({ format: 'opencigan-personal-data', version: 1, entries }, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = 'opencigan-personal-data.json';
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      personalExportState = '기존 개인 데이터 다운로드를 시작했어요.';
    } catch { personalExportState = '개인 데이터를 읽거나 저장하지 못했어요. 브라우저 저장소를 확인해 주세요.'; }
  }
  let handledAllergySettingsRequest = 0;
  let allergyFilterControl: HTMLSelectElement;
  $: if (openAllergySettingsRequest !== handledAllergySettingsRequest) {
    handledAllergySettingsRequest = openAllergySettingsRequest;
    settingsQuery = '';
    settingsOpen.meals = true;
    settingsOpen.allergies = true;
    tick().then(() => { allergyFilterControl?.focus(); allergyFilterControl?.scrollIntoView({ block: 'center' }); });
  }
  let settingsContent: HTMLElement;
  let searchResults: { name: string; category: string; target: HTMLElement; panel: HTMLDetailsElement }[] = [];
  let ruleSchool = '';
  let lessonDetailsOpen = false;
  let weekdayDetailsOpen = false;
  let timeError: ReturnType<typeof validateLessonTimeDrafts> = null;
  let weekdaySelection = 1;
  let ruleStart = '', ruleDuration = '', ruleBreak = '', ruleLunchAfter = '', ruleLunch = '';
  $: if ((school?.id ?? '') !== ruleSchool) {
    ruleSchool = school?.id ?? '';
    timeError = null;
    ruleStart = ''; ruleDuration = ''; ruleBreak = ''; ruleLunchAfter = ''; ruleLunch = '';
    try {
      const saved = JSON.parse(localStorage.getItem('opensigan-lesson-rules:' + ruleSchool) || 'null');
      if (saved && typeof saved === 'object') {
        ruleStart = typeof saved.start === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(saved.start) ? saved.start : '';
        ruleDuration = /^\d{1,4}$/.test(saved.duration) ? saved.duration : '';
        ruleBreak = /^\d{1,4}$/.test(saved.break) ? saved.break : '';
        ruleLunchAfter = /^\d{1,2}$/.test(saved.lunchAfter) ? saved.lunchAfter : '';
        ruleLunch = /^\d{1,4}$/.test(saved.lunch) ? saved.lunch : '';
      }
    } catch { /* 계산 입력은 저장소 없이도 사용할 수 있습니다. */ }
  }
  function saveRuleDraft() {
    if (!ruleSchool) return;
    try { localStorage.setItem('opensigan-lesson-rules:' + ruleSchool, JSON.stringify({ start: ruleStart, duration: ruleDuration, break: ruleBreak, lunchAfter: ruleLunchAfter, lunch: ruleLunch })); }
    catch { /* 계산 입력은 현재 화면에 유지됩니다. */ }
  }
  function submitLessonTimes() {
    timeError = validateLessonTimeDrafts(lessonTimeDrafts, weekdayTimeDrafts);
    if (timeError) {
      if (timeError.day) { weekdaySelection = timeError.day; weekdayDetailsOpen = true; }
      else lessonDetailsOpen = true;
      return;
    }
    saveLessonTimes();
  }
  $: rulePreview = calculateLessonTimes(ruleStart, ruleDuration, ruleBreak, ruleLunchAfter, ruleLunch, lessonTimePeriods.length);
  function settingsMatch(labels: string, query: string) {
    return !query.trim() || labels.toLocaleLowerCase('ko-KR').includes(query.trim().toLocaleLowerCase('ko-KR'));
  }
  function resetSubject(subject: string) {
    const subjectAliases = { ...displaySettings.subjectAliases };
    const subjectColors = { ...displaySettings.subjectColors };
    delete subjectAliases[subject];
    delete subjectColors[subject];
    saveDisplaySettings({ ...displaySettings, subjectAliases, subjectColors });
  }
  function updateSettingsSearch(query: string) {
    settingsQuery = query;
    searchResults = [];
    if (!query.trim()) return;
    for (const panel of settingsContent.querySelectorAll<HTMLDetailsElement>(':scope > details, :scope > details > details')) {
      const summary = panel.querySelector<HTMLElement>(':scope > summary');
      if (!summary) continue;
      const category = summary.textContent?.trim() ?? '';
      if (panel.classList.contains('allergy-settings') && settingsMatch(category, query)) {
        searchResults.push({ name: category, category, target: summary, panel });
      }
      for (const element of panel.querySelectorAll<HTMLElement>('label, button')) {
        if (element.closest('details') !== panel) continue;
        const target = element.tagName === 'LABEL' ? element.querySelector<HTMLElement>('input,select') : element;
        if (!target) continue;
        const name = target.getAttribute('aria-label') || Array.from(element.childNodes).filter((node) => node.nodeType === Node.TEXT_NODE || (node instanceof HTMLElement && node.tagName === 'SPAN')).map((node) => node.textContent).join('').trim();
        if (name && settingsMatch(name, query)) searchResults.push({ name, category, target, panel });
      }
    }
  }
  async function openSearchResult(result: typeof searchResults[number]) {
    settingsQuery = '';
    searchResults = [];
    await tick();
    const parent = result.panel.parentElement?.closest('details');
    if (parent) parent.open = true;
    result.panel.open = true;
    await tick();
    const target = result.target.matches(':disabled') ? result.panel.querySelector<HTMLElement>('summary') : result.target;
    target?.focus();
    target?.scrollIntoView({ block: 'center' });
  }
</script>

<section id="settings-panel" hidden={view !== 'settings'} aria-labelledby="settings-title">
          <h2 id="settings-title">설정</h2>
          <label class="settings-search">설정 검색<input type="search" value={settingsQuery} oninput={(event) => updateSettingsSearch(event.currentTarget.value)} maxlength="60" placeholder="예: 교시, 알레르기, 백업" /></label>
          {#if settingsQuery.trim()}
            {#if searchResults.length}
              <ul class="settings-results" aria-label="설정 검색 결과">{#each searchResults as result}<li><button type="button" onclick={() => openSearchResult(result)}><span>{result.name}</span><small>{result.category}</small></button></li>{/each}</ul>
            {:else}<p role="status">일치하는 설정이 없어요.</p>{/if}
          {/if}
          <div class="settings-cards" bind:this={settingsContent} hidden={!!settingsQuery.trim()}>
          <details class="display-settings" hidden={!settingsMatch('개발자 연동 알림 API 위젯', settingsQuery)}>
            <summary>개발자용 · 연동</summary>
            <div class="display-settings-grid">
              <a class="notification-link" href="./webhooks.html">시간표 변경 알림 관리 <span aria-hidden="true">↗</span></a>
              <a class="notification-link" href="./api-docs.html">API 문서 <span aria-hidden="true">↗</span></a>
              <a class="notification-link" href="./embed-builder.html">시간표 위젯 만들기 <span aria-hidden="true">↗</span></a>
            </div>
          </details>
          <details class="display-settings" hidden={!settingsMatch('일반 테마 애니메이션', settingsQuery)} bind:open={settingsOpen.general}>
            <summary>일반 설정</summary>
            <div class="display-settings-grid">
              <label>테마<select aria-label="테마" value={theme} onchange={(event) => setTheme(event.currentTarget.value)}><option value="light">라이트 모드</option><option value="dark">다크 모드</option><option value="system">시스템 설정 따르기</option></select></label>
              <label class="display-toggle"><input type="checkbox" checked={animationsEnabled} onchange={(event) => setAnimationsEnabled(event.currentTarget.checked)} /> 애니메이션 사용</label>
            </div>
          </details>
           {#if school}
             <details class="display-settings" hidden={!settingsMatch('시간표 표시 교사 날짜 변경 변동 배지 테두리 밀도 종료 요일 학급', settingsQuery)} bind:open={settingsOpen.display}>
               <summary>시간표 표시 설정</summary>
               <label class="display-toggle"><input type="checkbox" checked={useClassDisplay} disabled={classError} onchange={(event) => setClassDisplay(event.currentTarget.checked)} /> {grade}학년 {classroom}반만 따로 설정</label>
               <div class="display-settings-grid">
                 <label class="display-toggle"><input type="checkbox" checked={displaySettings.showTeachers} onchange={(event) => saveDisplaySettings({ ...displaySettings, showTeachers: event.currentTarget.checked })} /> 시간표에 교사 표시</label>
                  <label class="display-toggle"><input type="checkbox" checked={displaySettings.showDates} onchange={(event) => saveDisplaySettings({ ...displaySettings, showDates: event.currentTarget.checked })} /> 주간 시간표 머리글에 날짜 표시</label>
                  <label class="display-toggle"><input type="checkbox" checked={displaySettings.showChangeHighlights} onchange={(event) => saveDisplaySettings({ ...displaySettings, showChangeHighlights: event.currentTarget.checked })} /> 변경된 수업 강조</label>
                  <label class="display-toggle"><input type="checkbox" checked={displaySettings.showChangeBadges} onchange={(event) => saveDisplaySettings({ ...displaySettings, showChangeBadges: event.currentTarget.checked })} /> 변동 배지 표시</label>
                  <label class="display-toggle"><input type="checkbox" checked={displaySettings.showCellBorders} onchange={(event) => saveDisplaySettings({ ...displaySettings, showCellBorders: event.currentTarget.checked })} /> 시간표 칸 테두리 표시</label>
                  <label>시간표 밀도
                    <select value={displaySettings.density} onchange={(event) => saveDisplaySettings({ ...displaySettings, density: event.currentTarget.value as DisplaySettings['density'] })}>
                      <option value="compact">압축</option><option value="normal">보통</option><option value="relaxed">넓게</option>
                    </select>
                  </label>
                 <label>종료된 수업 표시
                   <select value={displaySettings.endedLessonMode} onchange={(event) => saveDisplaySettings({ ...displaySettings, endedLessonMode: event.currentTarget.value as DisplaySettings['endedLessonMode'] })}>
                     <option value="dim">흐리게 표시</option><option value="hide">숨기기</option><option value="normal">그대로 표시</option>
                   </select>
                 </label>
                 <label class="display-toggle"><input type="checkbox" checked={displaySettings.dimOtherDays} onchange={(event) => saveDisplaySettings({ ...displaySettings, dimOtherDays: event.currentTarget.checked })} /> 이번 주 오늘 외 요일 흐리게 표시</label>
               </div>
               <p class="display-settings-hint">{useClassDisplay ? '현재 학급에만 적용돼요.' : '별도 설정이 없는 이 학교 학급에 적용돼요.'}</p>
             </details>
             <details class="display-settings" hidden={!settingsMatch('데이터 고급 과목 색상 별칭 교사 이름 상세', settingsQuery)} bind:open={settingsOpen.advanced}>
               <summary>과목·교사 상세 설정</summary>
               <p class="display-settings-hint">{useClassDisplay ? '현재 학급에만 적용돼요.' : '별도 설정이 없는 이 학교 학급에 적용돼요.'}</p>
               <div class="display-settings-grid">
                 <label>과목 색상<select aria-label="과목 색상" value={displaySettings.colorMode} onchange={(event) => setColorMode(event.currentTarget.value)}><option value="none">색상 없음 (기본)</option><option value="auto">자동 색상</option><option value="custom">직접 선택</option></select></label>
                 {#if displaySettings.colorMode === 'custom'}
                   <button type="button" class="secondary-button display-reset" onclick={clearSubjectColors}>과목 색상 초기화</button>
                 {/if}
               </div>
               <details class="subject-settings">
                 <summary>과목 색상·표시 이름 관리</summary>
                 <p class="display-settings-hint">원본 과목명은 바뀌지 않아요. 선택한 색상은 과목 색상에서 ‘직접 선택’을 선택하면 적용돼요.</p>
                 <label class="subject-search">과목 목록 검색<input type="search" bind:value={subjectQuery} placeholder="원본 이름 또는 표시 이름" /></label>
                 {#if visibleSubjects.length}
                   <ul class="subject-list" aria-label="과목 색상과 표시 이름 목록">
                     {#each visibleSubjects as subject (subject)}
                       <li><div class="subject-original"><strong>{subject}</strong>{#if !subjectNames.includes(subject)} <small>저장된 과목</small>{/if}</div>
                         <label class="subject-alias"><span class="sr-only">{subject} 표시 이름</span><input aria-label={`${subject} 표시 이름`} type="text" value={displaySettings.subjectAliases[subject] || ''} maxlength="60" placeholder="원본 이름 유지" onchange={(event) => saveAlias('subject', subject, event.currentTarget.value)} /></label>
                         <label class="subject-color"><span class="sr-only">{subject} 색상</span><input aria-label={`${subject} 색상`} type="color" value={displaySettings.subjectColors[subject] || '#425a75'} onchange={(event) => saveSubjectColor(subject, event.currentTarget.value)} /><small>{displaySettings.subjectColors[subject] || '미설정'}</small></label>
                         <button class="text-button" type="button" aria-label={`${subject} 설정 초기화`} disabled={!displaySettings.subjectAliases[subject] && !displaySettings.subjectColors[subject]} onclick={() => resetSubject(subject)}>초기화</button>
                       </li>
                     {/each}
                   </ul>
                 {:else}<p class="display-settings-hint">{managedSubjects.length ? '일치하는 과목이 없어요.' : '시간표에 등록된 과목이 없어요.'}</p>{/if}
               </details>
               <details class="teacher-alias-settings">
                 <summary>교사 표시 이름 관리</summary>
                 <p class="display-settings-hint">원본 이름은 변경하지 않아요. 이름이 같은 교사는 원본에서 구분되지 않으면 함께 적용됩니다.</p>
                 <label class="teacher-alias-search">교사 목록 검색<input type="search" bind:value={teacherAliasQuery} placeholder="원본 이름 또는 표시 이름" /></label>
                 {#if visibleAliasTeachers.length}
                   <ul class="teacher-alias-list" aria-label="교사 표시 이름 목록">
                     {#each visibleAliasTeachers as teacher (teacher)}
                       <li><div><strong>{teacher}</strong>{#if displaySettings.teacherAliases[teacher]} <small>변경됨</small>{/if}{#if !teacherNames.includes(teacher)} <small>저장된 이름</small>{/if}</div>
                         <label><span class="sr-only">{teacher} 표시 이름</span><input aria-label={`${teacher} 표시 이름`} type="text" value={displaySettings.teacherAliases[teacher] || ''} maxlength="60" placeholder="원본 이름 유지" onchange={(event) => saveAlias('teacher', teacher, event.currentTarget.value)} /></label>
                         <button class="text-button" type="button" aria-label={`${teacher} 표시 이름 초기화`} disabled={!displaySettings.teacherAliases[teacher]} onclick={() => saveAlias('teacher', teacher, '')}>초기화</button>
                       </li>
                     {/each}
                   </ul>
                 {:else}<p class="display-settings-hint">{aliasTeachers.length ? '일치하는 교사가 없어요.' : '시간표에 등록된 교사 이름이 없어요.'}</p>{/if}
               </details>
               <div class="display-settings-grid" aria-label="교사 이름 공통 규칙">
                 <label>모든 교사 이름 앞에 추가
                   <input type="text" value={displaySettings.teacherPrefix} maxlength="30" placeholder="예: 선생님 " oninput={(event) => saveDisplaySettings({ ...displaySettings, teacherPrefix: event.currentTarget.value })} />
                 </label>
                 <label>모든 교사 이름 뒤에 추가
                   <input type="text" value={displaySettings.teacherSuffix} maxlength="30" placeholder="예: T" oninput={(event) => saveDisplaySettings({ ...displaySettings, teacherSuffix: event.currentTarget.value })} />
                 </label>
               </div>
             </details>
             <details class="lesson-time-settings" hidden={!settingsMatch('학교 교시 시각 시간 시작 종료', settingsQuery)} bind:open={settingsOpen.times}>
               <summary>학교 교시 시각 설정</summary>
               <p class="display-settings-hint">설정은 이 브라우저의 해당 학교에만 저장돼요. 원본에 시작 시각만 있으면 종료 시각은 비워 두며 추측하지 않아요.</p>
               <label class="display-settings-hint"><input type="checkbox" checked={sourceLessonAutoEnabled} onchange={(event) => setSourceLessonAuto(event.currentTarget.checked)} /> 원본 시작 시각 자동 적용</label>
               {#if sourceLessonStarts && Object.keys(sourceLessonStarts).length}
                 <div class="lesson-preview" aria-label="원본 교시 시작 시각">
                   <strong>원본 시작 시각</strong>
                   <p>현재 학교의 신선한 시간표 원본에서 확인한 시작 시각이에요. 종료 시각은 학교에서 확인해 입력해 주세요.</p>
                   <ol>{#each lessonTimePeriods.filter((period) => sourceLessonStarts?.[String(period)]) as period}<li>{period}교시 {sourceLessonStarts[String(period)]}</li>{/each}</ol>
                 </div>
               {/if}
               <div class="lesson-rule-grid">
                 <label>1교시 시작 시각<input type="time" bind:value={ruleStart} onchange={(event) => { ruleStart = event.currentTarget.value; saveRuleDraft(); }} /></label>
                 <label>수업 시간 (분)<input type="number" min="1" max="1440" step="1" value={ruleDuration} oninput={(event) => ruleDuration = event.currentTarget.value} onchange={saveRuleDraft} /></label>
                 <label>기본 쉬는 시간 (분)<input type="number" min="0" max="1440" step="1" value={ruleBreak} oninput={(event) => ruleBreak = event.currentTarget.value} onchange={saveRuleDraft} /></label>
                 <label>점심시간 시작<select bind:value={ruleLunchAfter} onchange={(event) => { ruleLunchAfter = event.currentTarget.value; saveRuleDraft(); }}><option value="">점심시간 없음</option>{#each lessonTimePeriods.slice(0, -1) as period}<option value={String(period)}>{period}교시 후</option>{/each}</select></label>
                 {#if ruleLunchAfter}<label>점심시간 길이 (분)<input type="number" min="0" max="1440" step="1" value={ruleLunch} oninput={(event) => ruleLunch = event.currentTarget.value} onchange={saveRuleDraft} /></label>{/if}
               </div>
               {#if rulePreview}
                 <div class="lesson-preview" aria-label="계산된 교시 시각 미리보기">
                   <strong>계산 미리보기</strong>
                   <p>학교에서 확인한 시간과 비교해 주세요. 적용하면 아래 입력값이 교체되며 저장 전에는 반영되지 않아요.</p>
                   <ol>{#each lessonTimePeriods as period}<li>{period}교시 {rulePreview[period].start}–{rulePreview[period].end}</li>{/each}</ol>
                   <button class="secondary-button" type="button" onclick={() => { if (rulePreview) { timeError = null; applyLessonTimeRules(rulePreview); } }}>계산값 입력란에 적용</button>
                 </div>
               {:else if ruleStart || ruleDuration || ruleBreak || ruleLunchAfter || ruleLunch}
                 <p class="state-inline" role="status">시작 시각과 수업·쉬는 시간을 입력하고, 선택한 점심시간과 하루 범위를 확인해 주세요.</p>
               {/if}
               <details class="lesson-time-detail" bind:open={lessonDetailsOpen}>
                 <summary>상세 시간 설정하기</summary>
                 <p class="display-settings-hint">직접 수정한 시각이 저장됩니다. 계산 입력은 이 학교의 브라우저에만 별도로 보관되며 백업 파일에는 포함되지 않아요. 실제 시각을 바꾸려면 계산값을 적용하고 저장해 주세요.</p>
               <div class="lesson-time-grid">
                 {#each lessonTimePeriods as period}
                   <div class="lesson-time-row">
                     <strong>{period}교시</strong>
                     <label>시작 <input type="time" aria-label={`${period}교시 시작`} aria-invalid={timeError?.day === 0 && timeError.period === period} aria-describedby={timeError?.day === 0 && timeError.period === period ? 'lesson-time-error' : undefined} value={lessonTimeDrafts[period]?.start ?? ''} oninput={(event) => { timeError = null; editLessonTime(period, 'start', event.currentTarget.value); }} /></label>
                     <label>종료 <input type="time" aria-label={`${period}교시 종료`} aria-invalid={timeError?.day === 0 && timeError.period === period} aria-describedby={timeError?.day === 0 && timeError.period === period ? 'lesson-time-error' : undefined} value={lessonTimeDrafts[period]?.end ?? ''} oninput={(event) => { timeError = null; editLessonTime(period, 'end', event.currentTarget.value); }} /></label>
                     {#if sourceLessonStarts?.[String(period)] && lessonTimeDrafts[period]?.start !== sourceLessonStarts[String(period)]}<button class="text-button lesson-time-revert" type="button" aria-label={`${period}교시 원본 시작 시각으로 되돌리기`} onclick={() => { timeError = null; useSourceStart(period); }}>원본 시작 시각 사용</button>{/if}
                     {#if timeError?.day === 0 && timeError.period === period}<p id="lesson-time-error" class="lesson-validation" role="alert">{timeError.message}</p>{/if}
                     {#if rulePreview}<button class="text-button lesson-time-revert" type="button" aria-label={`${period}교시 계산값으로 되돌리기`} onclick={() => { if (rulePreview) { timeError = null; editLessonTime(period, 'start', rulePreview[period].start); editLessonTime(period, 'end', rulePreview[period].end); } }}>계산값 복귀</button>{/if}
                   </div>
                 {/each}
               </div>
               </details>
               <details class="lesson-time-detail" bind:open={weekdayDetailsOpen}>
                 <summary>요일별 예외 시각</summary>
                 <p class="display-settings-hint">요일별로 입력한 교시만 공통 시각보다 우선합니다. 시작·종료를 모두 입력하거나 공통 시각으로 되돌리세요.</p>
                 <label>요일 선택 <select bind:value={weekdaySelection}><option value={1}>월요일</option><option value={2}>화요일</option><option value={3}>수요일</option><option value={4}>목요일</option><option value={5}>금요일</option><option value={6}>토요일</option><option value={7}>일요일</option></select></label>
                 <div class="lesson-time-grid">{#each lessonTimePeriods as period}
                   <div class="lesson-time-row">
                     <strong>{period}교시</strong>
                     <label>시작 <input type="time" aria-label={`요일별 ${period}교시 시작`} aria-invalid={timeError?.day === weekdaySelection && timeError.period === period} aria-describedby={timeError?.day === weekdaySelection && timeError.period === period ? 'lesson-time-error' : undefined} value={weekdayTimeDrafts[weekdaySelection]?.[period]?.start ?? ''} oninput={(event) => { timeError = null; editWeekdayTime(weekdaySelection, period, 'start', event.currentTarget.value); }} /></label>
                     <label>종료 <input type="time" aria-label={`요일별 ${period}교시 종료`} aria-invalid={timeError?.day === weekdaySelection && timeError.period === period} aria-describedby={timeError?.day === weekdaySelection && timeError.period === period ? 'lesson-time-error' : undefined} value={weekdayTimeDrafts[weekdaySelection]?.[period]?.end ?? ''} oninput={(event) => { timeError = null; editWeekdayTime(weekdaySelection, period, 'end', event.currentTarget.value); }} /></label>
                     {#if timeError?.day === weekdaySelection && timeError.period === period}<p id="lesson-time-error" class="lesson-validation" role="alert">{timeError.message}</p>{/if}
                     {#if weekdayTimeDrafts[weekdaySelection]?.[period]}<button class="text-button lesson-time-revert" type="button" aria-label={`요일별 ${period}교시 공통 시각으로 되돌리기`} onclick={() => { timeError = null; clearWeekdayTime(weekdaySelection, period); }}>공통 시각 사용</button>{/if}
                   </div>
                 {/each}</div>
               </details>
               <p class="display-settings-hint">시각 초기화는 저장된 기본 교시 시각과 요일별 예외를 지워요. 위의 계산 입력값은 유지돼요.</p>
               <div class="lesson-time-actions"><button class="secondary-button" type="button" onclick={(event) => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); event.currentTarget.focus(); submitLessonTimes(); }}><Icon name="save" /> 시각 저장</button><button class="secondary-button" type="button" onclick={() => { timeError = null; clearLessonTimes(); }}>시각 초기화</button></div>
               {#if lessonTimeState}<p class="state-inline" role="status">{lessonTimeState}</p>{/if}
             </details>
             <details class="settings-backup" hidden={!settingsMatch('설정 백업 복원 파일 저장 가져오기 내보내기 초기화', settingsQuery)} bind:open={settingsOpen.backup}>
               <summary>설정 백업·복원</summary>
               <p class="display-settings-hint">학교 파일에는 기본 표시 설정과 교시 시각을, 학급 파일에는 해당 학급의 표시 설정을 저장해요. 두 파일 모두 급식 알레르기 설정은 포함하지 않아요.</p>
               {#if !useClassDisplay}<p class="display-settings-hint">학급 설정 파일을 저장하려면 시간표 표시 설정에서 ‘{grade}학년 {classroom}반만 따로 설정’을 켜 주세요.</p>{/if}
               <div class="lesson-time-actions">
                 <button class="secondary-button" type="button" onclick={() => downloadSettingsBackup()}><Icon name="save" /> 학교 설정 파일 저장</button>
                 {#if useClassDisplay}<button class="secondary-button" type="button" disabled={classError} onclick={() => downloadSettingsBackup(true)}><Icon name="save" /> 학급 설정 파일 저장</button>{/if}
                 <label class="settings-import">설정 파일 불러오기 <input type="file" accept=".json,application/json" aria-label="Opencigan 설정 JSON 파일 불러오기" onchange={importSettingsFile} /></label>
                 <button class="secondary-button" type="button" onclick={resetDisplaySettings}>{useClassDisplay ? '이 학급에 학교 기본 설정 적용' : '학교 표시 설정 초기화'}</button>
               </div>
               {#if settingsBackupState}<p class="state-inline" role="status">{settingsBackupState}</p>{/if}
             </details>
           {/if}
          {#if !school}<p class="display-settings-hint">학교를 선택하면 시간표 설정을 바꿀 수 있어요.</p>{/if}
             <details class="meal-preferences" hidden={!settingsMatch('급식 보기 식사 조식 중식 석식 알레르기 번호', settingsQuery)} bind:open={settingsOpen.meals}>
               <summary>급식 설정</summary>
               <div class="meal-preference-options" aria-label="표시할 식사"><span>표시할 식사</span>{#each mealTypes as type}<label><input type="checkbox" checked={enabledMealTypes.includes(type)} disabled={enabledMealTypes.length === 1 && enabledMealTypes.includes(type)} onchange={(event) => toggleMealType(type, event.currentTarget.checked)} />{type}</label>{/each}</div>
               <label class="meal-number-toggle"><input type="checkbox" checked={showAllergenNumbers} onchange={(event) => setAllergenNumbersVisible(event.currentTarget.checked)} />메뉴의 알레르기 번호 표시</label>
               <p>하루·주간 보기와 표시 설정은 이 브라우저에 저장돼요. 주의 알레르기 경고는 항상 표시됩니다.</p>
               <details class="allergy-settings" bind:open={settingsOpen.allergies}><summary>알레르기 관리 {allergySelection.length ? `(${allergySelection.length}개 선택)` : ''}</summary><label class="meal-filter-setting">메뉴 표시 방식<select bind:this={allergyFilterControl} value={mealAllergyFilter} onchange={(event) => setMealAllergyFilter(event.currentTarget.value)}><option value="all">모든 메뉴</option><option value="marked">선택 알레르기 표시 메뉴</option><option value="unmarked">선택 알레르기 미표시 메뉴</option></select></label><div class="allergy-grid">{#each allergens as name, index}<label><input type="checkbox" checked={allergySelection.includes(index + 1)} onchange={(event) => toggleAllergy(index + 1, event.currentTarget.checked)} /><span>{index + 1}. {name}</span></label>{/each}</div><p>선택 항목은 이 브라우저에만 저장돼요. NEIS에서 알레르기가 표시되지 않았더라도 안전하다는 뜻은 아니에요.</p></details>
             </details>
          </div>
          {#if hasPersonalData}
            <div class="personal-export"><p>이 브라우저에 이전 개인 시간표·일정 데이터가 남아 있어요. 파일에는 모든 학교·학급의 개인 데이터가 포함되므로 보관에 주의해 주세요.</p><button class="secondary-button" type="button" onclick={exportPersonalData}>기존 개인 데이터 내보내기</button>{#if personalExportState}<p role="status">{personalExportState}</p>{/if}</div>
          {/if}
          <BuildInfo />
        </section>

<style>
.settings-search{display:grid;gap:5px;margin:0 0 12px;font-size:13px;color:var(--muted)}
.notification-link,.notification-link:visited{box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:48px;margin:0 0 12px;padding:10px 14px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:14px;font-weight:650;line-height:1.4;text-decoration:none}.notification-link:hover{background:var(--soft);border-color:var(--ink)}.notification-link:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.personal-export{margin:16px 0;color:var(--muted);font-size:12px;line-height:1.6}.personal-export button{min-height:44px}
.settings-search input{min-height:44px;max-width:100%;width:100%;border:1px solid var(--line);padding:8px;background:var(--surface);color:var(--ink)}
.settings-results{list-style:none;margin:0;padding:0;border-top:1px solid var(--line)}
.settings-results button{display:flex;justify-content:space-between;align-items:center;gap:12px;width:100%;min-height:44px;padding:10px 8px;border:0;border-bottom:1px solid var(--line);background:var(--surface);color:var(--ink);text-align:left;cursor:pointer}
.settings-results button:hover{background:var(--soft)}.settings-results small{color:var(--muted);text-align:right}
@media(max-width:700px){.settings-search input{font-size:16px}}
.display-settings{margin:0 0 14px;border:1px solid var(--line);padding:0 14px}
.display-settings summary{min-height:44px;align-content:center;cursor:pointer;font-size:14px;font-weight:650}
.display-settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:12px;padding:12px 0}
.display-settings-grid label{display:grid;gap:5px;align-content:start;font-size:13px;color:var(--muted)}
.display-settings-grid input:not([type="checkbox"]),.display-settings-grid select{width:100%;min-height:44px;background:var(--surface);color:var(--ink);border:1px solid var(--line);padding:8px;font:inherit;font-size:14px}
.display-settings-grid .display-toggle{display:flex;align-items:center;gap:9px;min-height:44px;cursor:pointer}
.display-settings-grid .display-reset{align-self:end;min-height:44px}
.settings-backup{margin:0 0 14px;padding:0 14px 14px;border:1px solid var(--line)}
.settings-backup summary{min-height:44px;align-content:center;cursor:pointer;font-size:14px;font-weight:650}
.settings-backup .lesson-time-actions{margin-top:0}
.settings-import{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-height:44px;font-size:14px;color:var(--ink)}
.settings-import input{max-width:100%;min-width:0;font-size:13px}
.settings-backup .state-inline{margin-top:10px}
.lesson-time-settings{margin:0 0 14px;padding:0 14px 14px;border:1px solid var(--line)}.lesson-time-settings summary{min-height:44px;align-content:center;cursor:pointer;font-size:14px;font-weight:650}.lesson-time-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.lesson-time-row{display:grid;grid-template-columns:50px repeat(2,minmax(0,1fr));gap:8px;align-items:center;min-width:0;font-size:13px}.lesson-time-row>strong{font-size:13px;white-space:nowrap}.lesson-time-row label{display:grid;gap:4px;min-width:0;color:var(--muted)}.lesson-time-row input{min-width:0;width:100%;min-height:44px;padding:7px 8px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:16px}.lesson-time-actions{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 0}.lesson-time-settings .state-inline{margin-top:10px}
.lesson-rule-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:10px;margin:12px 0}.lesson-rule-grid label{display:grid;gap:4px;min-width:0;font-size:13px;color:var(--muted)}.lesson-rule-grid input,.lesson-rule-grid select{width:100%;min-width:0;min-height:44px;padding:7px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:16px}.lesson-preview{margin:12px 0;padding:12px;border:1px solid var(--line)}.lesson-preview p{color:var(--muted);font-size:13px}.lesson-preview ol{display:flex;flex-wrap:wrap;gap:6px 18px;list-style:none;padding:0;font-size:13px}
.lesson-time-detail{margin-top:12px;border-top:1px solid var(--line)}.lesson-time-revert{grid-column:2 / -1;justify-self:start;min-height:44px}
.lesson-validation{grid-column:1 / -1;margin:0;color:var(--ink);font-size:13px}
@media(max-width:700px){.lesson-time-grid{grid-template-columns:1fr}.lesson-time-row{grid-template-columns:50px repeat(2,minmax(0,1fr))}}
@media(max-width:700px){.display-settings-grid input:not([type="checkbox"]),.display-settings-grid select{font-size:16px}}
.allergy-settings{border-top:1px solid var(--line);margin:0 0 12px}
.meal-preferences{border:1px solid var(--line);margin:0 0 12px;padding:0 14px}
.meal-preferences summary{cursor:pointer;font-size:14px;font-weight:700;min-height:44px;align-content:center}
.meal-preference-options{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:8px 0 12px}
.meal-preference-options>span{font-size:13px;color:var(--muted);margin-right:4px}
.meal-preference-options label,.meal-number-toggle{display:inline-flex;align-items:center;min-height:44px;gap:8px;font-size:14px;cursor:pointer}
.meal-preferences input{width:18px;height:18px;accent-color:var(--ink)}
.meal-preferences p{font-size:12px;line-height:1.6;color:var(--muted);margin:4px 0 12px}
.allergy-settings summary{cursor:pointer;font-size:14px;font-weight:700;min-height:44px;align-content:center}
.allergy-settings summary:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.meal-filter-setting{display:grid;gap:5px;margin:8px 0;font-size:13px}.meal-filter-setting select{width:100%;min-height:44px;padding:8px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;font-size:16px}
.allergy-settings p{font-size:12px;line-height:1.6;color:var(--muted);margin:12px 0}
.allergy-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-top:10px}
.allergy-grid label{display:flex;align-items:center;gap:8px;min-height:38px;font-size:14px;cursor:pointer}
.allergy-grid input{width:18px;height:18px;accent-color:var(--ink)}
.settings-cards>details{box-sizing:border-box;min-width:0;margin:0 0 12px;padding:0 14px;border:1px solid var(--line)}
.settings-cards>details[open]{padding-bottom:14px}
.settings-cards>details>summary{min-height:48px;align-content:center;cursor:pointer;font-size:14px;line-height:1.4;font-weight:650}
.settings-cards summary:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.settings-cards .display-toggle{display:flex;align-items:center;gap:9px;min-height:44px}
.subject-settings{border-top:1px solid var(--line)}.subject-settings summary{cursor:pointer;min-height:44px;align-content:center;font-weight:650;font-size:14px}.subject-search{display:grid;gap:4px;font-size:13px}.subject-alias{min-width:0}.subject-search input,.subject-alias input{box-sizing:border-box;min-width:0;width:100%;min-height:44px;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:8px;font:inherit}.subject-list{list-style:none;margin:12px 0;padding:0;max-height:420px;overflow:auto}.subject-list li{display:grid;grid-template-columns:minmax(70px,1fr) minmax(100px,2fr) auto auto;align-items:center;gap:8px;padding:8px 0;border-top:1px solid var(--line)}.subject-original{min-width:0;overflow-wrap:anywhere}.subject-original small{display:block;color:var(--muted);font-size:12px}.subject-color{display:flex;align-items:center;gap:4px}.subject-color input{box-sizing:border-box;width:44px;height:44px;padding:3px;border:1px solid var(--line);background:var(--surface);cursor:pointer}.subject-color small{color:var(--muted);font-size:11px}.subject-list button{min-height:44px}
@media(max-width:500px){.subject-list li{grid-template-columns:minmax(0,1fr) auto auto}.subject-alias{grid-column:1 / -1;grid-row:2}.subject-search input,.subject-alias input{font-size:16px}}
.teacher-alias-settings{border-top:1px solid var(--line)}.teacher-alias-settings summary{cursor:pointer;min-height:44px;align-content:center;font-weight:650;font-size:14px}.teacher-alias-search{display:grid;gap:4px;font-size:13px}.teacher-alias-settings input{min-width:0;width:100%;min-height:44px;border:1px solid var(--line);background:var(--surface);color:var(--ink);padding:8px;font:inherit}.teacher-alias-list{list-style:none;margin:12px 0;padding:0;max-height:360px;overflow:auto}.teacher-alias-list li{display:grid;grid-template-columns:minmax(70px,1fr) minmax(100px,2fr) auto;align-items:center;gap:8px;padding:8px 0;border-top:1px solid var(--line)}.teacher-alias-list li>div{min-width:0;overflow-wrap:anywhere}.teacher-alias-list small{display:block;color:var(--muted);font-size:12px}.teacher-alias-list button{min-height:44px}
@media(max-width:700px){.allergy-grid label{min-height:44px}}
</style>
