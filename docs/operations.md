# 배포·운영·상태 모니터링

정적 사이트와 Raspberry Pi API를 배포하거나 점검하는 운영자를 위한 문서입니다.

## 실행 경로 구분

| 환경 | 제공 내용 | 접근 및 상태 |
| --- | --- | --- |
| GitHub Pages | Svelte 정적 프런트엔드와 API 문서 | 페이지 빌드/배포 후 접근 가능. API 주소가 없으면 데이터 조회 불가 |
| RPi Python API | `backend.app` / Waitress | `127.0.0.1:8000` 로컬 바인딩 (원칙상 외부 포트 개방 없음) |
| RPi LAN preview | 정적 프런트엔드와 API 검수 | `LAN_HOST:8080/opensigan/`, 지정한 내부망에서 접근 |
| Cloudflare Workers/D1 | 초기 실험과 별도 코드 | `workers-api/`에 과거 배포 기록; 현재 Python API와 동일하다고 가정하지 않음 |

운영 파일: `deploy/opensigan.service`, `deploy/opensigan-preview.service`, `deploy/opensigan-preview-p0.conf`, `deploy/rpi-guard-opensigan.conf`. 서비스는 `systemd --user`에서 실행하도록 설계되어 있습니다. 자동 시작 여부와 실제 설치 상태는 RPi에서 따로 확인해야 합니다.

## 컴시간 전용 프록시

컴시간에서 서버의 직접 연결이 거부되는 경우 `OPENCIGAN_COMCIGAN_PROXY=http://127.0.0.1:18084`처럼 루프백 HTTP 프록시를 지정할 수 있습니다. 이 설정은 pycomcigan 요청에만 적용되며 NEIS 요청에는 적용하지 않습니다. 프록시가 실패하면 직접 연결로 우회하지 않습니다. 프록시 상태는 Pi에서 `curl --proxy http://127.0.0.1:18084 --max-time 8 http://comci.net:4082/st`로 확인할 수 있습니다. 일반적인 `http_proxy` 환경변수로 서비스 전체 트래픽을 변경하지 마세요.

2026-11-16 운영 긴급 적용은 기존 `release-54f89b9`를 보존한 `release-warp-20261116` 복사본과 `zzzz-opencigan-warp.conf` 사용자 서비스 drop-in을 사용했습니다. 이전 버전으로 되돌릴 때는 해당 drop-in을 다른 이름으로 옮긴 뒤 `systemctl --user daemon-reload`와 `systemctl --user restart opensigan.service`를 실행하고 로컬 상태 API를 확인합니다. 직접 연결이 차단된 동안 이전 버전의 컴시간 조회는 실패할 수 있습니다.

## 비밀키와 설정

- NEIS 키: `~/.config/opensigan/neis.env` (예: `NEIS_API_KEY=...`). 키 자체를 로그·Issue·PR에 붙이지 마세요.
- LAN 주소: `~/.config/opensigan/preview.env`의 `LAN_HOST`. 저장소에 실제 내부망 주소를 고정하지 마세요.
- 공개 CORS Origin: 서비스의 `ALLOWED_ORIGIN`. 실제 프런트엔드 출처와 정확히 맞추세요.
- 이력 저장: `OPENCIGAN_HISTORY_DB` 기본 미설정. 실제 데이터에 대한 수집·재제공 허용을 확인하기 전 활성화하지 마세요.
- GitHub Pages 배포: 저장소 변수 `API_BASE_URL`을 프런트엔드 빌드에서 `VITE_API_BASE_URL`로 전달합니다. 값이 없으면 Pages에 정적 화면만 표시될 수 있습니다.

## 비파괴적 점검 (RPi 내부)

```bash
systemctl --user status opensigan opensigan-preview --no-pager
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/status
journalctl --user -u opensigan-preview -n 30 --no-pager
```

