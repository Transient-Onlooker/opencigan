<script lang="ts">
  import type { TimetableChange } from './api';
  export let historyOpen: boolean;
  export let historyDisabled: boolean;
  export let historyLoading: boolean;
  export let historyError: string;
  export let historyChanges: TimetableChange[];
  export let visibleHistory: TimetableChange[];
  export let historyCursor: string | null;
  export let historyScope: 'class' | 'school';
  export let toggleHistory: () => void;
  export let loadHistory: (append?: boolean) => Promise<void>;
  export let dateText: (value: string) => string;
  export let timeText: (value: string | null | undefined) => string;
  export let changeTypeText: (value: string) => string;
</script>

<section class="history-section" aria-labelledby="history-title">
              <div class="history-heading">
                <div><h3 id="history-title">시간표 변경 이력</h3><p>선택한 주에 실제로 수집된 변경 기록</p></div>
                <button class="secondary-button" aria-expanded={historyOpen} aria-controls="history-list" onclick={toggleHistory}>{historyOpen ? '이력 닫기' : '이력 보기'}</button>
              </div>
              <div id="history-list" hidden={!historyOpen}>
                {#if historyDisabled}<p class="state-inline">변경 이력 저장이 아직 활성화되지 않았어요.</p>
                {:else if historyLoading && !historyChanges.length}<p class="state-inline" role="status">변경 이력을 불러오는 중…</p>
                {:else if historyError}<div class="notice" role="alert">{historyError} <button class="text-button" onclick={() => loadHistory()}>다시 시도</button></div>
                {:else if historyChanges.length}
                  <div class="history-filters lesson-search-fields"><label>비교 범위<select bind:value={historyScope}><option value="class">현재 학급</option><option value="school">학교 전체</option></select></label></div>
                  {#if visibleHistory.length}
                    <ol class="history-list">
                      {#each visibleHistory as change}
                        <li>
                          <div><strong>{change.grade}학년 {change.class}반 · {dateText(change.date)} · {change.period}교시</strong><span>{timeText(change.observedAt)} 확인 · {changeTypeText(change.type)}</span></div>
                          <p><span><strong>변경 전</strong> {change.before ? [change.before.subject, change.before.teacher].filter(Boolean).join(' · ') : '수업 없음'}</span>
                          <span><strong>변경 후</strong> {change.after ? [change.after.subject, change.after.teacher].filter(Boolean).join(' · ') : '수업 없음'}</span></p>
                        </li>
                      {/each}
                    </ol>
                  {:else}
                    <p class="state-inline">{historyCursor ? '불러온 기록에 현재 학급의 변경이 없어요.' : '이 주에 수집된 현재 학급의 변경 기록이 없어요.'}</p>
                  {/if}
                  {#if historyCursor}<button class="secondary-button history-more" disabled={historyLoading} onclick={() => loadHistory(true)}>{historyLoading ? '불러오는 중…' : '이전 변경 더 보기'}</button>{/if}
                {:else if !historyLoading}<p class="state-inline">이 주에 수집된 변경 기록이 없어요.</p>{/if}
              </div>
            </section>
