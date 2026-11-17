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
            <label>일정 표시 방식<select value={subscriptionMode} onchange={changeSubscriptionMode} aria-describedby="subscription-example"><option value="summary">하루 시간표 묶기</option><option value="periods">수업별로 표시 (시간 미지정)</option><option value="timed">실제 수업 시간에 표시</option></select></label>
          </div>
          <div id="subscription-example" class="subscription-example" aria-live="polite">
            <strong>캘린더 표시 예시</strong>
            {#if subscriptionMode === 'summary'}
              <p>하루의 수업을 종일 일정 하나로 묶어요.</p><div>종일 · 학교 1학년 1반 · 2개 수업<br /><small>일정 내용: 1교시 수학, 2교시 국어</small></div>
            {:else if subscriptionMode === 'periods'}
              <p>수업마다 시간 없는 종일 일정을 만들어요.</p><div>종일 · 1교시 수학<br />종일 · 2교시 국어</div>
            {:else}
              <p>설정한 시작·종료 시각으로 수업별 일정을 만들어요.</p><div>09:00–09:50 · 1교시 수학<br />종일 · 2교시 국어 <small>(시각 미설정)</small></div>
            {/if}
            <small>학교·학급·시각·과목은 설명을 위한 예시예요.</small>
          </div>
          {#if subscriptionMode === 'timed'}<label class="display-toggle"><input type="checkbox" checked={subscriptionTimesConsent} onchange={(event) => { setSubscriptionTimesConsent(event.currentTarget.checked); }} /> 입력한 교시 시각을 구독 URL에 포함하는 데 동의합니다.</label><p class="display-settings-hint">시각은 API 서버와 캘린더 서비스에 전달됩니다. 시각을 바꾸면 구독 URL을 다시 추가하세요. 입력하지 않은 교시는 ‘교시 시각 미설정’ 종일 일정으로 표시됩니다.</p>{/if}
          {#if subscriptionUrl}
          <label class="shared-link">시간표 구독 URL (이번 주·다음 주)<input type="text" readonly value={subscriptionUrl} onfocus={(event) => event.currentTarget.select()} /></label>
          <button type="button" class="secondary-button" onclick={copySubscription}><Icon name="link" /> 구독 링크 복사</button>
          {/if}
        {/if}
      {/if}
      <p><a href="./embed-builder.html">시간표 위젯 만들기</a></p>
    </section>

<style>
.secondary-actions{border-top:1px solid var(--line);margin-top:28px;padding-top:20px}
.share-tools{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:16px;font-size:14px}.shared-link{display:grid;gap:4px;margin-bottom:20px}.shared-link input{width:100%;min-height:44px;padding:8px 12px;border:1px solid var(--line);background:var(--surface);color:var(--ink)}
.subscription-example{margin:8px 0 16px;padding:12px;border:1px solid var(--line);font-size:13px;line-height:1.6;overflow-wrap:anywhere}.subscription-example p{margin:4px 0 8px;color:var(--muted)}.subscription-example small{color:var(--muted)}
@media(max-width:700px){.share-tools{margin-bottom:8px;gap:6px}.share-tools .secondary-button{min-height:38px;padding:5px 9px;font-size:12px}}
</style>