`/api/v1/status`는 프로세스가 응답하는지만 확인하며 컴시간 또는 NEIS 상태를 보장하지 않습니다. 자세한 외부 API 점검은 [API 가이드](api-guide.md) 참조. 실제 학교 검색/시간표·급식 호출은 원본 서버에 트래픽을 발생시키므로 캐시/제한을 고려해 필요한 경우만 하세요.

## 상태 배지 및 GitHub Actions

| 배지 | 대상 | 통과의 의미 | 통과해도 확인되지 않는 것 |
| --- | --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | `main` 및 PR의 `Check and deploy` | Python·Svelte 검사, Chromium·WebKit 테스트 및 빌드. `main`에서는 Pages도 배포 | 원본 서비스 가용성, 운영 네트워크, 모바일 실기기 동작 |
| [Parser health](../.github/workflows/parser-health.yml) | `main`의 스케줄/수동 실행 | `대전` 학교 검색 한 번의 결과 형식/파싱 정상 | 전체 시간표 데이터 정확성, 모든 학교, 공개 API 가용성 |

**Parser health 일정:** `17 0 * * 1` (UTC) = 매주 월요일 **09:17 KST**. GitHub Actions의 예약 실행은 지연되거나 실행되지 않을 수 있으며, 워크플로가 아직 실행된 적 없으면 배지가 미확정일 수 있습니다. 동작은 `backend/parser_health_probe.py`에 정의돼 있으며 **하나의 검색 작업이 내부적으로 여러 HTTP 교환을 사용할 수 있습니다**. 재시도나 전체 시간표 조회를 하지 않습니다.

수동 검증은 GitHub 저장소 → **Actions → Parser health → Run workflow**에서 할 수 있습니다. 파서 검사 실패 시 즉시 원본 프로토콜 변경이라고 단정하지 말고, 설치·DNS/네트워크·원본 403/429·응답 스키마를 순서대로 구분하세요. 불필요한 재시도는 원본에 부담을 줍니다.

## 내부망 검수 및 되돌리기

- `opensigan-preview`는 `frontend/dist`를 제공하며, `LAN_HOST`가 없으면 시작하지 않습니다.
- P0 검수용 `deploy/opensigan-preview-p0.conf`는 `WorkingDirectory`를 `~/opensigan-releases/p0-20261114`로 지정하고 이력 DB 환경 변수를 비웁니다. 실제 적용 여부는 `systemctl --user cat opensigan-preview`로 확인하세요.
- 해당 P0 검수 drop-in을 되돌릴 때는, **실제로 설치된 파일 경로를 확인한 후** `.conf.disabled`로 이동하고 `systemctl --user daemon-reload`와 `systemctl --user restart opensigan-preview`를 실행합니다. 기존 `~/opensigan` 작업물은 삭제하지 않습니다.
- `rpi-guard-opensigan.conf`는 특정 LAN 대역·`wlan0`·8080 포트만 허용하도록 설계된 선택적 drop-in입니다. 이는 방화벽 재시작 때 적용되며, 파일을 제거해도 **이미 적용된 nftables 규칙이 즉시 사라지지는 않습니다**. 규칙 삭제 전 반드시 정확한 handle을 확인하세요.
- 외부 접속 경로나 방화벽 규칙을 변경할 때는 기존 서비스에 미치는 영향과 되돌리는 방법을 먼저 확인합니다.

### 변경 이력 DB 백업·복구

이력 저장은 선택 기능이며 데이터 재제공 조건을 확인하기 전에는 활성화하지 않습니다. 이력은 수집한 시점 사이의 변화를 모두 보장하지 않고 최근 30일만 유지합니다. 새 버전은 이전 `snapshots`를 `snapshot_lessons`로 한 번 복사하며, 이후 새 관측은 새 테이블에만 반영합니다. 따라서 기존 테이블이 남아 있어도 DB를 그대로 둔 채 구버전으로 되돌리면 기준 스냅샷이 오래되어 잘못된 변경이 기록될 수 있습니다.

