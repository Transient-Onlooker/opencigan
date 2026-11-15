<script lang="ts">
  export let grade: number;
  export let classroom: number;
  export let gradeOptions: number[];
  export let availableClasses: number[];
  export let tableLoading: boolean;
  export let selectGrade: (event: Event) => void;
  export let selectClass: (event: Event) => void;
</script>

<div class="quick-class" aria-label="학급 빠른 전환">
  <label>학년 <select value={grade} onchange={selectGrade}>{#each gradeOptions as n}<option value={n}>{n}학년</option>{/each}</select></label>
  <label>반 <select value={classroom} onchange={selectClass}>{#if !availableClasses.length}<option value={Number(classroom)}>{classroom}반</option>{/if}{#each availableClasses as n}<option value={n}>{n}반</option>{/each}</select></label>
  {#if !availableClasses.length}<span class="quick-class-hint">{tableLoading ? '학급 정보를 불러오는 중이에요.' : '이 학년의 학급 정보가 없어요.'}</span>{/if}
</div>
