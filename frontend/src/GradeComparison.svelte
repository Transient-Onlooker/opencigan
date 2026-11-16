<script lang="ts">
  import { addDays } from './date';
  import { slotLessons } from './timetable-slots';
  import { displaySubject, displayTeacher, type DisplaySettings } from './personalization';
  import type { School, TimetableRecord } from './api';
  export let school: School;
  export let week: string;
  export let selectedDay: string;
  export let grade: number;
  export let comparableClasses: number[];
  export let gradeRecords: TimetableRecord[];
  export let displaySettings: DisplaySettings;
  export let selectTimetableDate: (event: Event, editing?: boolean) => void;
  export let dateText: (value: string, options?: Intl.DateTimeFormatOptions) => string;
  export let subjectStyle: (subject: string | null | undefined) => string | undefined;
</script>

<div class="day-picker"><label for="grade-date">비교 날짜</label><input id="grade-date" type="date" min={week} max={addDays(week, 6)} value={selectedDay} onchange={(event) => selectTimetableDate(event, true)} onblur={selectTimetableDate} onkeydown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} /></div>
            {#if comparableClasses.length}
              <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
               <div class="table-scroll grade-comparison-scroll" tabindex="0" role="region" aria-label={grade + '학년 학급별 비교 시간표'}><table class="timetable comparison-table" class:no-cell-borders={!displaySettings.showCellBorders} class:density-compact={displaySettings.density === 'compact'} class:density-relaxed={displaySettings.density === 'relaxed'}><caption class="sr-only">{school.name} {grade}학년 {dateText(selectedDay)} 학급별 교시 비교</caption><thead><tr><th scope="col">교시</th>{#each comparableClasses as classNumber}<th scope="col">{classNumber}반</th>{/each}</tr></thead><tbody>{#each Array.from({ length: Math.max(0, ...gradeRecords.map((item) => Number(item.period))) }, (_, index) => index + 1) as period}<tr><th scope="row">{period}교시</th>{#each comparableClasses as classNumber}{@const lessons = slotLessons(gradeRecords, selectedDay, period, classNumber)}<td class:changed={displaySettings.showChangeHighlights && lessons.some((lesson) => lesson.isChanged)}>{#each lessons as lesson}<div class="class-cell"><strong style={subjectStyle(lesson.subject)}>{displaySubject(lesson.subject, displaySettings)}</strong>{#if displaySettings.showTeachers && lesson.teacher}<span>{displayTeacher(lesson.teacher, displaySettings)}</span>{/if}{#if lesson.isChanged && displaySettings.showChangeBadges}<span class="change-label">변동</span>{/if}</div>{:else}<span class="empty-cell">—</span>{/each}</td>{/each}</tr>{/each}</tbody></table></div>
               <div class="grade-compact" class:no-cell-borders={!displaySettings.showCellBorders} class:density-compact={displaySettings.density === 'compact'} class:density-relaxed={displaySettings.density === 'relaxed'} aria-label={`${grade}학년 ${dateText(selectedDay)} 학급별 비교`}>
                 {#each Array.from({ length: Math.max(0, ...gradeRecords.map((item) => Number(item.period))) }, (_, index) => index + 1) as period}
                   <section class="grade-period"><h3>{period}교시</h3><div class="grade-class-grid">
                     {#each comparableClasses as classNumber}
                       {@const lessons = slotLessons(gradeRecords, selectedDay, period, classNumber)}
                        <div class="grade-class" class:changed={displaySettings.showChangeHighlights && lessons.some((lesson) => lesson.isChanged)}><h4>{classNumber}반</h4>
                          {#each lessons as lesson}<div class="class-cell"><strong style={subjectStyle(lesson.subject)}>{displaySubject(lesson.subject, displaySettings)}</strong>{#if displaySettings.showTeachers && lesson.teacher}<span>{displayTeacher(lesson.teacher, displaySettings)}</span>{/if}{#if lesson.isChanged && displaySettings.showChangeBadges}<span class="change-label">변동</span>{/if}</div>{:else}<span class="empty-cell">—</span>{/each}
                       </div>
                     {/each}
                   </div></section>
                 {/each}
               </div>
             {:else}<div class="state-message"><strong>비교할 시간표가 없어요</strong><p>선택한 날짜에 선택 학년의 수업이 없습니다.</p></div>{/if}

<style>
.grade-compact{display:none}
.grade-compact.no-cell-borders .grade-period,.grade-compact.no-cell-borders .grade-period h3,.grade-compact.no-cell-borders .grade-class{border:0}
.grade-compact.density-compact{gap:8px}
.grade-compact.density-compact .grade-class{padding:6px 8px}
.grade-compact.density-relaxed{gap:16px}
.grade-compact.density-relaxed .grade-class{padding:15px 12px}
@media(max-width:700px){
  .grade-comparison-scroll{display:none}.grade-compact{display:grid;gap:12px}.grade-period{border:1px solid var(--line);min-width:0}.grade-period h3{background:var(--soft);font-size:15px;padding:8px 12px;border-bottom:1px solid var(--line)}.grade-class-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))}.grade-class{min-width:0;padding:9px 10px;border-bottom:1px solid var(--line);border-right:1px solid var(--line);overflow-wrap:anywhere}.grade-class:nth-child(even){border-right:0}.grade-class:last-child,.grade-class:nth-last-child(2):nth-child(odd){border-bottom:0}.grade-class h4{font-size:13px;font-weight:800;margin:0 0 4px}.grade-class .class-cell{align-items:flex-start;gap:2px}.grade-class .class-cell strong{font-size:14px;line-height:1.4}.grade-class .class-cell>span{font-size:12px}.grade-class .class-cell+.class-cell{border-top:1px solid var(--line);margin-top:7px;padding-top:7px}.grade-class.changed{box-shadow:inset 3px 0 var(--ink)}
  .grade-class h4{white-space:nowrap}
}
</style>
