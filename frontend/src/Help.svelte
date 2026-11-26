<script lang="ts">
  import { onMount } from 'svelte';
  export let label: string;
  export let text: string;
  let open = false;
  let dismissed = false;
  let container: HTMLDivElement;
  onMount(() => {
    const dismissOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !container.contains(event.target)) open = false;
    };
    document.addEventListener('pointerdown', dismissOutside);
    return () => document.removeEventListener('pointerdown', dismissOutside);
  });
</script>

<div class="context-help" class:help-open={open} class:help-dismissed={dismissed} bind:this={container} onpointerleave={() => dismissed = false}>
  <button type="button" aria-label={label + ' 도움말'} aria-expanded={open} onclick={() => { dismissed = false; open = !open; }} onblur={() => open = false} onkeydown={(event) => { if (event.key === 'Escape') { open = false; dismissed = true; } }}>ⓘ</button>
  <p>{text}</p>
</div>
