<script lang="ts">
  const sha = import.meta.env.VITE_BUILD_SHA;
  const build = typeof sha === 'string' && /^[0-9a-f]{7,40}$/i.test(sha) ? sha.slice(0, 7) : '';
</script>

{#if build}<p class="build-info">웹 버전 {build}</p>{/if}

<style>
  .build-info{margin:8px 0;color:var(--muted);font-size:12px}
</style>