배포 전에는 실제 `OPENCIGAN_HISTORY_DB` 경로와 보관 권한을 확인하고 SQLite의 온라인 백업 API로 DB 전체를 별도 경로에 복사합니다. WAL 사용 중에는 DB 파일 하나만 복사하면 안 됩니다. 아래 예제의 경로는 운영 환경에 맞게 지정하며, 대상이 이미 있으면 덮어쓰지 않습니다.

```bash
python3 - "$HISTORY_DB" "$HISTORY_BACKUP" <<'PY'
import os, sqlite3, sys
from contextlib import closing
from pathlib import Path
source, target = sys.argv[1:]
if not os.path.isfile(source):
    raise SystemExit("source database does not exist")
fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
with closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)) as src, closing(sqlite3.connect(target)) as dst:
    src.backup(dst)
    if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("backup integrity check failed")
print("backup integrity check: ok")
PY
```

복구 시에는 서비스와 DB에 쓰는 다른 프로세스를 모두 중지하고, 복구 전 현재 DB도 별도 백업으로 보존합니다. 검증된 배포 전 백업을 **새 경로**에 복사한 뒤 구버전의 `OPENCIGAN_HISTORY_DB`가 그 복사본을 가리키도록 설정하고 재시작합니다. 구버전 실행 중에는 새 DB의 스키마나 WAL 파일을 직접 교체하지 않습니다. 백업 이후 관측한 이력은 복구본에 포함되지 않으므로 보존한 새 DB와 혼동하지 마세요. 적용 전후에는 `PRAGMA integrity_check`와 테스트 학교의 이력 조회를 확인합니다. 이 절차는 운영 DB에서 실행한 검증 결과가 아닙니다.

## Cloudflare Tunnel 전환 계획 (P0, 미적용)

[**오늘 진행용 세부 실행 체크리스트**](cloudflare-tunnel-rollout.md)는 호스트/인증서 선택, cloudflared 설치, WAF 오탐, 프런트·ICS 전환과 개별 롤백을 포함합니다.

**2026-11-16부터 공개 API/ICS 제공과 Cloudflare WAF 봇 방어를 P0 우선 작업으로 결정했습니다. 아직 Tunnel·WAF 운영 전환을 완료한 것은 아닙니다.** `cloudflared`가 Raspberry Pi에서 Cloudflare로 아웃바운드 연결을 만들고 로컬 API(`127.0.0.1:8000`)에 전달하는 구성을 우선 검토·구현합니다. 현재 정적 웹의 GitHub Pages 호스트와 분리되는 공개 API 호스트(우선 후보 `opencigan-api.mcv.kr`; Cloudflare zone/TLS 확인 전 미확정)를 사용하면 Pages 경로의 `/api/v1/...` 404 문제를 해소할 수 있습니다. DNS/TLS, CORS, 프런트·OpenAPI·ICS URL은 전환 검증 후 일치시켜야 합니다.

