<script lang="ts">
  import Icon from './Icon.svelte';
  import Help from './Help.svelte';
  import QuickClass from './QuickClass.svelte';
  import HistoryPanel from './HistoryPanel.svelte';
  import GradeComparison from './GradeComparison.svelte';
  import TeacherTimetable from './TeacherTimetable.svelte';
  import TodayLessons from './TodayLessons.svelte';
  import WeekGrid from './WeekGrid.svelte';
  import { addDays } from './date';
  import type { DisplaySettings } from './personalization';
  import type { School, TimetableRecord, TimetableResponse, TimetableChange } from './api';
  import type { LessonTimes, dailyLessonOverview } from './lesson-times';
  export let view: 'timetable' | 'meals' | 'settings';
  export let timetableView: 'today' | 'week' | 'grade' | 'teacher';
  export let school: School | null;
  export let timetable: TimetableResponse | null;
  export let week: string;
  export let current: string;
  export let today: string;
  export let selectedDay: string;
  export let grade: number;
  export let classroom: number;
  export let gradeOptions: number[];
  export let availableClasses: number[];
  export let tableLoading: boolean;
  export let tableState: string;
  export let tableRefreshState: string;
  export let timetableCheckedAt: string;
  export let timetableFromDevice: boolean;
  export let exportState: string;
  export let exportBusy: boolean;
  export let imageShareCancelled: boolean;
  export let canExport: boolean;
  export let weekendClasses: boolean;
  export let classError: boolean;
  export let sharedClassState: string;
  export let selectedClassLessons: TimetableRecord[];
  export let shownClassLessons: TimetableRecord[];
  export let dayOverview: ReturnType<typeof dailyLessonOverview>;
  export let displaySettings: DisplaySettings;
  export let lessonTimes: LessonTimes;
  export let comparableClasses: number[];
  export let gradeRecords: TimetableRecord[];
  export let teacherQuery: string;
  export let selectedTeacherName: string;
  export let selectedTeacherRecords: TimetableRecord[];
  export let teacherSuggestions: string[];
  export let teacherDates: string[];
  export let teacherPeriods: number[];
  export let dates: string[];
  export let periods: number[];
  export let filtered: TimetableRecord[];
  export let missingWeekdays: string[];
  export let observedClassCount: number;
  export let teacherNames: string[];
  export let historyOpen: boolean;
  export let historyDisabled: boolean;
  export let historyLoading: boolean;
  export let historyError: string;
  export let historyChanges: TimetableChange[];
  export let visibleHistory: TimetableChange[];
  export let historyCursor: string | null;
  export let historyScope: 'class' | 'school';
  export let exportTimetable: (format: 'PNG' | 'PDF') => Promise<void>;
  export let sharePng: () => Promise<void>;
  export let refreshTimetable: () => void;
  export let currentWeek: () => void;
  export let selectTimetableView: (value: 'today' | 'week' | 'grade' | 'teacher') => void;
  export let selectGrade: (event: Event) => void;
  export let selectClass: (event: Event) => void;
  export let changeWeek: (delta: number) => void;
  export let loadTimetable: (preserve?: boolean) => void;
  export let selectTimetableDate: (event: Event) => void;
  export let toggleHistory: () => void;
  export let loadHistory: (append?: boolean) => Promise<void>;
  export let dateText: (value: string, options?: Intl.DateTimeFormatOptions) => string;
  export let shortDate: (value: string) => string;
  export let timeText: (value: string | null | undefined, withSeconds?: boolean) => string;
  export let changeTypeText: (value: string) => string;
  export let subjectStyle: (subject: string | null | undefined) => string | undefined;
</script>

