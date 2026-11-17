# Cloudflare Pages + Workers VPC + Tunnel — P0 실행 로드맵

> **2026-11-17 사용자 업데이트:** `opencigan.mcv.kr`의 **Cloudflare Pages 이전은 완료됐다고 보고**됐다. 이미 기록된 Pages→Worker→VPC→Pi 기본 연결과 별개로, 현재 DNS/TLS·실제 IP·전체 API·ICS 및 캘린더 실기기 QA는 추후 검증해야 한다. MCVKR은 타사 서브도메인 제공자이며 `mcv.kr` zone 전체를 소유하지 않는다. [P0 로드맵](roadmap/core-quality.md) · [운영 가이드](operations.md) · [프록시 IP 신뢰 정책](proxy-client-ip.md) · [QA](qa-2026-11-16.md).

## 목표 아키텍처 — 사용자 제안 방식

```mermaid
flowchart TD
  User["브라우저 · API/ICS 클라이언트"] --> Host["opencigan.mcv.kr · MCVKR CNAME"]
  Host --> Pages["Cloudflare Pages · 정적 프런트 + Functions"]
  Pages -->|/api/v1/* · Service Binding| Worker["Cloudflare Worker · 제한/검증"]
  Worker -->|VPC Service binding| VPC["Workers VPC · 비공개 HTTP Service"]
  VPC --> Tunnel["Cloudflare Tunnel · cloudflared / QUIC"]
  Tunnel --> Pi["Pi · 127.0.0.1:8000"]
  Pi --> NEIS["NEIS · 기존 출구"]
  Pi --> WARP["컴시간 전용 WARP 출구"]
  WARP --> Comcigan["컴시간"]
```

**핵심:** Pages/Functions → Worker → Workers VPC → Pi Tunnel의 기본 연결이 구성되어 있고, 사용자에 따르면 공식 `opencigan.mcv.kr`도 Cloudflare Pages로 이전됐다. **ICS/공개 API의 기존 `.ts.net` 구독 URL은 사이트 이전만으로 자동 변경되지 않는다.** 신규 구독 호스트와 기존 구독자를 구분해 확인하고, `mcv.kr` zone 네임서버/별도 API 도메인은 변경하지 않는다.

- Cloudflare의 **일반 Tunnel Published Application**은 Cloudflare zone에서 관리되는 CNAME이 필요하므로 여기서는 사용하지 않는다. 외부 MCVKR DNS의 CNAME을 `<UUID>.cfargotunnel.com`에 단순 연결하는 방식도 동작한다고 가정하지 않는다.
- **Workers VPC**는 Cloudflare Tunnel을 비공개 원본 연결로 이용하는 별도 기능이다. 2026-11-16 기준 Free 플랜에서 이용 가능한 **베타** 기능이며 변경 가능성이 있으므로 먼저 계정에서 지원 여부 확인.
- Cloudflare Pages Function은 Worker의 **Service Binding**을 호출하고, Worker는 **VPC Service binding**을 호출한다. Pages Functions가 VPC binding을 직접 제공한다고 가정하지 않는다.
- **보안 범위:** 타사 DNS의 `mcv.kr` zone-wide Cloudflare WAF Rules는 이 계정에서 적용 불가. 대신 Worker의 Rate Limiting binding과 요청 검증/봇 남용 탐지, 기존 Pi의 429/셔터를 조합한다. 정식 WAF zone 정책이 필요해지면 소유 도메인 또는 DNS 위임을 별도 검토.

## Phase 0 — 기존 자산 보존 및 계정 확인

