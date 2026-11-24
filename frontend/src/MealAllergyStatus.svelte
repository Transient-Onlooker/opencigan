<script lang="ts">
  import type { MealAllergyFilter } from './meal-filter';
  export let selection: number[];
  export let filter: MealAllergyFilter;
  export let openSettings: () => void;
</script>

<p class="meal-filter-note">
  {filter === 'all' ? '모든 메뉴 표시 중' : '알레르기 필터 적용 중'} · 선택한 알레르기 {selection.length}개{filter === 'marked' ? ' · 표시된 메뉴만 표시' : filter === 'unmarked' ? ' · 미표시 메뉴만 표시' : ''}.
  미표시 메뉴도 안전을 보장하지 않습니다.{filter !== 'all' && !selection.length ? ' 주의 알레르기를 선택해 주세요.' : ''}
  <button type="button" class="text-button" onclick={openSettings}>알레르기 설정</button>
</p>

<style>
  .meal-filter-note{margin:0 0 14px;color:var(--muted);font-size:12px;line-height:1.6;overflow-wrap:anywhere}
  .meal-filter-note button{min-height:44px}
</style>
