<script lang="ts">
  import { addDays, pasteDate } from './date';
  import { displaySubject, displayTeacher, type DisplaySettings } from './personalization';
  import type { TimetableRecord } from './api';
  import type { LessonTimes, dailyLessonOverview } from './lesson-times';
  export let week: string;
  export let selectedDay: string;
  export let today: string;
  export let selectedClassLessons: TimetableRecord[];
  export let shownClassLessons: TimetableRecord[];
  export let dayOverview: ReturnType<typeof dailyLessonOverview>;
  export let displaySettings: DisplaySettings;
  export let lessonTimes: LessonTimes;
  export let selectTimetableDate: (event: Event, editing?: boolean) => void;
  export let dateText: (value: string, options?: Intl.DateTimeFormatOptions) => string;
  export let subjectStyle: (subject: string | null | undefined) => string | undefined;
</script>

<div class="day-picker"><label for="today-date">날짜</label><input id="today-date" type="date" min={week} max={addDays(week, 6)} value={selectedDay} onpaste={pasteDate} onchange={(event) => selectTimetableDate(event, true)} onblur={selectTimetableDate} onkeydown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} /><span>{selectedDay === today ? '오늘' : dateText(selectedDay, { weekday: 'long' })}</span></div>
            {#if selectedClassLessons.length}
              <div class="day-summary" aria-live="polite">
                <span>총 {dayOverview.total}교시</span>
                {#if displaySettings.showChangeBadges && dayOverview.changed}<span>변동 {dayOverview.changed}교시</span>{/if}
                {#if selectedDay === today}
                  {#if dayOverview.timed}
                    <span>남은 수업 {dayOverview.remaining}교시</span>
                    {#if dayOverview.current}<strong>현재 {dayOverview.current.period}교시 · {dayOverview.current.lessons.map((lesson) => displaySubject(lesson.subject, displaySettings)).join(' / ')}</strong>{:else if !dayOverview.next}<span>오늘 수업 종료</span>{/if}
                    {#if dayOverview.next}<strong>다음 {dayOverview.next.period}교시 · {dayOverview.next.lessons.map((lesson) => displaySubject(lesson.subject, displaySettings)).join(' / ')} <small>{dayOverview.next.time.start} 시작</small></strong>{/if}
                  {:else}<span>교시 시각 설정 후 현재·다음 수업을 볼 수 있어요.</span>{/if}
                {/if}
              </div>
              <div class="lesson-list" class:density-compact={displaySettings.density === 'compact'} class:density-relaxed={displaySettings.density === 'relaxed'} aria-label="선택한 날짜 시간표">
                {#each shownClassLessons as item}
                  <article class:active-lesson={dayOverview.current?.period === Number(item.period)} class:completed-lesson={displaySettings.endedLessonMode === 'dim' && dayOverview.completed.includes(Number(item.period))} class:changed={displaySettings.showChangeHighlights && item.isChanged}>
                    <span class="lesson-period">{item.period}교시{#if lessonTimes[Number(item.period)]}<small class="lesson-time">{lessonTimes[Number(item.period)].start}–{lessonTimes[Number(item.period)].end}</small>{/if}</span>
                    <strong style={subjectStyle(item.subject)}>{displaySubject(item.subject, displaySettings)}</strong>
                    {#if displaySettings.showTeachers && item.teacher}<span>{displayTeacher(item.teacher, displaySettings)}</span>{/if}
                    {#if item.isChanged && displaySettings.showChangeBadges}<span class="change-label">변동</span>{/if}
                  </article>
                {/each}
              </div>
              {#if !shownClassLessons.length}<p class="state-inline" role="status">종료된 수업을 모두 숨겼어요. 표시 설정에서 다시 볼 수 있어요.</p>{/if}
            {:else}<div class="state-message"><strong>이 날짜의 시간표가 없어요</strong><p>다른 날짜를 선택하거나 주간 반 시간표를 확인해 주세요.</p></div>{/if}