- [x] **2026-11-16 23:02 KST 읽기 전용 기록(PR #43):** 공용 DNS 확인 기준 `mcv.kr`의 NS는 `japan.linode.dns.mcv.kr`, `singapore.linode.dns.mcv.kr`; `opencigan.mcv.kr`은 `transient-onlooker.github.io`를 가리키는 CNAME. 이는 Cloudflare가 해당 zone을 관리한다는 뜻이 아니다.
- [x] **PR #43 읽기 전용 Pi 점검:** 로컬·기존 Funnel 상태 API 정상, WARP 전용 브리지 컴시간 1회 응답 200, 운영 Pi는 `release-warp-20261116` 기반 `54f89b9`(수정·미추적 운영 파일 포함). `cloudflared` 미설치/미발견; sudo 인증·계정 플랜은 미확인.
- [ ] **잘못 추가한 `mcv.kr` Cloudflare zone은 변경하지 말고 계정에서 정리**. DNS 40개 복사본 편집이나 NS 변경 시도 중단. MCVKR 제공 도메인 전체를 소유한 것이 아님.
- [ ] Cloudflare Workers & Pages 및 **Workers VPC** 메뉴 접근, Free 플랜/Connectivity Directory 권한 확인. VPC Beta를 계정에서 사용할 수 없으면 여기서 중단하고 기존 Funnel 유지.
- [ ] 기존 GitHub Pages 배포 설정(`API_BASE_URL`), MCVKR CNAME, Pi 앱·WARP systemd drop-in 및 Tailscale Funnel의 롤백 경로 기록. 토큰·관리 키는 저장소나 채팅에 공유하지 않음.

## Phase 1 — Cloudflare Pages를 기본 주소에서 시험

- [x] Svelte 프런트엔드 Cloudflare Pages 배포 구성 및 기본 주소 접근 기록. GitHub CI/Pages 배포 성공 및 상태 API 확인 기록에 근거하며, 캐시·SPA·PWA·아이콘·OG의 사후 실사용 QA는 Phase 4로 분리. 기존 GitHub Pages를 즉시 삭제하지 않음.
- [x] Pages 출처에서 `/api/v1/*` 같은 출처 라우팅을 사용하도록 구성·수정(PR #94 포함). 기본 상태 응답은 확인했고, 전체 라우트/정적 자산 충돌은 Phase 4 QA 대상으로 둠.
- [x] Pages Functions의 `/api/v1/*` → Service Binding → API Worker → VPC 연결 구성. 상태 200·입력 오류 400·HEAD/OPTIONS 기본 동작은 기록됨. 인증 헤더·쿼리·본문·ETag/304 등 전체 계약은 Phase 4 QA에 남김.

## Phase 2 — Pi Tunnel과 Workers VPC Service 연결

- [x] Pi에서 서비스 설정과 로컬 상태 API를 확인했다. 기존 컴시간 전용 WARP 설정은 유지했다.
- [x] 전용 터널과 Pi 사용자 서비스를 생성했다. `cloudflared` 2026.11.0, QUIC·UDP 연결 및 Cloudflare 터널 healthy 상태를 확인했다.
- [x] 비공개 HTTP 원본 `127.0.0.1:8000`을 VPC Service `opencigan-pi`로 등록했다. Service ID: `01a1e508-9473-7c43-b9ab-1b76b0600696`.
- [x] API Worker `opensigan-private-api`에 VPC Service를 `PRIVATE_API`로 연결했다. 공개 `workers.dev` 경로는 사용하지 않는다.
- [x] Pages Functions → Worker → VPC → Pi 경로에서 상태 API 200, 입력 오류 JSON 400, HEAD 200, OPTIONS 204를 확인했다. Pages 미리보기와 운영 환경에 서비스 바인딩을 설정했으며 `opencigan.pages.dev` 상태 API도 200을 반환했다.

2026-11-17 **초기 연결 기록(이전 시점의 기록)**: Pi의 사용자 서비스는 `opencigan-cloudflared.service`이고 터널 토큰은 Pi에 별도 보관한다. 당시 기존 Funnel/WARP를 유지하고 공식 CNAME을 바꾸지 않았으나, **이후 사용자가 `opencigan.mcv.kr`의 Pages 이전 완료를 보고**했다. 상태 API 응답은 프로세스 생존만 의미하므로 실제 클라이언트 IP·인증·ICS 및 전체 데이터 검증은 여전히 남는다.

```bash
systemctl --user status opensigan --no-pager
systemctl --user cat opensigan
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/status
command -v cloudflared && cloudflared --version
```

참고: Workers VPC는 Zero Trust 일반 Published Application의 DNS 라우팅과 다르다. Pi에서 프록시를 열거나 `mcv.kr` NS를 바꿀 필요가 없다.

## Phase 3 — API/봇 방어·실제 IP 검증

- [x] **Worker 경계에서 허용 경로·HTTP 메서드·요청 크기 검증** 구현. 알려진 API 경로와 메서드만 Pi로 전달하고 본문은 원본과 같은 4,096바이트로 제한한다. 관리/웹훅 인증은 원본에서 유지하며 범용 URL 프록시는 제공하지 않는다. 단위 테스트 완료; Worker 운영 배포와 실제 인증 경로 검증은 별도로 필요하다.
- [ ] **Workers Rate Limiting binding**으로 검색·시간표·ICS별 요청률 제한을 구현. 코드에는 일반 요청 상한과 별도의 시간표·캘린더 상한, JSON 429 및 `Retry-After`를 추가했다. 예시 값은 테스트용이며 실제 트래픽을 관측한 뒤 정하고 바인딩을 함께 배포해야 한다. 배포·관측은 미완료. 이 제한은 대략적·PoP별이며 엄밀한 전역 방어가 아니라 기존 Pi 제한과 함께 사용한다.
- [ ] ICS·공개 API에는 JS/Managed Challenge·Cloudflare Access 로그인 강제 적용 금지. 봇 차단이 정상 학생·캘린더/외부 클라이언트를 차단하지 않는지 검증.
- [ ] **IP 신뢰 경계:** Pages/Worker의 사용자가 보낸 `X-Forwarded-For`/`Forwarded`를 그대로 Pi에 전달하지 않는다. 실제 엣지 IP 정보 전달 방식을 명확히 설계하고 Worker→Pi 헤더 위변조·프록시 홉·`OPENCIGAN_TRUSTED_PROXIES`를 테스트. 현재 백엔드는 `CF-Connecting-IP`를 직접 사용하지 않음. 다른 외부망 2곳에서 IP별 로그·429 제한을 실측.
- [ ] **원본 API의 캐시·CORS·ETag·304·HEAD·웹훅 서명·관리자 인증 유지**, Worker 429와 Pi `429 rate_limited`, `503 service_overloaded`, `503 upstream_unavailable` 구분. Worker 자체 오류의 CORS와 `Retry-After` 노출은 허용 출처에 한해 구현·단위 테스트했다. Worker의 `ALLOWED_ORIGINS`를 Pi의 `ALLOWED_ORIGIN`과 맞춰 배포하고 실제 경로를 검증해야 한다.
- [ ] Cloudflare Pages의 사용자 지정 도메인에 적용되는 zone WAF는 `mcv.kr` zone의 소유자/운영자가 관리함. Workers 레벨 제한으로 가능한 것과 WAF 보호 범위의 차이를 문서화.

## Phase 4 — 공식 사이트 이전 완료 보고 및 실사용 QA

- [x] **`opencigan.mcv.kr`의 Cloudflare Pages 공식 사이트 이전**: 사용자가 작업 완료를 확인했다. 실제 CNAME 대상과 Pages Custom domains/TLS 설정값은 외부에서 독립 확인하지 못했으므로 아래 QA의 사후 검증 대상으로 둔다.

**2026-11-17 예정 QA (실행 전, 미완료)**

- [ ] Pages 기본 주소와 `opencigan.mcv.kr`의 DNS·TLS·정적 자산·SPA/PWA·캐시·공유·PNG/PDF 및 `/api/v1/status`·학교 검색·시간표·급식·관리자/알림·ICS가 각 호스트에서 정상인지 검증. 기존 GitHub Pages를 제거하지 않는다.
- [ ] 인증 헤더·쿼리·본문, CORS·HEAD/OPTIONS·ETag/304, 429/503 오류 계약과 Pages Functions의 정적 자산 충돌 여부를 실제 엔드포인트에서 확인한다.
- [ ] **공식 호스트 이전 사후 QA:** HTTPS 인증서·커스텀 도메인 Pages 라우팅, 기존 공유 링크·OG 미리보기·리다이렉트·PWA/Service Worker 캐시를 확인한다. **사이트 이전 완료**와 **QA 통과**를 혼동하지 않는다.
- [ ] **선택한 공개 ICS 호스트로 구독 제공:** `opencigan.pages.dev` 또는 기존 Tailscale `.ts.net`의 `/api/v1/timetable.ics`를 이용하며 `opencigan.mcv.kr` 동일 출처는 필수가 아님. 클라이언트 직접 접근·TLS·정상 VCALENDAR·ETag/304·Apple/Google Calendar 실제 구독·갱신·장애 시 대체 경로를 검증. 기존 구독 URL은 자동으로 다른 호스트로 이전되지 않으므로 변경 시 재등록 안내 또는 한시적 병행 운영.
- [ ] **Tailscale Funnel 단계적 종료·관측:** 2026-11-17 사용자가 기존 `.ts.net` 캘린더 구독자가 없다고 확인한 뒤 Funnel을 중지했다. Pages 기본 주소의 상태·검색·시간표·급식·ICS는 200으로 확인했다. 공식 `opencigan.mcv.kr`은 같은 시각 공개 DNS에서 일시적으로 SERVFAIL이었으나 23:16 KST 재확인 시 CNAME 조회와 상태 API 200으로 복구됐다. 원인 및 장기 안정성, 외부 자동화 의존 여부는 미확인이다. 사설 Tailscale·Cloudflare Tunnel은 유지하며 WARP는 변경하지 않았다. 중지 전 설정과 확인 범위는 [운영 기록](operations.md#tailscale-funnel-단계적-퇴역)을 따른다.

## Phase 5 — 롤백 및 완료 게이트

- [ ] Worker 문제가 생기면 Pages Function의 API 경로를 기존 Funnel API로 되돌릴 수 있는 스테이징/배포 복구 방안 확보. CNAME 전환 실패 시 MCVKR CNAME을 기존 GitHub Pages로 되돌리고 이전 호스트 인증서/전파 상태 확인.
- [ ] Pi 문제는 기존 `release-warp-20261116` 및 구 릴리스의 백업·systemd 복구 절차를 따르되, **컴시간 전용 WARP 프록시는 제거하지 않기**.
- [ ] 평균/중앙값/p95 응답 시간, 오류·429·503, Worker 제한, Workers VPC 연결·QUIC 재연결, 외부망 2곳 실제 IP와 CORS/ICS 로그를 기록. Private VPC Beta의 버전/제한을 운영 위험으로 남기기.

| 게이트 | 통과 조건 |
| --- | --- |
| Pages | `pages.dev`에서 프런트·API 경로 정상, TLS·캐시 확인. 공식 웹사이트 이전을 선택했을 때만 custom domain/CNAME 검사 |
| Workers VPC | cloudflared QUIC 안정, Worker→Pi 비공개 HTTP fetch 정상, Pi 외부 포트 개방 없음 |
| 보안 | Worker 경로·인증·대략적 Rate Limiting + Pi 자체 제한, 위조 IP 차단 검증 |
| 데이터 | 학교/시간표/급식 정상, 기존 WARP와 NEIS 동작 보존 |
| ICS | 선택된 `pages.dev` 또는 `.ts.net`에서 실제 구독·갱신 및 ETag 304·TLS, 호스트 변경 시 기존 링크 재등록/병행 운영 방안 (동일 출처 강제 없음) |
| 운영 | DNS·Pages·Worker·Pi 각각 독립 롤백, 적용 SHA와 증거 기록 |

## 공식 근거 (2026-11-16 검증)

- [Pages 외부 DNS 서브도메인 CNAME](https://developers.cloudflare.com/pages/configuration/custom-domains/)
- [Workers VPC 개요 (Free/Beta)](https://developers.cloudflare.com/workers-vpc/) · [Workers VPC 시작](https://developers.cloudflare.com/workers-vpc/get-started/) · [Pi Private API 예제](https://developers.cloudflare.com/workers-vpc/examples/private-api/)
- [Pages Functions → Worker Service Binding](https://developers.cloudflare.com/pages/functions/bindings/)
- [Worker Rate Limiting binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)
- [일반 Tunnel의 DNS 제한](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/dns/)
