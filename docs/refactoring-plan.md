# OpenCigan 리팩터링 실행 설계

> 이 문서는 [로드맵 배치 7](roadmap.md#배치-7-착수-조건과-리팩터링-순서)의 구체적인 구현 지침이다. **현재 수정 마무리 → RPi 적용 → QA 기준선 확정 후 착수**하며, 문서 작성 자체는 리팩터링 착수가 아니다.
> 코드 분석 기준: 2026-11-15, `main` 커밋 `54f89b935491a404dc251713ca652ad048b0599e`. 별도 에이전트가 코드를 계속 변경 중이므로 실행 시에는 최신 코드와 비교한다. 경로와 모듈명은 제안안이며 사용자 동작·테스트 계약 보존을 우선한다.

## 0. 안정 버전과 브랜치 운영

- 현재 작업을 완결하고 RPi API 및 LAN 미리보기에 반영한 정확한 **배포 커밋 SHA**, 실제 실행 서비스·설정, 이전 버전 복귀 위치를 기록한다. GitHub Pages 프런트 배포와 RPi API 배포는 서로 별개다.
- 학교·학급 전환, 날짜/주차, 공유 URL, 시간표·급식, 변경 이력, 개인 설정, 오프라인, PNG/PDF, ICS, 관리자·Webhook 등 **현재 사용 가능한 기능**의 QA 결과와 미확인 영역을 `docs/`에 기록한다. WebKit 실패 재현 여부, iOS/Android 실기기·외부망 검증 여부도 구분한다.
- QA에서 확인된 데이터 오류·P0/배포 차단 문제는 먼저 수정하고, 일반적인 재현 가능 문제는 재현 조건을 기록한 뒤 기준선에 포함한다. 모든 사소한 버그를 고칠 때까지 리팩터링을 미루지는 않는다.
- 안정 버전 커밋을 기준으로 `refactor/selection-state`, `refactor/timetable-session`처럼 **단계별 별도 브랜치**를 만든다. PR을 Draft로 열고 CI·코드 리뷰·해당 범위 E2E를 통과하면 Ready로 전환하여 순차 병합한다. 병합 전에는 `main`의 운영 배포를 그대로 유지한다.
- 대형 단일 PR·강제 푸시·운영 코드 동시 교체는 피한다. 브랜치에서 코드/테스트를 확인하더라도 RPi에 직접 자동 배포하지 않는다. 필요한 경우 QA용 독립 검수 인스턴스를 사용한다.
- 각 PR은 리팩터링만 한다. 기능·UI 재설계·API 응답 변경을 혼합하지 않는다. 리팩터링 중 발견한 버그 수정은 별도 커밋/PR 또는 테스트와 함께 이유를 명시한다. 다음 PR은 가급적 직전 PR 병합 후 최신 `main`에서 시작한다.

## 1. 실제 코드에서 확인된 결합 지점

| 코드 | 확인한 책임 | 위험 또는 분리 기준 |
| --- | --- | --- |
| `frontend/src/App.svelte` | 학교·학급·주차·탭·교사, 급식, 개인화, 저장, 내보내기, 공유/ICS, 이력, 캐시·오프라인, 브라우저 history, 다수 `$:` 반응형 계산 | 가장 먼저 **상태 소유권과 상태 전이**를 분리. JSX처럼 화면만 나누지 말 것 |
| `chooseSchool`, `ensureAvailableClass`, `restoreSharedClass`, `saveClass`/`saveGrade`, `applyNavigation` | 중복된 학급 결정, 저장, 공유 복원, 실패 복귀 | 하나의 선택 트랜잭션과 검증 경계를 구성 |
| `loadTimetable`, `timetableWeeks`, `tableRequest`, `onMount` | 요청 취소, 학교·주차 검증, 4개 주 캐시/TTL, 디바이스 오프라인 복원 | 선택과 분리된 인스턴스별 데이터 세션 |
| `connectMeals`, `chooseNeis`, `loadMeals` | NEIS 학교 연결, 요청 취소, 기간 캐시 | 시간표 선택 변경을 입력으로 받는 급식 세션 |
| `loadHistory`, `historyRequestKey` | 변경 이력 페이지네이션, stale 응답 방지 | 조회 전용 이력 세션 |
| `saveDisplaySettings`, `classDisplayDrafts`, `importSettingsFile`, `loadFavorites`, `onMount` | 학교/반별 로컬 저장·백업, 즐겨찾기, 설정 로드 | 저장소 키와 파싱 정책을 유지하면서 repository로 분리 |
| `backend/app.py` | 신뢰 프록시·제한, CORS·응답, 시간표/급식/ICS/이력, 관리자 통계·접속 로그, Webhook, WSGI·HTTP 진입점 | 공개 호환 API를 유지하며 route와 공통 HTTP 경계 분리 |
| `backend/access_logs.py` | 이미 `AccessLogStore`(SQLite·검색·CSV)와 `AccessLogRecorder`(비동기 큐) 두 클래스로 분리됨 | **클래스 내부 책임부터 검토**. 필요할 때만 파일 분리 |
| `backend/analytics.py` | `AnalyticsStore` + `ApiRecorder` | AccessLogRecorder와 유사한 큐 처리 패턴 확인. 불필요한 공통 추상화 생성 금지 |

이미 분리된 `frontend/src/navigation.ts`, `api.ts`, `date.ts`, `sharing.ts`, `personalization.ts`, `settings-backup.ts`, `lesson-times.ts`, `timetable-slots.ts`, `neis-match.ts`, `export-png.ts`, `personal-timetable.ts`는 **중복 구현하지 않고 재사용**한다. `PersonalTimetable.svelte` 및 `MealMenu.svelte`도 이미 별도 컴포넌트다.

## 2. 제안 구조 (완료 후의 책임 관계)

```text
frontend/src/
  App.svelte                         # 앱 구성·최상위 라이프사이클·컴포넌트 연결
  state/
    selection.ts                     # 학교/학년/반/주차 선택과 공유 복원, 실패 롤백
    timetable-session.ts             # 주간 요청 취소·검증·캐시·오프라인
    meal-session.ts                  # NEIS 연결·기간 데이터·요청 상태
    history-session.ts               # 변경 이력 요청·커서·취소
  storage/
    preferences.ts                   # 기존 localStorage 키/설정/즐겨찾기 저장 인터페이스
  selectors/
    timetable-view.ts                # 주간/일간/학년/교사 계산의 순수 함수
  components/
    SchoolSelector.svelte            # 학교 검색/학년·반 입력 및 오류 안내
    FavoritesBar.svelte              # 즐겨찾기 전환
    CalendarNav.svelte               # 탭/주차 메뉴·모바일 포커스
    TimetablePanel.svelte            # 시간표 화면의 조합
    TodayLessons.svelte              # 오늘 보기 (필요 시)
    WeekGrid.svelte                  # 주간 표 (필요 시)
    GradeComparison.svelte           # 학년 비교 (필요 시)
    TeacherTimetable.svelte          # 교사 보기 (필요 시)
    HistoryPanel.svelte              # 변경 이력 UI
    MealsPanel.svelte                # 기존 MealMenu 재사용
    SettingsPanel.svelte             # 학교·학급 개인화 및 백업
    ShareTools.svelte                # 학급 공유·ICS·PNG/PDF 버튼
  navigation.ts, api.ts, ...         # 기존 모듈 유지

backend/
  app.py                             # 기존 dispatch_request, make_app, Handler, serve 호환 진입점
  http_core.py                       # 공통 응답·CORS·HTTP 오류/메서드 처리 (필요한 경우)
  trusted_proxy.py                   # 신뢰 프록시 IP 해석·검증 (필요한 경우)
  routes/
    timetable.py                     # 검색·시간표·필터·이력
    calendar.py                      # ICS/RSS, ETag·304
    meals.py                         # NEIS 학교/급식
    analytics.py                     # 페이지뷰·관리자 통계
    admin.py                         # 관리자 접속 로그
    webhooks.py                      # 구독 등록/수정·테스트/삭제·인증
  cache.py, history.py, access_logs.py, ...  # 기존 데이터·저장 계층 우선 재사용
```

이는 **목표 책임 구조**이지 첫 PR에서 만들 파일 목록이 아니다. 패널을 더 잘게 나눌지, `http_core.py`와 `trusted_proxy.py`를 만들지는 실제 결합도와 테스트 결과를 보고 결정한다. 작은 함수 하나마다 새 파일을 만드는 것은 지양한다.

## 3. 단계별 실행 PR

### PR 0 — 기준선/특성 테스트만 추가 (`refactor/baseline-tests`)

- UI와 API 구현은 변경하지 않고 과거 회귀를 다시 재현 가능한 테스트로 고정한다.
- 테스트: 공유 학교의 ID/이름/지역 불일치, 미확인 반, `popstate`와 공유 복원 경합, 빠른 학교·학급·주차 전환, 늦은 응답 취소, 저장 실패, 오프라인 복원, 주간 캐시 만료, 여러 수업, PNG/PDF(다크 UI에서 PDF 흰색), ICS 동의·ETag, 급식 NEIS 다중 후보, 관리자 인증·429/503.
- Playwright의 기존 `frontend/e2e/selection-integrity.spec.js` 및 API 계약·WSGI 단위 테스트를 우선 활용한다. 실제 외부 데이터 테스트 대신 고정 응답으로 재현 가능하게 만든다.

### PR 1 — 선택 상태와 공유 복원 (`refactor/selection-state`)

- `App.svelte`의 `chooseSchool`, `ensureAvailableClass`, `cancelSharedSelection`, `restoreSharedClass`, `updateClass`, `saveClass`, `saveGrade`, `saveClassFromSelect`, `switchToFavorite`가 바꾸는 **학교·학년·반·주차** 상태를 단일 소유자로 모은다.
- 선택 전이 결과는 검증 전 `pending`, 확정 `committed`, 실패 `rolled back`으로 구분한다. 최신 학교·주차와 동일하지 않은 응답, 취소된 검색, 검증 실패 링크는 선택/저장/공유·ICS 활성화를 확정하지 않는다.
- 사용자 편집 초안(`classroomDraft`)과 적용된 반(`classroom`)을 구분한다. `applyNavigation`, `navigation.ts`와 `history.state`의 뒤로가기/앞으로가기·공유 fragment 충돌 방지를 유지한다.
- 저장소에 기록하는 경로는 하나로 모으되 기존 `opensigan-school`, `opensigan-grade`, `opensigan-class` 형식을 유지한다. 존재하지 않는 학급에 대한 조용한 강제 대체, 잘못된 링크로 저장값 오염 금지.
- 현재 Svelte 레거시 `$:` 반응성을 고려한다. `.ts`로 **변수만 복사해 비반응형 상태를 만들지 말고**, 컴포넌트 인스턴스별 소유 상태/명시적 subscribe 또는 기존 반응형 연결을 사용한다. 전역 singleton·상태 이중 소유 금지.

### PR 2 — 시간표 데이터 세션과 순수 선택자 (`refactor/timetable-session`)

- `loadTimetable`, `tableRequest`, `timetableWeeks`, `timetableRefreshAt`, `timetableFromDevice`를 요청 세션으로 이전한다. 요청 ID 또는 AbortController와 schoolId/week 검사 모두 유지한다.
- 기존 `(schoolId, week)`별 캐시, 30분 TTL, 4개 주 최대 유지, `preserve`/`reuseCachedWeek` 구분, 현재 UI 로딩·stale·오프라인 상태와 로컬 저장 키 `opensigan-offline-timetable` 유지.
- `$:`의 `filtered`, `selectedClassLessons`, `availableGrades`, `availableClasses`, `teacherNames`, `selectedTeacherRecords`, `missingWeekdays` 등 계산을 `selectors/timetable-view.ts`의 테스트 가능한 순수 함수로 순차 이동한다. 정렬·주말·복수 수업 순서·조회 범위를 고정한다.
- 선택 세션에서 '확정된 학교/주차'만 넘기도록 하고, 시간표 데이터 세션이 반 선택을 임의로 저장하거나 네비게이션을 직접 바꾸지 않게 한다.

### PR 3 — 급식/이력/저장 책임 (`refactor/secondary-state`)

- `connectMeals`, `chooseNeis`, `loadMeals`를 급식 세션에, `loadHistory`·커서·이력 취소를 별도 세션에 분리한다. 학교/주차 변경 시 재요청 조건과 요청 취소를 명시한다.
- 학교/학급별 표시 설정·교시 시각, 즐겨찾기, 급식 선호, 알레르기, 테마, 애니메이션, JSON 백업/복원을 `storage/preferences.ts` 등으로 정리한다. 기존 키·백업 스키마·저장 실패 롤백과 학급 기본값 상속을 보존한다.
- 저장 모델과 화면 편집 상태를 구분한다. `classDisplayDrafts`가 학교·반 교체에서 유효하지 않은 데이터를 붙잡지 않는지 회귀 검사한다.

### PR 4 — 화면 컴포넌트 (`refactor/ui-panels`)

- 먼저 `SchoolSelector`·`FavoritesBar`·`CalendarNav`를 추출한 후 `TimetablePanel`·`HistoryPanel`·`MealsPanel`·`SettingsPanel`·`ShareTools`를 순차 이동한다.
- 하위 컴포넌트는 **props/명시적 이벤트·콜백**으로 읽기/요청을 전달하고, 독립적으로 학교·반·시간표 원본을 저장하지 않는다. 전역 이벤트 버스나 큰 양방향 바인딩 객체를 만들지 않는다.
- 시간표의 오늘/주간/학년 비교/교사 보기는 필요할 때만 자식 컴포넌트로 분할. 기존 `MealMenu`와 `PersonalTimetable`은 재사용한다.
- DOM 계약 `#timetable-panel`, `#class-error`, `.quick-class`, `aria-label="캘린더 메뉴"`, `aria-pressed`/`hidden`/키보드 포커스를 보존하거나 같은 PR에서 E2E를 근거 있게 갱신한다. UI 픽셀/접근성 변경 최소화.

### PR 5 — CSS (`refactor/component-styles`)

- `style.css`의 base/theme/layout/공유 요소를 남기고 컴포넌트 전용 규칙을 점진적으로 이동한다. 중복 선택자·반응형 후행 override를 정리한다.
- Svelte 컴포넌트의 scoped CSS로 옮기면 `.app-shell.dark` 같은 부모 테마 선택자와 중첩 자식 스타일이 깨질 수 있으므로 `:global`, 상속 변수, 공유 class의 책임을 구분한다.
- 320px 모바일, 667px 가로, 데스크톱, 라이트/다크, 모바일 입력 포커스, 마지막 셀 가림, 긴 학급명과 복수 수업 표시를 확인한다. 형식·디자인 개편은 별도 PR.

### PR 6 — 백엔드 HTTP/라우팅 (`refactor/backend-routing`)

- `backend/app.py`의 `_dispatch_request`에서 학교 검색/시간표, ICS·RSS, NEIS, 분석, 관리자 접속 로그, Webhook 경로를 각각 `routes/`로 이전하고 공통 검증·헤더·JSON 오류 계약을 한 곳에 모은다.
- **호환 인터페이스를 유지**한다: `backend.app.dispatch_request`, `_dispatch_request`, `make_app`, `Handler`, `serve`, `resolve_client_ip`, `cache`, `_rate_clients` 등은 기존 테스트/도구에서 import 또는 patch한다. 특히 `tests/test_api.py`·`test_public_api.py`는 `backend.app.fetch_timetable`, `search_schools`, `NEISClient.from_environment`, `cache`를 patch하고 `test_access_log_api.py`는 `_dispatch_request`, `_access_log_store`, `_access_log_recorder`를 patch하므로 **route 분리 시 patch 지점이 끊어지기 쉽다**.
- 서비스 의존성은 필요 시 request context/provider로 주입하되 현재 호출 시점에 `backend.app`의 패치 가능 참조가 사용되도록 한다. 테스트를 업데이트하더라도 기존 의미의 통합 계약 테스트는 별도로 유지한다.
- WSGI와 직접 HTTP Handler의 동일 메서드·응답 계약, CORS/OPTIONS/HEAD, `Cache-Control`, `Retry-After`, IP 429, 셔터 503, 관리자 401/CSV, `ETag`/304, Webhook Body 제한·인증·서명, 캐시 상태/이력 기록 시점을 변경하지 않는다.
- 현재 사용 중인 `backend/cache.py`, `history.py`, `ical.py`, `neis.py`, `webhook_store.py`, `webhook_delivery.py`, `webhook_worker.py`, `analytics.py`, `access_logs.py` 등은 이번 단계에서 불필요하게 재작성하지 않는다.

### PR 7 — 로그/운영·기록 계층 (`refactor/logging-boundaries`, 필요할 때만)

- `AccessLogStore`와 `AccessLogRecorder`는 이미 독립 클래스로 구현됨. 같은 파일이라는 이유만으로 분할하지 않는다. 초기화·보존기간·동시 쓰기·종료/flush·CSV와 관리자 인증 결합도가 문제일 때 최소 변경한다.
- `ApiRecorder`와 공통 큐의 중복은 종료·유실 정책 차이를 확인한 뒤에만 통합한다. 개인정보 수집 범위·가명/원시 IP 구분·기본 비활성 정책을 변경하지 않는다.

2026-11-16 코드 확인: `AccessLogRecorder`는 입력 시각을 캡처하고 종료 상태·대기 중 작업 완료·시간 제한 종료를 제공한다. `ApiRecorder`는 지연 시작되는 데몬 큐이며 별도의 flush·close 계약이 없다. 종료 및 유실 동작이 다르므로 두 큐는 통합하지 않는다. 두 저장소도 기존 독립 클래스를 유지한다.

### PR 8 — 과거 코드·바이너리·번들 (`refactor/repository-cleanup`)

- `workers-api/`가 여전히 CI(`test_worker`, `test_d1_cache`, `test_migration`) 대상이므로 선행 참조 확인 없이 삭제하지 않는다. `phase0/`, `phase0-mvp/`와 wheelhouse는 재현·배포 의존성을 조사한 뒤 아카이브/삭제 여부 결정.
- Python/Workers 구현 차이는 공동 API 계약 테스트와 실제 배포 대상에 근거해 정리. 일괄 추상화나 무근거 통합을 하지 않는다.
- 원본·gzip·brotli JS/CSS 청크, PDF의 동적 `pdf-lib`, 폰트 전송량·필요 시 지연 로딩을 **실측**한다. 저장소 파일 크기와 사용자 브라우저 전송량을 구분한다.

#### 조사 기록 — 2026-11-16

- `workers-api/`는 CI의 Worker·D1·마이그레이션 테스트 대상이며, 별도 배포 설정과 재현 스크립트가 남아 있다. `phase0-mvp/`는 해당 재현 절차에서 도구 경로로 참조된다. 동일한 SHA-256의 `pycomcigan` 1.4.4 wheel 두 개는 Workers wheelhouse 하나를 참조하도록 통합하고 오프라인 잠금 검사를 통과했다. Workers용 `pycryptodomex` wheel은 재현 스크립트와 잠금 파일에서 참조하므로 보존한다.
- 프런트엔드 로컬 프로덕션 빌드 기준 주요 파일 크기(바이트, 원본 / gzip 기본값 / Brotli 품질 4)는 main JS 195,362 / 67,421 / 67,592, main CSS 88,870 / 22,906 / 21,715, 별도 `es` JS 청크 440,122 / 181,744 / 181,140이다. PDF 생성은 `export-png.ts`에서 `pdf-lib`를 동적 import한다.
- 빌드 디렉터리의 WOFF2는 92개 합계 2,957,724바이트다. 이는 저장된 산출물 총량이며, 사용자의 브라우저가 모두 내려받는다는 뜻은 아니다.
- 로컬 Chromium의 빈 캐시·서비스 워커 차단 상태에서 시간표 API를 고정 응답으로 대체해 실제 요청을 계측했다. 초기 화면에서 JS 4개 71,056바이트, CSS 1개 23,416바이트, WOFF2 13개 337,796바이트가 전송됐고, PDF 저장 시 별도의 JS 청크 1개 182,246바이트가 추가됐다. 값은 HTTP 헤더가 포함된 Chromium 네트워크 전송량이며 로컬 Vite 미리보기와 해당 화면·문자 집합에 한정된다. 운영 CDN의 압축과 실제 사용자 요청량은 확인하지 않았다.
- Python API와 Workers는 시간표 검색·기본 시간표 응답의 공통 필드를 동일한 고정 데이터로 비교하는 테스트를 공유한다. Python은 추가로 `cacheStatus`를 반환한다. Workers는 실험 구현으로 필터·이력·ICS·관리자 경로와 Python의 오류 코드 계약을 제공하지 않고, 급식의 영양·원산지 필드도 다르므로 두 구현을 완전한 대체재로 취급하거나 무근거로 합치지 않는다.
- 2026-11-16 `d9ebbe9` 기준 새 격리 스테이지에서 잠금된 의존성 동기화와 로컬 D1 스키마 초기화 후 Wrangler 4.159.0으로 Workers 번들을 기동했다. 상태 API는 200, 검색어 없는 학교 검색과 잘못된 학교 식별자는 각각 400을 반환했다. 원본 데이터 요청이나 원격 배포는 하지 않았으며 분산 D1·실제 Workers 운영 환경은 검증하지 않았다.

## 4. 모든 PR의 완료 조건

1. 해당 단계의 기존 동작/데이터/저장 키/API 계약 변화가 없거나, 차이가 있으면 명시적 승인과 별도 변경으로 분리한다.
2. `python -m unittest discover -s tests -v`, 관련 클라이언트·통합·Workers 테스트, `npm run check`, `npm test`, `npx playwright test`, `npm run build` 및 GitHub Actions의 결과를 확인한다. 실행하지 못한 항목은 미검증이라고 기록한다.
3. 학교/반·주차·공유·오프라인/저장·급식/ICS·PDF·관리자·Webhook의 리스크에 맞게 E2E/단위 테스트를 추가한다. 프런트·백엔드 독립 배포 상태에서도 혼합 버전 계약이 유지돼야 한다.
4. PR 본문에 **변경 대상, 이전/이후 책임, 영향받는 테스트, 잔여 위험, 롤백 방법**을 간결하게 적는다. 실패한 CI를 건너뛰거나 테스트를 삭제하여 녹색으로 만들지 않는다.
5. Merge 전 최신 `main`과의 충돌을 확인하고 리뷰 완료 후 병합한다. 병합 후에는 다음 단계를 새 브랜치로 시작한다. 운영 RPi 교체는 배포 절차와 별도의 QA 승인을 따른다.

## 5. 리팩터링 이후 재개할 작업

- 기존 로드맵 P0의 외부망 두 클라이언트 IP 식별·요청 제한, 실제 도메인 ICS/API, iOS/Android 및 캘린더 앱 검증은 리팩터링으로 자동 해결되지 않는다.
- Webhook/관리자·이력 기능은 현재 수정 중일 수 있으므로 기준선 커밋에 실제 존재하는 기능 목록을 확인하고 회귀 대상으로 포함한다.
- 제안 파일 이름과 컴포넌트 크기는 절대적인 목표가 아니다. **각 상태의 단일 소유권, 재현 가능한 회귀, 단계별 배포 가능성**이 완료 기준이다.
