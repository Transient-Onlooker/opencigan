<script lang="ts">
  export let name: 'settings' | 'save' | 'share' | 'link' | 'star' | 'close' | 'search' | 'school' | 'refresh';
  const paths = {
    settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 3v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4',
    save: 'M5 3h12l4 4v14H3V3h2Zm2 0v6h10V3M7 21v-8h10v8',
    share: 'M12 16V3m-5 5 5-5 5 5M5 13H3v8h18v-8h-2',
    link: 'm10 13 4-4M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 1 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0',
    star: 'm12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z',
    close: 'm6 6 12 12M6 18 18 6',
    search: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14m5 12 6 6',
    school: 'm3 10 9-7 9 7v11H3V10Zm6 11v-7h6v7M9 10h6',
    refresh: 'M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 14 0l1 4M4 12l1 4a8 8 0 0 0 14 0',
  };
</script>

<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>
