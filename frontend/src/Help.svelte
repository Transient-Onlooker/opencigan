<script lang="ts">
  export let label: string;
  export let text: string;
  let open = false;
</script>

<div class="context-help" class:help-open={open}>
  <button type="button" aria-label={label + ' 도움말'} aria-expanded={open} onclick={() => open = !open} onkeydown={(event) => { if (event.key === 'Escape') open = false; }}>ⓘ</button>
  <p>{text}</p>
</div>
