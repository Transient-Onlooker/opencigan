# P0 · 핵심 기능과 공개 전 품질

> 시간표·API 기반, 운영 전에 확인해야 할 품질과 보안 게이트를 정리합니다. 체크박스 **[x]는 코드 구현 기록**이지 운영 배포·실기기 QA 완료를 뜻하지 않습니다. [전체 개요](../roadmap.md)로 돌아가기.

## P0 — 핵심 시간표와 API 기반

**현재 코드에 구현됨**

- [x] 오늘/우리 반 주간/학년 비교/교사 검색 시간표 UI
- [x] 시간표 원본의 변경 표시(`isChanged`), 원본 갱신·수집 시각
- [x] 프로세스별 30분 캐시와 동일 키 single-flight, 이전 값 유지·실패 후 backoff
- [x] 프런트엔드 주간 메모리 캐시 (최대 4개 학교·주, 30분 유효, 만료·수동 새로고침 시 재검증)
- [x] Python `/api/v1` 읽기 API, JSON 오류 코드, OpenAPI 3.1, 내부망 API Playground
- [x] 프로세스별 IP당 60회/60초 요청 제한과 Origin 기반 CORS
- [x] 관측 스냅샷 비교·이력 조회 API 및 프런트엔드 UI (SQLite 저장은 기본 꺼짐)

**공개 전 필요**

### P0 — Cloudflare Pages + Workers VPC + Tunnel · 비공개 API·봇 방어

> **2026-11-16 설계 정정:** MCVKR은 타사 서브도메인 서비스이고 `mcv.kr` DNS zone은 사용자 소유가 아니다. **Cloudflare zone 네임서버 이전 및 `opencigan-api.mcv.kr` 직접 생성은 계획에서 제외.** [단계별 P0 실행 체크리스트](../cloudflare-tunnel-rollout.md).

- [ ] **P0 · Pages 정적 배포 및 Functions 경로:** 기존 GitHub Pages와 별개로 Cloudflare Pages의 `<project>.pages.dev`에서 UI·정적 자산·`/api/v1/*` Functions 라우트를 검증. 외부 CNAME은 마지막에만 변경.
- [ ] **P0 · Cloudflare Tunnel 비공개 백엔드:** Pi `cloudflared` QUIC 연결 → Workers VPC Service (`127.0.0.1:8000`) → Worker의 VPC Service binding을 구성. **일반 Tunnel Published Application 공개 DNS를 요구하지 않는 방식**으로 구현·테스트. 현재 Free/Beta 가용성 확인 필요.
- [ ] **P0 · Pages Functions → Worker 연결:** Pages Service Binding으로 Worker를 호출, Worker는 VPC Service로 Pi에 전달. 기존 JSON API·HEAD/OPTIONS·CORS·ETag/304·ICS/급식/시간표/관리자 인증 계약 유지.
- [ ] **P0 · 봇/남용 방어:** `mcv.kr` zone WAF는 직접 설정할 수 없으므로 Worker 레벨 경로 검증, 요청량 제한(Rate Limiting binding), 캐시/요청 폭주 방어를 사용. 학교 검색·시간표·급식·ICS·관리/웹훅별 정책 구분, 정상 캘린더/API 사용자를 Challenge로 막지 않기.
- [ ] **P0 · IP 신뢰·보안 경계:** Worker→VPC→Pi로 원본 클라이언트 IP가 안전하게 전달되도록 설계·검증. 현재 `resolve_client_ip()`는 `CF-Connecting-IP`를 직접 파싱하지 않음. 외부망 두 곳에서 IP별 제한/접속 로그 검증, 사용자 제공 XFF·Forwarded 신뢰 금지.
- [ ] **P0 · 최종 CNAME 연결:** Cloudflare Pages Custom domains에 `opencigan.mcv.kr`을 등록하고 **MCVKR CNAME만 `<project>.pages.dev`로 변경**. 기존 `mcv.kr` 전체 NS나 다른 서브도메인 DNS는 변경하지 않음. 외부 TLS, 서비스, ICS 구독 갱신 확인.
- [ ] **NEW-02 · 공개 API/ICS URL 정상화:** 같은 `https://opencigan.mcv.kr/api/v1/...` 경로로 API/ICS 제공; 기존 Tailscale `.ts.net` 구독 URL의 이전/재등록 방안과 혼합 버전 운영 검증.
- [ ] **P0 · 롤백/베타 가용성:** Cloudflare Pages / Worker VPC Beta / cloudflared 연결 장애, 429·503, 캐시·원본 가용성을 분리하고 기존 GitHub Pages·Tailscale Funnel·Pi WARP 출구 프록시로 단계별 복구 가능하게 유지.

