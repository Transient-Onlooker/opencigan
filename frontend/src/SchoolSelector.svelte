<script lang="ts">
  import Icon from './Icon.svelte';
  import type { School } from './api';
  export let schoolQuery: string;
  export let schoolResults: School[];
  export let schoolSearchState: string;
  export let grade: number;
  export let classroom: number;
  export let classroomDraft: string;
  export let gradeOptions: number[];
  export let classError: boolean;
  export let sharedClassState: string;
  export let findSchool: (event: Event) => void;
  export let cancelSearch: () => void;
  export let chooseSchool: (school: School) => void;
  export let selectGrade: (event: Event) => void;
  export let updateClass: (event: Event) => void;
  export let saveClass: (event: Event) => void;
</script>

<section id="school-settings" class="school-panel" aria-label="학교 및 학급 선택">
  <div class="search-field">
    <label for="school">학교 찾기</label>
    <div class="search-wrap"><Icon name="search" /><input id="school" type="search" maxlength="50" aria-describedby="school-search-help" bind:value={schoolQuery} oninput={findSchool} onkeydown={(event) => { if (event.key === 'Escape') cancelSearch(); }} placeholder="학교 이름 두 글자 이상" autocomplete="off" /></div>
    <p id="school-search-help" class="quick-class-hint">2~50자 · 결과는 최대 10개예요. 컴시간에서 제공하는 학교만 찾을 수 있어요.</p>
    <span class="sr-only" aria-live="polite">{schoolSearchState || (schoolResults.length ? schoolResults.length + '개 학교 검색 결과' : '')}</span>
    {#if schoolResults.length || schoolSearchState}
      <div class="search-results">
        {#each schoolResults as item (item.id)}<button class="school-option" onclick={() => chooseSchool(item)}><strong>{item.name}</strong><span>{item.region}</span></button>{/each}
        {#if schoolSearchState}<p>{schoolSearchState}</p>{/if}
      </div>
    {/if}
  </div>
  <div class="selectors">
    <label for="grade">학년<select id="grade" value={grade} onchange={selectGrade}>{#each gradeOptions as n}<option value={n}>{n}학년</option>{/each}</select></label>
    <label for="classroom">반<input id="classroom" type="number" min="1" max="99" step="1" required value={classroomDraft} oninput={updateClass} onchange={saveClass} aria-invalid={classError} aria-describedby={classError ? 'class-error' : 'class-selection'} /></label>
  </div>
  <p id="class-selection" class="quick-class-hint">현재 선택: {grade}학년 {classroom}반 · 반 입력은 편집을 마치면 적용돼요.</p>
  {#if classError}<p id="class-error" class="notice" role="alert">{sharedClassState || '1~99 사이의 반을 입력해 주세요. 시간표가 있는 경우 등록된 반만 선택할 수 있어요.'}</p>{/if}
</section>
