<script lang="ts">
  import Icon from './Icon.svelte';
  import type { School } from './api';
  import type { Favorite } from './preferences';
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

<style>
  .favorite-save{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin:0 0 18px}
  .favorites-bar{border:1px solid var(--line);padding:16px;margin-bottom:20px;min-width:0}
  .favorites-heading{display:flex;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:12px}.favorites-heading h2{font-size:17px}
  .favorite-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(250px,100%),1fr));gap:8px}
  .favorite-picker{display:grid;gap:5px;margin:0 0 12px;font-size:13px;color:var(--muted)}
  .favorite-picker select{min-height:44px;max-width:100%;width:100%;border:1px solid var(--line);padding:8px;background:var(--surface);color:var(--ink)}
  .favorite-item{display:flex;min-width:0;border:1px solid var(--line)}
  .favorite-switch{display:flex;flex:1;flex-direction:column;align-items:flex-start;justify-content:center;min-width:0;min-height:52px;padding:9px 12px;text-align:left;border:0;background:var(--surface);color:var(--ink);overflow-wrap:anywhere}
  .favorite-switch strong{font-size:14px}.favorite-switch span{color:var(--muted);font-size:13px}.favorite-switch:hover{background:var(--soft)}
  .favorite-switch[aria-pressed=true]{background:var(--ink);color:var(--surface)}.favorite-switch[aria-pressed=true] span{color:var(--surface)}
  .favorite-remove{flex:none;width:44px;min-height:52px;border:0;border-left:1px solid var(--line);background:var(--surface);color:var(--ink);font-size:23px}.favorite-remove:hover{background:var(--soft)}
  @media(max-width:700px){
    .favorite-save{margin-bottom:8px;gap:6px}
    .favorite-save .secondary-button{min-height:38px;padding:5px 9px;font-size:12px}
    .favorites-bar{padding:10px;margin-bottom:12px}
    .favorite-picker select{font-size:16px}
  }
</style>
