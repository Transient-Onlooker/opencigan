# P2 · API와 외부 개발자 연동

> API·캘린더·관리자·접속 로그, 공개 네트워크/터널 검증을 정리합니다. 체크박스 **[x]는 코드 구현 기록**이지 운영 배포·실기기 QA 완료를 뜻하지 않습니다. [전체 개요](../roadmap.md)로 돌아가기.

## P2 — 외부 개발자 연동


**2026-11-16 운영 QA 후속** ([NEW-01/02 원인·공개 게이트](../qa-2026-11-16.md))

- [ ] **NEW-02 (출시 필수): 공개 API·ICS 주소 확립**. QA에서 캘린더 기본 주소가 `rpi.tail9802be.ts.net`을 사용하고 `opencigan.mcv.kr/api/v1/timetable.ics`는 Pages 404임을 확인. 공개 API 호스트/프록시·DNS/TLS·CORS·ICS ETag/304·외부 캘린더 갱신을 검증한 뒤 생성 URL·API 문서를 일치시킬 것. 운영/Tailscale 주소를 외부 사용자에게 기본값으로 노출하지 않기.
- [ ] **NEW-01 (가용성 계측): 프로세스 생존과 외부 의존성 구분**. `/api/v1/status`의 `scope=process liveness` 기존 계약을 보존하고 상류/readiness의 별도 진단 지표·에러 분류·시간대별 실패율/캐시 적중 관측을 추가 검토. 공통 `upstream_unavailable` 코드의 서버 로그 내 원인을 확인할 수 있게 하고 민감한 요청 정보·토큰 노출 금지.

- [x] 시간표 필터 API (`grade`, `class`, `teacher`, 기존 학교·주간 캐시 재사용)
- [x] iCalendar(.ics) 구독 URL (선택한 학급, 현재/다음 주 자동 이동, 학교·주별 캐시 재사용, 로컬에서 하루 요약과 교시별 종일 일정 모드 지원; 실제 수업 시작·종료 시각 연동은 후속 과제)
- [x] iframe 임베드 위젯·Embed Builder (2026-11-15: 실제 학년·반 선택, 복수 수업·20교시, 안전한 문자열 표시·취소 경합 브라우저 회귀 검증.)
- [x] TypeScript/Python 경량 클라이언트, 실행 예제 및 모의 HTTP 경계 회귀 (2026-11-15)
- [x] AI Agent Skill(`agent-skill/SKILL.md`), `llms.txt` (실제 API 계약·식별자·조회 범위·개인정보 경계 안내)
- [ ] 공개 API 버전/하위 호환성 정책, 요청량·지연·오류 모니터링
- [ ] Tailscale Funnel과 Cloudflare Tunnel의 실제 TTFB·전체 응답 시간을 같은 OpenCigan API(`/api/v1/status`, 캐시된 시간표)로 비교 테스트하고, 한국 접속 환경에서 평균·중앙값·p95 및 거점(ICN/NRT 등)·측정 조건·결과를 `docs/` 벤치마크 보고서에 기록하여 터널 선택에 반영
- [ ] Cloudflare Tunnel을 Tailscale Funnel의 대안으로 검토: Raspberry Pi `cloudflared` → 로컬 API(`127.0.0.1:8000`) 연결, `opencigan.mcv.kr` DNS/TLS, 웹·API·ICS 접근, Cloudflare WAF·요청 제한, 접속 로그의 원본 IP 인식을 시험
- [ ] Tailscale Funnel의 대역폭 제한과 Cloudflare Tunnel의 플랜·사용 정책·트래픽/요청 제한을 비교하고, 터널별 지연·안정성·보안·운영 편의성을 종합하여 사용 방식 결정
- [x] 캘린더 구독(.ics)에 ETag·조건부 요청을 지원해 변경되지 않은 일정의 중복 다운로드 감소 (SHA-256 ETag 및 If-None-Match 304 로컬 구현 완료; 공개 서버 외부 접근 및 클라이언트별 재검증 대기)
- [x] 사용자 동의를 받은 교시 시각 URL 전달 및 `mode=timed` 일정 구현. 한국 시각 입력·표시를 유지하고 ICS는 UTC 순간으로 직렬화. 공개 API 배포·실제 캘린더 동기화는 별도 게이트.
- [x] 신규 API 필터·캘린더 구독을 Playground에서 바로 시험하고 OpenAPI 명세와 실제 응답 일치 여부 자동 검사 (필터·교시 시각 Playground Chromium·WebKit 검증, 공개 읽기 API 성공 응답 및 시간표 오류·캘린더 200/304 계약 검사. 모든 오류 사례를 망라하지는 않음)
- [x] API 운영 통계에서 캐시 적중률과 데이터 조회 실패·과부하 차단을 구분 (기록된 캐시 응답 기준, 기존 기록은 분모에서 제외)
- [x] 요청별 접속 로그 저장 — 접속 시각(KST), 원본 IP, 요청 방식·경로, 학교 식별자, 학년·반, 조회 날짜·주차, 데이터 종류, 응답 코드·처리 시간·캐시 상태 기록. 기본 비활성화이며 운영 활성화는 별도.
- [x] 웹사이트와 외부 API 요청을 Origin/Referer 출처로 분류·조회. 헤더가 없으면 unknown이며 조작 가능한 관측 신호로만 사용.
- [x] 관리자 접속 로그 검색 화면 — IP·학교·학급·날짜 범위·API 경로·응답 코드 필터, 시간순 커서 조회 및 CSV 내보내기. [사용법](../access-log-ui.md).
- [x] 별도 관리자 토큰, 기본 7일·최대 90일 보관 설정, 검색어·인증 토큰·전체 URL 제외. 비동기 기록·유실 집계. [설정 및 한계](../access-logs.md).

추가 구현: 선택적으로 활성화하는 90일 가명 이용 통계, API 요청량·오류율·평균 처리 시간과 토큰 인증 관리자 화면(`/analytics.html`). 수집 거부·비동기 큐·누락 수를 지원합니다. [집계 기준](../analytics.md)을 참고하세요. 공개 상태 페이지와 전체 모니터링 정책은 후속 작업입니다.

현재 이미 있는 기능: 기본 REST 계약, OpenAPI 3.1, 상대 경로 Playground, 관측 이력 API. **인터넷 공개 상태와는 별개**.