<section id="timetable-panel" hidden={view !== 'timetable'} aria-labelledby="timetable-title">
           <div class="section-heading"><div><p class="eyebrow">{week === current ? '이번 주' : '선택한 주'}</p><h2 id="timetable-title">시간표</h2></div><div class="heading-actions"><span class="last-fetched">{timetable ? '마지막 수집 ' + timeText(timetable.fetchedAt) : ''}</span>{#if timetable && timetableView !== 'grade'}<button class="secondary-button" disabled={!canExport || exportBusy} onclick={sharePng}><Icon name="share" /> 이미지 저장·공유</button>{/if}<button class="secondary-button refresh-button" disabled={!school || tableLoading} onclick={refreshTimetable} aria-label="현재 표시 중인 주의 시간표 새로고침"><svg class:spinning={tableLoading} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5"/><path d="M5.4 9a7.5 7.5 0 0 1 13.3-1.4L20 12M4 12l1.3 4.4A7.5 7.5 0 0 0 18.6 15"/></svg> {tableLoading ? '갱신 중' : '새로고침'}</button>{#if timetableView === 'today' && selectedDay !== today}<button class="secondary-button" onclick={currentWeek}>오늘로</button>{:else if timetableView !== 'today' && week !== current}<button class="secondary-button" onclick={currentWeek}>이번 주로</button>{/if}</div></div>
           {#if tableRefreshState && !(tableState && tableRefreshState === '새로고침 실패')}<p class="refresh-feedback" role="status">{tableRefreshState}{timetableCheckedAt ? ' · 마지막 확인 ' + timeText(timetableCheckedAt, true) : ''}</p>{/if}
           {#if exportState}<p class="export-feedback" role="status">{exportState}{#if imageShareCancelled && canExport} <button class="text-button" disabled={exportBusy} onclick={() => exportTimetable('PNG')}>PNG로 저장</button>{/if}</p>{/if}
           <div class="view-switch timetable-switch" role="group" aria-label="시간표 보기"><button aria-pressed={timetableView === 'today'} onclick={() => selectTimetableView('today')}>오늘</button><button aria-pressed={timetableView === 'week'} onclick={() => selectTimetableView('week')}>이번 주</button><button aria-pressed={timetableView === 'grade'} onclick={() => selectTimetableView('grade')}>{grade}학년</button><button aria-pressed={timetableView === 'teacher'} onclick={() => selectTimetableView('teacher')}>교사</button></div>
           {#if school}<QuickClass {grade} {classroom} {gradeOptions} {availableClasses} {tableLoading} {selectGrade} {selectClass} />{/if}
           <div class="calendar-toolbar"><button class="arrow-button" onclick={() => changeWeek(-1)} disabled={week <= current} aria-label="이전 주">←</button><div class="calendar-date" aria-live="polite"><strong>{shortDate(week)} ~ {shortDate(addDays(week, weekendClasses ? 6 : 4))}</strong></div><button class="arrow-button" onclick={() => changeWeek(1)} disabled={week >= addDays(current, 7)} aria-label="다음 주">→</button></div>
           <div class="quick-class-hint">이번 주·다음 주만 조회할 수 있어요. <Help label="시간표 조회 범위" text="원본 서비스가 제공하는 현재 주와 다음 주를 조회합니다. 과거 또는 더 먼 미래의 시간표는 제공하지 않아요." /></div>
          {#if tableState}<div class="notice" role="alert">{tableRefreshState === '새로고침 실패' ? '새로고침 실패. ' : ''}{timetable ? '이전 시간표를 표시하고 있어요. ' : '이 학교와 주에 저장된 시간표가 없어요. '}{tableState}{tableRefreshState === '새로고침 실패' && timetableCheckedAt ? ' · 마지막 확인 ' + timeText(timetableCheckedAt, true) : ''} <button class="text-button" onclick={() => loadTimetable(!!timetable)}>다시 시도</button></div>{/if}
          {#if tableLoading && timetable}<p class="state-inline" role="status">새 시간표를 확인하는 동안 이전 시간표를 표시하고 있어요.</p>{/if}
          {#if !school}<div class="state-message"><strong>학교를 먼저 선택해 주세요</strong><p>학교와 학급을 선택하면 시간표가 표시돼요.</p></div>
          {:else if tableLoading && !timetable}<div class="state-message" role="status"><strong>시간표를 불러오고 있어요.</strong></div>
          {:else if classError}<div class="state-message">{sharedClassState || '현재 선택은 유지했어요. 시간표에 등록된 반을 선택하거나 반 입력을 확인해 주세요.'}</div>
          {:else if timetable && timetableView === 'today'}
            <TodayLessons {week} {selectedDay} {today} {selectedClassLessons} {shownClassLessons} {dayOverview} {displaySettings} {lessonTimes} {selectTimetableDate} {dateText} {subjectStyle} />
          {:else if timetable && timetableView === 'grade'}
            <GradeComparison {school} {week} {selectedDay} {grade} {comparableClasses} {gradeRecords} {displaySettings} {selectTimetableDate} {dateText} {subjectStyle} />
           {:else if timetable && timetableView === 'teacher'}
             <TeacherTimetable bind:teacherQuery {selectedTeacherName} {selectedTeacherRecords} {teacherSuggestions} {teacherDates} {teacherPeriods} {displaySettings} {week} {current} {today} {dateText} {subjectStyle} />
          {:else if timetable && timetableView === 'week' && filtered.length}
            <WeekGrid {school} {grade} {classroom} {dates} {today} {week} {current} {periods} {filtered} {displaySettings} {missingWeekdays} {timetable} {timetableFromDevice} {tableState} {dateText} {subjectStyle} />
          {:else if !tableState}<div class="state-message"><strong>선택한 학급의 시간표 데이터가 없어요.</strong><p>학교와 학년·반을 확인해 주세요. 해당 기간의 원본 데이터가 제공되지 않은 이유는 확인되지 않습니다.</p></div>{/if}
           {#if timetable}<div class="freshness" aria-live="polite">{#if timetableFromDevice}<span>이 기기에 저장된 시간표 · 최신 정보가 아닐 수 있어요</span>{:else if timetable.stale}<span>저장된 시간표 · 최신 정보가 아닐 수 있어요</span>{/if}<span>원본 갱신 {timeText(timetable.sourceUpdatedAt)}</span></div>{/if}
           {#if timetable?.records.length}<details class="dataset-details"><summary>수업 데이터 규모 · 학급 {observedClassCount}개 · 교사 이름 {teacherNames.length}개</summary><p>선택한 주에 수집된 수업 기록 기준입니다. 학교 전체 학급·교사 수가 아닐 수 있고, 교사 이름 누락이나 동명이인이 있으면 실제 인원과 다를 수 있어요.</p></details>{/if}
          {#if timetable}
            <HistoryPanel {historyOpen} {historyDisabled} {historyLoading} {historyError} {historyChanges} {visibleHistory} {historyCursor} bind:historyScope {toggleHistory} {loadHistory} {dateText} {timeText} {changeTypeText} />
          {/if}
        </section>

<style>
.last-fetched{font-size:12px;color:var(--muted);white-space:nowrap}
.dataset-details{margin:8px 0 0;font-size:12px;color:var(--muted)}
.dataset-details summary{display:list-item;width:fit-content;min-height:36px;align-content:center;cursor:pointer}
.dataset-details summary:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.dataset-details p{margin:0 0 8px;line-height:1.6}
.refresh-button{display:inline-flex;align-items:center;gap:6px}
.refresh-button svg{width:17px;height:17px;flex:none}
.refresh-button svg.spinning{animation:refresh-spin .85s linear infinite}
@keyframes refresh-spin{to{transform:rotate(360deg)}}
.refresh-feedback{margin:-10px 0 10px;color:var(--muted);font-size:12px;text-align:right}
.export-feedback{margin:-6px 0 10px;color:var(--muted);font-size:12px;text-align:right}
@media(max-width:700px){.last-fetched{min-width:0;text-align:left;font-size:11px;flex:0 0 100%;white-space:normal;overflow-wrap:normal}}
</style>
