<script lang="ts">
  import Icon from './Icon.svelte';
  import { allergens } from './allergens';
  import type { School } from './api';
  import type { DisplaySettings } from './personalization';
  export let view: 'timetable' | 'meals' | 'settings';
  export let school: School | null;
  export let useClassDisplay: boolean;
  export let classError: boolean;
  export let grade: number;
  export let classroom: number;
  export let theme: 'light' | 'dark' | 'system';
  export let animationsEnabled: boolean;
  export let displaySettings: DisplaySettings;
  export let selectedSubject: string;
  export let selectedTeacher: string;
  export let subjectNames: string[];
  export let teacherNames: string[];
  export let lessonTimePeriods: number[];
  export let lessonTimeDrafts: Record<number, { start: string; end: string }>;
  export let lessonTimeState: string;
  export let settingsBackupState: string;
  export let mealTypes: string[];
  export let enabledMealTypes: string[];
  export let showAllergenNumbers: boolean;
  export let allergySelection: number[];
  export let setClassDisplay: (value: boolean) => void;
  export let setTheme: (value: string) => void;
  export let setAnimationsEnabled: (value: boolean) => void;
  export let setColorMode: (value: string) => void;
  export let saveAlias: (kind: 'subject' | 'teacher', key: string, value: string) => void;
  export let saveSubjectColor: (value: string) => void;
  export let clearSubjectColors: () => void;
  export let saveDisplaySettings: (value: DisplaySettings) => void;
  export let editLessonTime: (period: number, part: 'start' | 'end', value: string) => void;
  export let saveLessonTimes: () => void;
  export let clearLessonTimes: () => void;
  export let downloadSettingsBackup: (classOnly?: boolean) => void;
  export let importSettingsFile: (event: Event) => Promise<void>;
  export let resetDisplaySettings: () => void;
  export let toggleMealType: (type: string, checked: boolean) => void;
  export let setAllergenNumbersVisible: (value: boolean) => void;
  export let toggleAllergy: (id: number, checked: boolean) => void;
  let settingsQuery = '';
  let settingsOpen = { display: false, times: false, backup: false, meals: false, allergies: false };
  function settingsMatch(labels: string, query: string) {
    return !query.trim() || labels.toLocaleLowerCase('ko-KR').includes(query.trim().toLocaleLowerCase('ko-KR'));
  }
</script>

