<script lang="ts">
  import Icon from './Icon.svelte';
  export let view: 'timetable' | 'meals' | 'settings';
  export let inputFocused: boolean;
  export let selectView: (value: 'timetable' | 'meals' | 'settings') => void;
</script>

<nav class="calendar-menu" class:input-focused={inputFocused} aria-label="캘린더 메뉴">
  <span class="menu-label">캘린더</span>
  <button aria-pressed={view === 'timetable'} aria-controls="timetable-panel" onclick={() => selectView('timetable')}><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="5" width="18" height="16"/><path d="M7 3v4m10-4v4M3 10h18M8 14h3m2 0h3m-8 3h3m2 0h3"/></svg> 시간표</button>
  <button aria-pressed={view === 'meals'} aria-controls="meals-panel" onclick={() => selectView('meals')}><svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 3v6a3 3 0 0 0 6 0V3M7 3v18M16 21V3c3 1 4 4 4 8h-4"/></svg> 급식</button>
  <button aria-pressed={view === 'settings'} aria-controls="settings-panel" onclick={() => selectView('settings')}><Icon name="settings" /> 설정</button>
</nav>
