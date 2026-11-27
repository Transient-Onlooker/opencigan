<script lang="ts">
  import { displaySubject, displayTeacher, type DisplaySettings } from './personalization';
  import type { TimetableRecord } from './api';
  export let teacherQuery: string;
  export let selectedTeacherName: string;
  export let selectedTeacherRecords: TimetableRecord[];
  export let teacherSuggestions: string[];
  export let teacherDates: string[];
  export let teacherPeriods: number[];
  export let displaySettings: DisplaySettings;
  export let week: string;
  export let current: string;
  export let today: string;
  export let dateText: (value: string, options?: Intl.DateTimeFormatOptions) => string;
  export let subjectStyle: (subject: string | null | undefined) => string | undefined;
</script>

<label class="teacher-search" for="teacher-search">교사별 주간 시간표<input id="teacher-search" type="search" bind:value={teacherQuery} placeholder="교사 이름 입력 또는 목록에서 선택" autocomplete="off" /></label>
              {#if !selectedTeacherRecords.length && teacherSuggestions.length}<div class="teacher-options" aria-label="선택 가능한 교사 목록">{#each teacherSuggestions as teacherName}<button class="secondary-button" onclick={() => teacherQuery = teacherName}>{displayTeacher(teacherName, displaySettings)}</button>{/each}</div>{/if}
             {#if selectedTeacherRecords.length}
                <p class="table-hint">{displayTeacher(selectedTeacherName, displaySettings)} 선생님 · {week === current ? '이번 주' : '다음 주'} 수업 (동명이인은 원본 시간표에서 구분할 수 없어요.)</p>
               <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
                <div class="table-scroll" tabindex="0" role="region" aria-label={`${displayTeacher(selectedTeacherName, displaySettings)} 선생님 주간 시간표`}>
                   <table class="timetable teacher-table" class:no-cell-borders={!displaySettings.showCellBorders} class:density-compact={displaySettings.density === 'compact'} class:density-relaxed={displaySettings.density === 'relaxed'}><caption class="sr-only">{displayTeacher(selectedTeacherName, displaySettings)} 선생님 주간 시간표</caption><thead><tr><th scope="col">교시</th>{#each teacherDates as date}<th scope="col" class:other-day={displaySettings.dimOtherDays && week === current && date !== today}><span>{dateText(date, { weekday: 'short' })}</span>{#if displaySettings.showDates}<small>{dateText(date)}</small>{:else}<small class="sr-only">{dateText(date)}</small>{/if}</th>{/each}</tr></thead><tbody>{#each teacherPeriods as period}<tr><th scope="row">{period}교시</th>{#each teacherDates as date}{@const teacherLessons = selectedTeacherRecords.filter((r) => r.date === date && Number(r.period) === period)}<td class:other-day={displaySettings.dimOtherDays && week === current && date !== today} class:changed={displaySettings.showChangeHighlights && teacherLessons.some((lesson) => lesson.isChanged)}>{#each teacherLessons as item}<div class="class-cell"><strong><span>{item.grade}학년</span> <span>{item.class}반</span></strong><span style={subjectStyle(item.subject)}>{displaySubject(item.subject, displaySettings)}</span>{#if item.isChanged && displaySettings.showChangeBadges}<span class="change-label">변동</span>{/if}</div>{:else}<span class="empty-cell">—</span>{/each}</td>{/each}</tr>{/each}</tbody></table>
               </div>
             {:else if teacherQuery.trim() && !teacherSuggestions.length}<div class="state-message"><strong>이 주에 검색된 교사가 없어요</strong><p>다른 이름을 입력하거나 다른 주를 확인해 주세요.</p></div>{:else}<p class="table-hint">목록에서 이름을 고르면 월~금 시간표가 표시돼요.</p>{/if}

<style>
.teacher-search{display:flex;gap:10px;margin:0 0 16px;font-weight:650;align-items:stretch;flex-direction:column;max-width:440px}
.teacher-search input{min-height:44px;max-width:100%;border:1px solid var(--line);padding:8px 10px;color:var(--ink);background:var(--surface);width:100%;font-weight:400}
.teacher-options{display:flex;gap:8px;flex-wrap:wrap;max-height:190px;overflow-y:auto;overscroll-behavior:contain;margin:0 0 18px;padding:2px}
.teacher-options button{min-height:40px;padding:7px 12px}
</style>