- **WAF/봇 방어:** API 호스트의 요청률·학교 검색 남용·반복 오류는 Cloudflare WAF 사용자 정의 규칙과 Rate Limiting으로 방어하는 것을 우선합니다. 학교 검색·시간표·ICS·상태·Webhook·관리자 API는 서로 다른 요청 특성이 있으므로 경로별 정책을 만들고 보안 이벤트와 오탐율을 확인합니다. 사용 가능한 Bot Score/관리 기능은 Cloudflare 계정 플랜을 확인한 후 선택합니다. API/ICS에 브라우저 JS Challenge를 일괄 적용하면 캘린더·기계 클라이언트가 차단될 수 있으므로 금지합니다. Bot Fight Mode의 예외 처리 제약도 검토해야 합니다.
- **외부 진입과 원본 연결은 별개:** Cloudflare Tunnel/WAF는 방문자→API **수신** 경로입니다. 위의 `OPENCIGAN_COMCIGAN_PROXY`와 WARP는 Pi→컴시간 **송신** 경로이며 서로 대체하지 않습니다.
- **변경 검증/되돌리기:** DNS/TLS/라우팅, ETag·304·ICS 구독, CORS, JSON API의 정상 및 차단 응답, Rate Limiting·Python 자체 제한 일치, 인증된 관리 페이지, Tailscale Funnel 대비 지연·정책·비용·롤백을 확인합니다. 실제 적용 전에는 기존 구독 URL의 연속성을 고려하세요.
- **접속자 IP와 로그:** 터널 뒤에서 서버의 `REMOTE_ADDR`는 보통 `cloudflared`의 연결 주소입니다. HTTP 원본 접속 IP는 Cloudflare의 `CF-Connecting-IP` 헤더로 전달되므로, 현재의 [신뢰 프록시 IP 처리](proxy-client-ip.md)와 [접속 로그](access-logs.md)에 **신뢰된 터널에서만** 올바르게 반영되는지 시험합니다. 외부에서 임의로 보낸 헤더를 신뢰하는 구성은 피합니다.
- **속도·용량:** Tailscale Funnel은 변경 불가능한 대역폭 제한이 있습니다. Cloudflare Tunnel에는 동일한 공개 월간 GB 한도가 명시되지 않았더라도, 플랜·요청 크기·서비스별 사용 정책·운영 서버의 업로드 대역폭과 처리 성능 등 제약이 남습니다. *무제한 트래픽이나 무조건 빠른 응답은 가정하지 않습니다.* 기존 로드맵의 TTFB/p95 벤치마크로 비교합니다.
- **전환 시 확인:** `opencigan.mcv.kr` DNS/TLS, API CORS, `.ics` 구독, 304/ETag, 관리자 인증, IP별 429 제한과 503 과부하 보호, 터널 재연결, 서비스 중단 시 복귀 방법을 확인합니다. 현재 운영 중인 Funnel·DNS·systemd 설정은 이 검토만으로 변경하지 않습니다.

공식 문서: [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/) · [원본 IP 헤더](https://developers.cloudflare.com/fundamentals/reference/http-headers/) · [Cloudflare Tunnel FAQ](https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/) · [Tailscale Funnel 제한](https://tailscale.com/docs/features/tailscale-funnel)

## 자동 셔터와 통계

`backend/shutter.py`의 기본 임계치는 프로세스당 60초에 600회 요청 또는 1분 평균 부하 8입니다. 임계치를 넘으면 30초 동안 `503 service_overloaded`와 `Retry-After`를 반환합니다. `SHUTTER_MAX_REQUESTS`, `SHUTTER_WINDOW_SECONDS`, `SHUTTER_COOLDOWN_SECONDS`, `SHUTTER_MAX_LOAD`로 조절합니다. 요청량·부하 조건은 각각 0이면 비활성화되며, 평균 부하를 읽을 수 없는 OS에서는 부하 조건을 적용하지 않습니다. 상태 확인, 인증된 관리자 통계, OPTIONS 요청은 셔터 대상에서 제외합니다.

통계 설정과 운영 지표의 의미는 [이용 통계](analytics.md)를 참고하세요. 내부망 서버는 최신 `/assets/...` 경로와 기존 `/opensigan/assets/...` 경로를 모두 제공합니다.

### 배포 검증

Pages 배포가 끝나면 공개 페이지와 정적 파일이 열리는지 확인합니다. API 변경은 별도로 배포한 뒤 상태 응답, 프런트엔드 출처의 CORS 응답, 관리자 인증을 점검합니다. UI만 변경했다면 API를 재시작할 필요가 없습니다.

## 공개 전 체크리스트

- [ ] 원본 컴시간 데이터의 이용 조건·저장·재제공 범위 확인
- [ ] 프록시/Tunnel 뒤 실제 클라이언트 식별과 60회/60초 요청 제한의 상호작용 검증
- [ ] LAN과 외부 접속에서 캐시 HIT/MISS 및 오류 상황 실측
- [ ] CORS·보안 헤더·API 버전·오류 계약·비밀키 보호 확인
- [ ] RPi Wi-Fi/정전·업데이트·백업·되돌리기 절차 확보

[지연 계측 자료](latency-2026-11-13.md) · [개발 가이드](development.md)