**별도 출구 경로:** 컴시간 전용 `OPENCIGAN_COMCIGAN_PROXY`/WARP는 Pi에서 컴시간으로 나가는 경로로 유지하고, Tunnel 수신 구조와 섞지 않는다.

**2026-11-16 QA 후속 ([결함 NEW-01~09](../qa-2026-11-16.md))**

- [ ] **NEW-01 (P0 사용자 진입 차단): 반복 503 원인 규명**. `upstream_unavailable`은 `backend/app.py`의 포괄적인 예외 처리 결과라 컴시간 장애로 단정 불가. 실제 예외 로그·원본 연결·캐시 상태·셔터 `service_overloaded`·IP 제한 `rate_limited`을 구분해 재현하고, 검색·다음 주·타 학교 조회의 복구를 검증. `/api/v1/status`의 프로세스 생존 계약 유지, 별도 upstream/readiness 관측 설계.
- [ ] **NEW-01 장애 UX와 캐시 전용 표시**: 원본에 접근하지 못하면 학교 검색/시간표에 정확한 사유와 재시도 안내, 기존 캐시의 학교·주·수집 시각/오래된 데이터 표시, 미보유 캐시의 한계 안내. 정상 급식 등 별도 제공처는 불필요하게 차단하지 않고 mock 기반 장애·복구 E2E 추가. 요청 제한·서버 과부하·원본 및 API 연결 오류의 안내 문구 구분은 구현했으며 캐시 복구와 E2E는 남음.
- [ ] **NEW-08 원본 사실 대조**: 2026-11-19 수능일 보인고 시간표 7교시와 NEIS 급식 미등록을 컴시간 원문·NEIS 원문·학교 운영 일정으로 각각 검증. 단순 불일치만으로 서비스 파싱 버그 단정 금지.

- [x] 시간표·급식·설정·검색·즐겨찾기·공유·저장·새로고침 등 여러 메뉴와 주요 버튼에 직관적인 아이콘을 추가하고, PC·모바일에서 아이콘 스타일과 배치를 통일 (2026-11-15 로컬 구현·브라우저 회귀)

- [ ] 프록시/Tunnel 경유 시 실제 클라이언트별 호출 제한 검증 (로컬 WSGI에서 제한과 접속 로그가 같은 IP를 사용하는지 확인; 실제 외부망 두 곳에서의 검증은 남음)
- [ ] Tailscale Funnel·Cloudflare Tunnel 등 신뢰된 프록시를 거쳐도 실제 접속자 공인 IP를 서버가 인식하고, IP별 요청 제한·접속 로그에 반영하도록 개선
- [ ] 전체 시간표/급식 및 모바일 실기기 회귀 검증
- [ ] [2026-11-14 실사용 브라우저 QA](../browser-qa-2026-11-14.md)의 날짜 입력·외부 학교/학급 공유 링크 검증·시간표 공백 사유 표시 개선 (날짜·공유 회귀와 평일 전체 공백 안내 완료; 제보 당시 원본 확인은 남음)
- [ ] 변경 이력 저장의 실서비스 사용 정책 및 스키마 정합성 검증 (복수 수업 스냅샷·기존 DB 마이그레이션 회귀 완료; 운영 정책·복구 절차 검증 남음)
- [ ] 공개 API 운영 정책·원본 데이터 재제공 조건 확인
- [x] 학교·학년·반을 바꿔도 시간표, PNG, 공유 링크와 캘린더 구독의 대상 학급이 일치하도록 개선 (공유 복원·주차 검증 대기·내보내기 및 링크 대상 Chromium·WebKit 회귀)
- [x] 한 날짜·교시에 복수 수업 레코드가 있을 때 일반 주간 시간표와 학년 비교에서 수업이 누락되지 않도록 표시 개선 (복수 레코드·변동 배지 회귀 테스트)
- [ ] 모바일 고정 하단 메뉴가 마지막 수업·검색 결과·입력창을 가리지 않도록 레이아웃 개선 (320px 세로·667px 가로 화면과 입력 포커스 자동 검사 완료; 실기기 키보드·회전은 남음)
- [ ] 캘린더 구독 공개 도메인(\`opencigan.mcv.kr\`) 외부 접근성 검증 (해당 도메인은 Pages 404; 기존 Tailscale 구독 주소는 ETag·304 외부 확인 완료)
- [ ] 모바일 실기기(iOS Safari, Android Chrome) 및 캘린더 앱(Apple Calendar, Google Calendar) 구독 연동 검증 (실기기 게이트)
