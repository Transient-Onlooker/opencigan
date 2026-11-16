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

<style>
.calendar-menu{display:flex;align-items:center;gap:6px;border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:24px}
.menu-label{margin-right:auto;padding-right:20px;font-size:14px;font-weight:750;color:var(--muted)}
.calendar-menu button{min-width:136px;min-height:48px;padding:10px 16px;border:1px solid transparent;border-radius:10px;background:var(--soft);color:var(--muted);font-size:15px;font-weight:750;transition:background-color .16s ease,color .16s ease,border-color .16s ease}
.calendar-menu button :global(.icon){margin-right:5px}
.calendar-menu button[aria-pressed=true]{color:var(--surface);background:var(--ink)}
.calendar-menu button:hover:not([aria-pressed=true]){color:var(--ink);border-color:var(--line);background:var(--surface)}
@media(max-width:700px){
  .calendar-menu{position:fixed;z-index:10;bottom:0;left:0;width:100%;margin:0;gap:6px;background:var(--surface);border-top:1px solid var(--line);border-bottom:0;box-shadow:0 -8px 24px rgba(0,0,0,.07);padding:8px calc(8px + env(safe-area-inset-right,0px)) calc(8px + env(safe-area-inset-bottom,0px)) calc(8px + env(safe-area-inset-left,0px))}
  .menu-label{display:none}
  .calendar-menu button{flex:1 1 0;min-width:0;min-height:56px;padding:8px 4px;font-size:15px;border-radius:9px}
  .calendar-menu button :global(.icon){margin-right:3px}
  .calendar-menu.input-focused{visibility:hidden;pointer-events:none}
}
</style>
