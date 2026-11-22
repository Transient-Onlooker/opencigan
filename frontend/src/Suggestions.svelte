<script lang="ts">
  import { onMount } from 'svelte';
  type Suggestion = { id: string; title: string; description: string; context: string | null };
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
  let available = false, busy = false, open = false;
  let query = '', title = '', description = '', context = '', status = '';
  let suggestions: Suggestion[] = [];
  let cursor: string | null = null;
  let active = true;
  let controller = new AbortController();

  async function search(append = false) {
    if (busy) return;
    busy = true; status = '';
    const params = new URLSearchParams();
    if (query.trim()) params.set('q', query.trim());
    if (append && cursor) params.set('cursor', cursor);
    try {
      const response = await fetch(`${base}/api/v1/suggestions?${params}`, { signal: controller.signal, cache: 'no-store' });
      if (!response.ok) throw new Error('제안 목록을 불러오지 못했어요. 다시 시도해 주세요.');
      const data = await response.json();
      if (!active || !Array.isArray(data.suggestions)) return;
      suggestions = append ? [...suggestions, ...data.suggestions] : data.suggestions;
      cursor = typeof data.nextCursor === 'string' ? data.nextCursor : null;
      available = true;
    } catch (error) {
      if (active && available) status = error instanceof Error ? error.message : '목록을 불러오지 못했어요.';
    } finally { if (active) busy = false; }
  }

  async function submit() {
    if (busy) return;
    if (!title.trim() || !description.trim()) { status = '제목과 내용을 입력해 주세요.'; return; }
    busy = true; status = '';
    try {
      const response = await fetch(`${base}/api/v1/suggestions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), description: description.trim(), context: context.trim() || null }),
        signal: controller.signal, cache: 'no-store',
      });
      if (!response.ok) {
        status = response.status === 409 ? '비슷한 제안이 최근에 접수됐어요.' : response.status === 429 ? '요청이 많아요. 잠시 후 다시 시도해 주세요.' : '제안을 보내지 못했어요. 다시 시도해 주세요.';
        return;
      }
      title = ''; description = ''; context = '';
      status = '제안을 접수했어요. 검토 후 공개 목록에 표시될 수 있어요.';
    } catch { if (active) status = '연결하지 못했어요. 다시 시도해 주세요.'; }
    finally { if (active) busy = false; }
  }
  onMount(() => { void search(); return () => { active = false; controller.abort(); }; });
</script>

{#if available}
  <details class="suggestions" bind:open>
    <summary>만들어주세요</summary>
    {#if open}
      <form class="search" onsubmit={(event) => { event.preventDefault(); void search(); }}>
        <label>공개 제안 검색<input type="search" maxlength="100" bind:value={query} /></label>
        <button type="submit" disabled={busy}>검색</button>
      </form>
      {#if suggestions.length}
        <ul>{#each suggestions as item (item.id)}<li><strong>{item.title}</strong><p>{item.description}</p>{#if item.context}<small>{item.context}</small>{/if}</li>{/each}</ul>
        {#if cursor}<button type="button" onclick={() => search(true)} disabled={busy}>더 보기</button>{/if}
      {:else}<p>공개된 제안이 없어요.</p>{/if}
      <form class="submit" onsubmit={(event) => { event.preventDefault(); void submit(); }}>
        <h3>새 제안</h3>
        <label>제목<input required maxlength="100" bind:value={title} /></label>
        <label>내용<textarea required maxlength="2000" rows="4" bind:value={description}></textarea></label>
        <label>어떻게 사용할 건가요? (선택)<textarea maxlength="500" rows="2" bind:value={context}></textarea></label>
        <p>개인정보를 입력하지 말아 주세요. 제안은 검토 후 공개될 수 있어요.</p>
        <button type="submit" disabled={busy}>제안 보내기</button>
      </form>
      <p role="status" aria-live="polite">{status}</p>
    {/if}
  </details>
{/if}

<style>
  .suggestions{border:1px solid var(--line);margin:12px 0;padding:12px;overflow-wrap:anywhere}
  summary{cursor:pointer;font-weight:700;min-height:44px;align-content:center}
  form,label{display:grid;gap:8px} form{margin:12px 0} label{font-weight:600}
  input,textarea{box-sizing:border-box;width:100%;min-width:0;padding:10px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit}
  button{min-height:44px;padding:8px 12px;border:1px solid var(--line);background:var(--surface);color:var(--ink);font:inherit;cursor:pointer}
  button:focus-visible,summary:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
  button:disabled{opacity:.6;cursor:wait} ul{list-style:none;padding:0} li{border-top:1px solid var(--line);padding:12px 0} li p{white-space:pre-wrap} small{color:var(--muted)}
</style>
