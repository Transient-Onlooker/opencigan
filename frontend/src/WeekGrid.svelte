<script lang="ts">
  import Help from './Help.svelte';
  import { slotLessons } from './timetable-slots';
  import { displaySubject, displayTeacher, type DisplaySettings } from './personalization';
  import type { School, TimetableRecord, TimetableResponse } from './api';
  export let school: School;
  export let grade: number;
  export let classroom: number;
  export let dates: string[];
  export let today: string;
  export let week: string;
  export let current: string;
  export let periods: number[];
  export let filtered: TimetableRecord[];
  export let displaySettings: DisplaySettings;
  export let missingWeekdays: string[];
  export let timetable: TimetableResponse;
  export let timetableFromDevice: boolean;
  export let tableState: string;
  export let dateText: (value: string, options?: Intl.DateTimeFormatOptions) => string;
  export let subjectStyle: (subject: string | null | undefined) => string | undefined;
</script>

<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
            <div class="table-scroll" tabindex="0" role="region" aria-label="주간 시간표, 좌우로 스크롤 가능">
               <table class="timetable" class:no-cell-borders={!displaySettings.showCellBorders} class:density-compact={displaySettings.density === 'compact'} class:density-relaxed={displaySettings.density === 'relaxed'}><caption class="sr-only">{school.name} {grade}학년 {classroom}반 주간 시간표</caption><thead><tr><th scope="col">교시</th>{#each dates as date}<th scope="col" class:today-column={date === today} class:other-day={displaySettings.dimOtherDays && week === current && date !== today} aria-current={date === today ? 'date' : undefined}><span>{dateText(date, { weekday: 'short' })}</span>{#if displaySettings.showDates}<small>{dateText(date)}</small>{:else}<small class="sr-only">{dateText(date)}</small>{/if}{#if date === today}<span class="today-label">오늘</span>{/if}</th>{/each}</tr></thead>
                  <tbody>{#each periods as period}<tr><th scope="row">{period}<span class="sr-only">교시</span></th>{#each dates as date}{@const lessons = slotLessons(filtered, date, period)}<td class:today-column={date === today} class:other-day={displaySettings.dimOtherDays && week === current && date !== today} class:changed={displaySettings.showChangeHighlights && lessons.some((lesson) => lesson.isChanged)}>{#each lessons as lesson}<div class="class-cell"><strong style={subjectStyle(lesson.subject)}>{displaySubject(lesson.subject, displaySettings)}</strong>{#if displaySettings.showTeachers && lesson.teacher}<span>{displayTeacher(lesson.teacher, displaySettings)}</span>{/if}{#if lesson.isChanged && displaySettings.showChangeBadges}<span class="change-label">변동</span>{/if}</div>{:else}<span class="empty-cell" aria-label="수업 없음">—</span>{/each}</td>{/each}</tr>{/each}</tbody>
              </table>
            </div>
            {#if missingWeekdays.length}<p class="table-hint" role="status">수업 기록이 없는 평일: {missingWeekdays.map((date) => dateText(date, { weekday: 'long' })).join(', ')}. {timetable.stale || timetableFromDevice || tableState ? '저장된 시간표 기준이에요. ' : ''}휴업일인지 원본 자료가 비어 있는지는 확인할 수 없어요.</p>{/if}
            <div class="table-hint">빈 교시 <Help label="빈 교시" text="— 표시는 수집된 수업 기록이 없는 칸입니다. 휴업일인지, 원본 미제공인지, 일부 데이터가 누락됐는지는 확인되지 않습니다." /></div>
