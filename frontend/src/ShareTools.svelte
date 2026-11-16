<script lang="ts">
  import Icon from './Icon.svelte';
  import type { School, SubscriptionMode } from './api';
  export let view: 'timetable' | 'meals' | 'settings';
  export let school: School | null;
  export let classActionsReady: boolean;
  export let apiNotConfigured: boolean;
  export let shareUrl: string;
  export let shareState: string;
  export let subscriptionUrl: string;
  export let subscriptionState: string;
  export let subscriptionPanelOpen: boolean;
  export let subscriptionMode: SubscriptionMode;
  export let subscriptionTimesConsent: boolean;
  export let canExport: boolean;
  export let exportBusy: boolean;
  export let shareClass: () => void;
  export let subscribeTimetable: () => void;
  export let exportTimetable: (format: 'PDF') => void;
  export let changeSubscriptionMode: (event: Event) => void;
  export let setSubscriptionTimesConsent: (value: boolean) => void;
  export let copySubscription: () => void;
</script>

<section class="secondary-actions" aria-label="공유" hidden={view !== 'timetable'}>
      {#if school}
        <div class="share-tools"><button class="secondary-button" disabled={!classActionsReady} onclick={shareClass} aria-expanded={classActionsReady && !!shareUrl}><Icon name="link" /> {classActionsReady && shareUrl ? '학급 링크 닫기' : '학급 링크 복사'}</button><button class="secondary-button" disabled={!classActionsReady || apiNotConfigured} onclick={subscribeTimetable} aria-expanded={classActionsReady && subscriptionPanelOpen}><Icon name="link" /> {classActionsReady && subscriptionPanelOpen ? '구독 링크 닫기' : '캘린더 구독 링크'}</button>{#if canExport}<button class="secondary-button" disabled={exportBusy} onclick={() => exportTimetable('PDF')}><Icon name="save" /> PDF 저장</button>{/if}<span role="status">{classActionsReady ? shareState || subscriptionState : ''}</span></div>
        {#if classActionsReady && shareUrl}<label class="shared-link">공유 링크<input type="text" readonly value={shareUrl} onfocus={(event) => event.currentTarget.select()} /></label>{/if}
        {#if classActionsReady && subscriptionPanelOpen}
          <div class="lesson-search-fields">
            <label>일정 표시 방식<select value={subscriptionMode} onchange={changeSubscriptionMode}><option value="summary">하루 요약</option><option value="periods">교시별 종일 일정</option><option value="timed">입력한 교시 시각</option></select></label>
          </div>
          {#if subscriptionMode === 'timed'}<label class="display-toggle"><input type="checkbox" checked={subscriptionTimesConsent} onchange={(event) => { setSubscriptionTimesConsent(event.currentTarget.checked); }} /> 입력한 교시 시각을 구독 URL에 포함하는 데 동의합니다.</label><p class="display-settings-hint">시각은 API 서버와 캘린더 서비스에 전달됩니다. 시각을 바꾸면 구독 URL을 다시 추가하세요. 입력하지 않은 교시는 ‘교시 시각 미설정’ 종일 일정으로 표시됩니다.</p>{/if}
          {#if subscriptionUrl}
          <label class="shared-link">시간표 구독 URL (이번 주·다음 주)<input type="text" readonly value={subscriptionUrl} onfocus={(event) => event.currentTarget.select()} /></label>
          <button type="button" class="secondary-button" onclick={copySubscription}><Icon name="link" /> 구독 링크 복사</button>
          {/if}
        {/if}
      {/if}
    </section>

<style>
.secondary-actions{border-top:1px solid var(--line);margin-top:28px;padding-top:20px}
.share-tools{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:16px;font-size:14px}.shared-link{display:grid;gap:4px;margin-bottom:20px}.shared-link input{width:100%;min-height:44px;padding:8px 12px;border:1px solid var(--line);background:var(--surface);color:var(--ink)}
@media(max-width:700px){.share-tools{margin-bottom:8px;gap:6px}.share-tools .secondary-button{min-height:38px;padding:5px 9px;font-size:12px}}
</style>
