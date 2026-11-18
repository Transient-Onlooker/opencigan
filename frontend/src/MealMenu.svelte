<script lang="ts">
  import type { Meal } from './api';
  import { allergenMatches, withoutAllergenNumbers } from './allergens';
  import { filterDishes, type MealAllergyFilter } from './meal-filter';

  let {
    meals,
    dates,
    today,
    visibleTypes,
    allergySelection,
    allergyFilter,
    showAllergenNumbers,
    timetableFrom,
    timetableTo,
    formatDate,
    onDateSelect,
  }: {
    meals: Meal[];
    dates: string[];
    today: string;
    visibleTypes: string[];
    allergySelection: number[];
    allergyFilter: MealAllergyFilter;
    showAllergenNumbers: boolean;
    timetableFrom: string;
    timetableTo: string;
    formatDate: (date: string) => string;
    onDateSelect?: (date: string) => void;
  } = $props();

  let query = $state('');

  function sourceText(value: string) {
    return value.replace(/<br\s*\/?>/gi, '\n');
  }
</script>

<div class="meal-filters" aria-label="급식 메뉴 검색 및 필터">
  <label>메뉴 검색<input type="search" maxlength="100" bind:value={query} placeholder="조회한 식단에서 검색" /></label>
</div>
<div class="meal-days">
  {#each dates as date (date)}
    <article class="meal-day" class:current={date === today} aria-label={date + ' 식단'}>
      <header>
        <h3>{formatDate(date)}{date === today ? ' · 오늘' : ''}</h3>
        {#if onDateSelect}
          {#if date >= timetableFrom && date <= timetableTo}
            <button type="button" onclick={() => onDateSelect?.(date)}>이 날짜 시간표</button>
          {:else}
            <span class="meal-range-note">시간표는 이번 주·다음 주만 조회할 수 있어요.</span>
          {/if}
        {/if}
      </header>
      {#if !meals.some((meal) => meal.date === date && visibleTypes.includes(meal.type))}
        <p class="meal-day-empty">{meals.some((meal) => meal.date === date) ? '표시하도록 설정한 식사에 등록된 식단이 없어요.' : '이 날짜에 등록된 식단이 없어요.'}</p>
      {:else}
        <div class="meal-types">
          {#each visibleTypes as type}
            {@const matchingMeals = meals.filter((meal) => meal.date === date && meal.type === type)}
            <section aria-label={date + ' ' + type}>
              <h4>{type}</h4>
              {#if !matchingMeals.length}
                <p>등록된 {type} 식단이 없어요.</p>
              {/if}
              {#each matchingMeals as meal}
                {@const dishes = filterDishes(meal.dishes, query, allergySelection, allergyFilter)}
                {#if dishes.length}
                  <ul>
                    {#each dishes as dish}
                      {@const matches = allergenMatches(dish, allergySelection)}
                      <li class:warning={matches.length > 0}>
                        {#if matches.length}<strong>⚠ 주의: {matches.map(({ id, name }) => `${id}. ${name}`).join(', ')}</strong>{/if}
                        <span>{showAllergenNumbers ? dish : withoutAllergenNumbers(dish)}</span>
                      </li>
                    {/each}
                  </ul>
                {:else}
                  <p class="meal-filter-empty" role="status">검색·필터에 맞는 메뉴가 없어요.</p>
                {/if}
                {#if meal.calories}<p class="meal-calories">열량(NEIS 원문): {sourceText(meal.calories)}</p>{/if}
                {#if meal.nutrition || meal.origin}
                  <details class="meal-source-details">
                    <summary>영양·원산지 정보</summary>
                    {#if meal.nutrition}<p class="meal-source-text">{sourceText(meal.nutrition)}</p>{/if}
                    {#if meal.origin}<p class="meal-source-text">원산지: {sourceText(meal.origin)}</p>{/if}
                    <p>NEIS에서 제공한 원문입니다. 제공되지 않은 값은 추정하지 않습니다.</p>
                  </details>
                {/if}
              {/each}
            </section>
          {/each}
        </div>
      {/if}
    </article>
  {/each}
</div>
<p class="meal-source">급식 정보 출처: 교육부·시도교육청, <a href="https://open.neis.go.kr/">나이스 교육정보 개방 포털</a></p>

<style>
  .meal-filters{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
  .meal-filters label{display:grid;gap:5px;flex:1;min-width:min(220px,100%);font-size:13px;font-weight:650}
  .meal-filters input,.meal-day button{width:100%;min-height:44px;max-width:100%;padding:8px 10px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit}
  .meal-day button{width:auto;cursor:pointer;font-size:13px}
  .meal-range-note{font-size:12px;color:var(--muted);line-height:1.6;overflow-wrap:anywhere}
  .meal-days{display:grid;gap:14px}
  .meal-day{min-width:0;border:1px solid var(--line)}
  .meal-day.current{border-color:var(--ink)}
  .meal-day>header{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line);background:var(--soft)}
  .meal-day h3{margin:0;font-size:16px}
  .meal-types{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(210px,100%),1fr))}
  .meal-types>section{min-width:0;padding:14px;border-right:1px solid var(--line)}
  .meal-types>section:last-child{border-right:0}
  .meal-types h4{margin:0 0 10px;font-size:15px}
  .meal-types ul{list-style:none;margin:0;padding:0}
  .meal-types li{padding:8px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere;line-height:1.6}
  .meal-types li span,.meal-types li strong{display:block}
  .meal-types li strong{font-size:12px}
  .meal-types li.warning{border-left:3px solid #c4263d;padding-left:8px;color:#a11125;background:#fff1f2}
  :global(.app-shell.dark) .meal-types li.warning{color:#ffc0ca;background:#34151d;border-color:#ff788d}
  .meal-day-empty,.meal-types p{margin:0;padding:12px 14px;color:var(--muted);font-size:13px;line-height:1.6;overflow-wrap:anywhere}
  .meal-types .meal-filter-empty{padding:8px 0}
  .meal-calories{margin:10px 0 0!important;padding:0!important;font-size:12px!important}
  .meal-source-details{margin-top:8px}
  .meal-source-details summary{min-height:44px;align-content:center;cursor:pointer;font-size:13px}
  .meal-source-text{white-space:pre-line;overflow-wrap:anywhere}
  .meal-source{margin:10px 0 0;color:var(--muted);font-size:13px;line-height:1.6;overflow-wrap:anywhere}
  .meal-source a{display:inline-flex;align-items:center;min-height:44px;color:var(--ink);text-underline-offset:3px}
  .meal-source a:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
  .meal-source-details:focus-within,.meal-day button:focus-visible,.meal-filters input:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
  @media(max-width:540px){.meal-types{grid-template-columns:1fr}.meal-types>section{border-right:0;border-bottom:1px solid var(--line)}.meal-types>section:last-child{border-bottom:0}}
</style>
