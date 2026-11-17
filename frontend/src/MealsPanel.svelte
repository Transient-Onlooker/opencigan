<script lang="ts">
  import MealMenu from './MealMenu.svelte';
  import { addDays, pasteDate } from './date';
  import type { Meal, NeisSchool, School } from './api';
  import type { MealAllergyFilter } from './meal-filter';
  export let view: 'timetable' | 'meals' | 'settings';
  export let mealDate: string;
  export let today: string;
  export let mealView: 'day' | 'week';
  export let mealDates: string[];
  export let mealDateDraft: string;
  export let dateError: string;
  export let neis: NeisSchool | null;
  export let school: School | null;
  export let neisSearchState: string;
  export let neisLoading: boolean;
  export let neisResults: NeisSchool[];
  export let mealState: string;
  export let hasMeals: boolean;
  export let mealLoading: boolean;
  export let meals: Meal[];
  export let visibleMealTypes: string[];
  export let allergySelection: number[];
  export let mealAllergyFilter: MealAllergyFilter;
  export let openAllergySettings: () => void;
  export let showAllergenNumbers: boolean;
  export let current: string;
  export let mealsStale: boolean;
  export let todayMeals: () => void;
  export let setMealView: (value: 'day' | 'week') => void;
  export let changeMealDate: (delta: number) => void;
  export let dateText: (date: string, options?: Intl.DateTimeFormatOptions) => string;
  export let updateMealDateDraft: (event: Event) => void;
  export let selectMealDate: (event: Event, editing?: boolean) => void;
  export let chooseNeis: (school: NeisSchool) => void;
  export let connectMeals: () => Promise<void>;
  export let loadMeals: (preserve?: boolean) => void;
  export let selectMealTimetableDate: (value: string) => void;
</script>

<section id="meals-panel" hidden={view !== 'meals'} aria-labelledby="meals-title">
          <div class="section-heading"><div><p class="eyebrow">{mealDate === today ? '오늘의 식단' : '하루 식단'}</p><h2 id="meals-title">학교 급식</h2></div><button class="secondary-button" onclick={todayMeals}>오늘로</button></div>
          <div class="view-switch" role="group" aria-label="급식 보기"><button aria-pressed={mealView === 'day'} onclick={() => setMealView('day')}>하루 식단</button><button aria-pressed={mealView === 'week'} onclick={() => setMealView('week')}>주간 식단</button></div>
          <div class="calendar-toolbar"><button class="arrow-button" onclick={() => changeMealDate(mealView === 'week' ? -7 : -1)} aria-label={mealView === 'week' ? '이전 급식 주' : '이전 날짜'}>←</button><div class="calendar-date"><strong aria-live="polite">{mealView === 'week' ? dateText(mealDates[0]) + ' — ' + dateText(mealDates[6]) : dateText(mealDate, { month: 'long', day: 'numeric', weekday: 'long' })}</strong><label class="date-picker">날짜 선택 <input type="date" min="1900-01-01" max="9999-12-31" value={mealDateDraft} oninput={updateMealDateDraft} onpaste={pasteDate} onchange={(event) => selectMealDate(event, true)} onblur={selectMealDate} onkeydown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} aria-invalid={!!dateError} aria-describedby={dateError ? 'meal-date-error' : undefined} /></label></div><button class="arrow-button" onclick={() => changeMealDate(mealView === 'week' ? 7 : 1)} aria-label={mealView === 'week' ? '다음 급식 주' : '다음 날짜'}>→</button></div>
          {#if dateError}<p id="meal-date-error" class="notice" role="alert">{dateError}</p>{/if}
          {#if mealAllergyFilter !== 'all'}
            <p class="meal-filter-note">알레르기 필터 적용 중 · 선택한 알레르기 {allergySelection.length}개 · {mealAllergyFilter === 'marked' ? '표시된 메뉴만' : '미표시 메뉴만'} 표시. 미표시 메뉴도 안전을 보장하지 않습니다.{!allergySelection.length ? ' 주의 알레르기를 선택해 주세요.' : ''} <button type="button" class="text-button" onclick={openAllergySettings}>알레르기 설정</button></p>
          {/if}
           <div class="meal-connection" aria-live="polite">{!neis && school ? neisSearchState : ''}</div>
          {#if !school}<div class="state-message"><strong>학교를 먼저 선택해 주세요</strong><p>시간표 학교를 선택하면 급식도 함께 연결돼요.</p></div>
          {:else if neisLoading}<div class="state-message" role="status">같은 학교의 급식을 연결하고 있어요.</div>
          {:else if !neis}
            <div class="connection-options">{#each neisResults as item (item.id)}<button class="school-option" onclick={() => chooseNeis(item)}><strong>{item.name}</strong><span>{item.address}</span></button>{/each}<button class="text-button" onclick={() => connectMeals()}>급식 연결 다시 시도</button></div>
           {:else}
            {#if mealState}<div class="notice" role="alert">{hasMeals ? '이전 급식 정보를 표시하고 있어요. ' : ''}{mealState} <button class="text-button" onclick={() => loadMeals(true)}>다시 시도</button></div>{/if}
            {#if mealLoading && hasMeals}<p class="state-inline" role="status">새 식단을 확인하는 동안 이전 식단을 표시하고 있어요.</p>{/if}
            {#if mealLoading && !hasMeals}<div class="state-message" role="status">식단을 불러오고 있어요.</div>
            {:else if hasMeals}
               <MealMenu
                 {meals}
                 dates={mealView === 'week' ? mealDates : [mealDate]}
                 {today}
                 visibleTypes={visibleMealTypes}
                 {allergySelection}
                 allergyFilter={mealAllergyFilter}
                 {showAllergenNumbers}
                 timetableFrom={current}
                 timetableTo={addDays(current, 13)}
                 formatDate={(date) => dateText(date, { month: 'numeric', day: 'numeric', weekday: 'long' })}
                 onDateSelect={selectMealTimetableDate}
               />
            {/if}
            {#if mealsStale}<p class="notice">저장된 급식 정보예요. 최신 정보가 아닐 수 있습니다.</p>{/if}
          {/if}
        </section>

<style>
.meal-connection{font-size:14px;color:var(--muted);margin:0 0 18px;overflow-wrap:anywhere}
.meal-connection:empty{display:none}
.meal-filter-note{margin:0 0 14px;color:var(--muted);font-size:12px;line-height:1.6;overflow-wrap:anywhere}.meal-filter-note button{min-height:44px}
</style>
