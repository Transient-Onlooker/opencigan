<script lang="ts">
  import Icon from './Icon.svelte';
  import type { School } from './api';
  type Favorite = { school: School; grade: number; classroom: number };
  export let school: School | null;
  export let grade: number;
  export let classroom: number;
  export let favorites: Favorite[];
  export let currentFavorite: boolean;
  export let disabled: boolean;
  export let addFavorite: () => void;
  export let removeFavorite: (favorite: Favorite) => void;
  export let switchToFavorite: (favorite: Favorite) => void;
  let favoritesExpanded = true;
</script>

{#if school || favorites.length}
  {#if school && !currentFavorite && favorites.length < 10}
    <div class="favorite-toolbar"><div class="favorite-save"><button class="secondary-button" {disabled} onclick={addFavorite}><Icon name="star" /> 현재 학급 즐겨찾기 추가</button></div></div>
  {/if}
  {#if favorites.length}
    <section class="favorites-bar" aria-labelledby="favorites-title">
      <div class="favorites-heading"><h2 id="favorites-title">즐겨찾는 학급 ({favorites.length})</h2><button class="text-button" aria-expanded={favoritesExpanded} aria-controls="favorite-list" onclick={() => favoritesExpanded = !favoritesExpanded}>{favoritesExpanded ? '목록 접기' : '목록 펼치기'}</button></div>
      <label class="favorite-picker">학급 바로 선택<select aria-label="즐겨찾는 학급 바로 선택" value="" onchange={(event) => { const selected = favorites[Number(event.currentTarget.value)]; if (event.currentTarget.value && selected) switchToFavorite(selected); event.currentTarget.value = ''; }}><option value="">즐겨찾는 학급을 선택하세요</option>{#each favorites as favorite, index}<option value={String(index)}>{favorite.school.name} {favorite.grade}학년 {favorite.classroom}반</option>{/each}</select></label>
      <div id="favorite-list" class="favorite-list" hidden={!favoritesExpanded}>
        {#each favorites as favorite (`${favorite.school.id}-${favorite.grade}-${favorite.classroom}`)}
          <div class="favorite-item">
            <button class="favorite-switch" aria-pressed={school?.id === favorite.school.id && Number(grade) === favorite.grade && Number(classroom) === favorite.classroom} onclick={() => switchToFavorite(favorite)}><strong>{favorite.school.name}</strong><span>{favorite.grade}학년 {favorite.classroom}반</span></button>
            <button class="favorite-remove" aria-label={`${favorite.school.name} ${favorite.grade}학년 ${favorite.classroom}반 즐겨찾기 삭제`} onclick={() => removeFavorite(favorite)}><Icon name="close" /></button>
          </div>
        {/each}
      </div>
    </section>
  {/if}
{/if}
{#if school && !favorites.length}<p class="quick-class-hint">즐겨찾는 학급이 없어요. 현재 학급을 추가하면 바로 전환할 수 있어요.</p>{/if}