<section id="settings-panel" hidden={view !== 'settings'} aria-labelledby="settings-title">
          <h2 id="settings-title">설정</h2>
          <p><a href="./webhooks.html">시간표 변경 알림 관리</a></p>
          <label class="settings-search">설정 검색<input type="search" bind:value={settingsQuery} oninput={() => { if (settingsQuery.trim()) settingsOpen = { display: true, times: true, backup: true, meals: true, allergies: true }; }} maxlength="60" placeholder="예: 교시, 알레르기, 백업" /></label>
          {#if settingsQuery.trim() && !settingsMatch('시간표 표시 테마 애니메이션 과목 색상 별칭 교사 이름 날짜 변경 변동 배지 테두리 밀도 종료 요일 학교 교시 시각 시간 시작 백업 복원 파일 저장 가져오기 내보내기 초기화 급식 보기 식사 조식 중식 석식 알레르기 번호 주의', settingsQuery)}<p role="status">일치하는 설정이 없어요.</p>{/if}
           {#if school}
             <details class="display-settings" hidden={!settingsMatch('시간표 표시 테마 애니메이션 과목 색상 별칭 교사 이름 날짜 변경 변동 배지 테두리 밀도 종료 요일', settingsQuery)} bind:open={settingsOpen.display}>
               <summary>시간표 표시 설정</summary>
               <label class="display-toggle"><input type="checkbox" checked={useClassDisplay} disabled={classError} onchange={(event) => setClassDisplay(event.currentTarget.checked)} /> {grade}학년 {classroom}반만 따로 설정</label>
               <div class="display-settings-grid">
                <label>테마
                  <select value={theme} onchange={(event) => setTheme(event.currentTarget.value)}>
                    <option value="light">라이트 모드</option><option value="dark">다크 모드</option><option value="system">시스템 설정 따르기</option>
                  </select>
                </label>
                 <label class="display-toggle"><input type="checkbox" checked={animationsEnabled} onchange={(event) => setAnimationsEnabled(event.currentTarget.checked)} /> 애니메이션 사용</label>
                 <label>과목 색상
                   <select value={displaySettings.colorMode} onchange={(event) => setColorMode(event.currentTarget.value)}>
                     <option value="none">색상 없음 (기본)</option><option value="auto">자동 색상</option><option value="custom">직접 선택</option>
                   </select>
                 </label>
                 <label>과목 선택
                   <select bind:value={selectedSubject} disabled={!subjectNames.length}>
                     <option value="">과목을 선택하세요</option>{#each subjectNames as subject}<option value={subject}>{subject}</option>{/each}
                   </select>
                 </label>
                 <label>과목 표시 이름
                   <input type="text" value={displaySettings.subjectAliases[selectedSubject] || ''} disabled={!selectedSubject} maxlength="60" placeholder="원본 이름 유지" oninput={(event) => saveAlias('subject', selectedSubject, event.currentTarget.value)} />
                 </label>
                 {#if displaySettings.colorMode === 'custom'}
                   <label>선택한 과목 색상
                     <input type="color" value={displaySettings.subjectColors[selectedSubject] || '#dcebfD'} disabled={!selectedSubject} onchange={(event) => saveSubjectColor(event.currentTarget.value)} />
                   </label>
                   <button type="button" class="secondary-button display-reset" onclick={clearSubjectColors}>과목 색상 초기화</button>
                 {/if}
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
                 <label>교사 선택
                   <select bind:value={selectedTeacher} disabled={!teacherNames.length}>
                     <option value="">교사를 선택하세요</option>{#each teacherNames as teacher}<option value={teacher}>{teacher}</option>{/each}
                   </select>
                 </label>
                 <label>교사 표시 이름
                   <input type="text" value={displaySettings.teacherAliases[selectedTeacher] || ''} disabled={!selectedTeacher} maxlength="60" placeholder="원본 이름 유지" oninput={(event) => saveAlias('teacher', selectedTeacher, event.currentTarget.value)} />
                 </label>
                 <label>모든 교사 이름 앞에 추가
                   <input type="text" value={displaySettings.teacherPrefix} maxlength="30" placeholder="예: 선생님 " oninput={(event) => saveDisplaySettings({ ...displaySettings, teacherPrefix: event.currentTarget.value })} />
                 </label>
                 <label>모든 교사 이름 뒤에 추가
                   <input type="text" value={displaySettings.teacherSuffix} maxlength="30" placeholder="예: T" oninput={(event) => saveDisplaySettings({ ...displaySettings, teacherSuffix: event.currentTarget.value })} />
                 </label>
               </div>
               <p class="display-settings-hint">{useClassDisplay ? '현재 학급에만 적용돼요.' : '별도 설정이 없는 이 학교 학급에 적용돼요.'}</p>
             </details>
             <details class="lesson-time-settings" hidden={!settingsMatch('학교 교시 시각 시간 시작 종료', settingsQuery)} bind:open={settingsOpen.times}>
               <summary>학교 교시 시각 설정</summary>
               <p class="display-settings-hint">학교에서 확인한 실제 시작·종료 시각을 입력해 주세요. 설정은 이 브라우저의 해당 학교에만 저장되며, 입력하지 않은 교시는 추측하지 않습니다.</p>
               <div class="lesson-time-grid">
                 {#each lessonTimePeriods as period}
                   <div class="lesson-time-row">
                     <strong>{period}교시</strong>
                     <label>시작 <input type="time" aria-label={`${period}교시 시작`} value={lessonTimeDrafts[period]?.start ?? ''} oninput={(event) => editLessonTime(period, 'start', event.currentTarget.value)} /></label>
                     <label>종료 <input type="time" aria-label={`${period}교시 종료`} value={lessonTimeDrafts[period]?.end ?? ''} oninput={(event) => editLessonTime(period, 'end', event.currentTarget.value)} /></label>
                   </div>
                 {/each}
               </div>
               <div class="lesson-time-actions"><button class="secondary-button" type="button" onclick={(event) => { if (document.activeElement instanceof HTMLElement) document.activeElement.blur(); event.currentTarget.focus(); saveLessonTimes(); }}><Icon name="save" /> 시각 저장</button><button class="secondary-button" type="button" onclick={clearLessonTimes}>시각 초기화</button></div>
               {#if lessonTimeState}<p class="state-inline" role="status">{lessonTimeState}</p>{/if}
             </details>
             <details class="settings-backup" hidden={!settingsMatch('설정 백업 복원 파일 저장 가져오기 내보내기 초기화', settingsQuery)} bind:open={settingsOpen.backup}>
               <summary>설정 백업·복원</summary>
               <p class="display-settings-hint">학교 파일에는 기본 표시 설정과 교시 시각을, 학급 파일에는 해당 학급의 표시 설정을 저장해요. 두 파일 모두 급식 알레르기 설정은 포함하지 않아요.</p>
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
             <details class="meal-preferences" hidden={!settingsMatch('급식 보기 식사 조식 중식 석식 알레르기 번호', settingsQuery)} bind:open={settingsOpen.meals}><summary>급식 보기 설정</summary><div class="meal-preference-options" aria-label="표시할 식사"><span>표시할 식사</span>{#each mealTypes as type}<label><input type="checkbox" checked={enabledMealTypes.includes(type)} disabled={enabledMealTypes.length === 1 && enabledMealTypes.includes(type)} onchange={(event) => toggleMealType(type, event.currentTarget.checked)} />{type}</label>{/each}</div><label class="meal-number-toggle"><input type="checkbox" checked={showAllergenNumbers} onchange={(event) => setAllergenNumbersVisible(event.currentTarget.checked)} />메뉴의 알레르기 번호 표시</label><p>하루·주간 보기와 표시 설정은 이 브라우저에 저장돼요. 주의 알레르기 경고는 항상 표시됩니다.</p></details>
             <details class="allergy-settings" hidden={!settingsMatch('급식 알레르기 주의', settingsQuery)} bind:open={settingsOpen.allergies}><summary>급식 알레르기 설정 {allergySelection.length ? `(${allergySelection.length}개 선택)` : ''}</summary><div class="allergy-grid">{#each allergens as name, index}<label><input type="checkbox" checked={allergySelection.includes(index + 1)} onchange={(event) => toggleAllergy(index + 1, event.currentTarget.checked)} /><span>{index + 1}. {name}</span></label>{/each}</div><p>선택 항목은 이 브라우저에만 저장돼요. NEIS에서 알레르기가 표시되지 않았더라도 안전하다는 뜻은 아니에요.</p></details>
        </section>

<style>
.display-settings{margin:0 0 14px;border:1px solid var(--line);padding:0 14px}
.display-settings summary{min-height:44px;align-content:center;cursor:pointer;font-size:14px;font-weight:650}
.display-settings-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,210px),1fr));gap:12px;padding:12px 0}
.display-settings-grid label{display:grid;gap:5px;align-content:start;font-size:13px;color:var(--muted)}
.display-settings-grid input:not([type="checkbox"]),.display-settings-grid select{width:100%;min-height:44px;background:var(--surface);color:var(--ink);border:1px solid var(--line);padding:8px;font:inherit;font-size:14px}
.display-settings-grid input[type="color"]{cursor:pointer;padding:4px}
.display-settings-grid .display-toggle{display:flex;align-items:center;gap:9px;min-height:44px;cursor:pointer}
.display-settings-grid .display-reset{align-self:end;min-height:44px}
.settings-backup{margin:0 0 14px;padding:0 14px 14px;border:1px solid var(--line)}
.settings-backup summary{min-height:44px;align-content:center;cursor:pointer;font-size:14px;font-weight:650}
.settings-backup .lesson-time-actions{margin-top:0}
.settings-import{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-height:44px;font-size:14px;color:var(--ink)}
.settings-import input{max-width:100%;min-width:0;font-size:13px}
.settings-backup .state-inline{margin-top:10px}
@media(max-width:700px){.display-settings-grid input:not([type="checkbox"]),.display-settings-grid select{font-size:16px}}
.allergy-settings{border:1px solid var(--line);margin:0 0 16px;padding:0 14px}
.meal-preferences{border:1px solid var(--line);margin:0 0 12px;padding:0 14px}
.meal-preferences summary{cursor:pointer;font-size:14px;font-weight:700;min-height:44px;align-content:center}
.meal-preference-options{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:8px 0 12px}
.meal-preference-options>span{font-size:13px;color:var(--muted);margin-right:4px}
.meal-preference-options label,.meal-number-toggle{display:inline-flex;align-items:center;min-height:44px;gap:8px;font-size:14px;cursor:pointer}
.meal-preferences input{width:18px;height:18px;accent-color:var(--ink)}
.meal-preferences p{font-size:12px;line-height:1.6;color:var(--muted);margin:4px 0 12px}
.allergy-settings summary{cursor:pointer;font-size:14px;font-weight:700;min-height:44px;align-content:center}
.allergy-settings summary:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.allergy-settings p{font-size:12px;line-height:1.6;color:var(--muted);margin:12px 0}
.allergy-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-top:10px}
.allergy-grid label{display:flex;align-items:center;gap:8px;min-height:38px;font-size:14px;cursor:pointer}
.allergy-grid input{width:18px;height:18px;accent-color:var(--ink)}
@media(max-width:700px){.allergy-grid label{min-height:44px}}
</style>
