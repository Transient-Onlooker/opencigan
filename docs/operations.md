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

캐시가 원본 갱신에 실패하면 API 로그에 `cache refresh failed`가 기록됩니다. `resource`는 시간표·학교 검색·급식 중 작업 종류이고, `fallback=stale`은 기존 데이터를 반환했음을, `fallback=none`은 대체 데이터가 없음을 뜻합니다. `error_type`은 예외 종류이며 원인이 반드시 원본 서버라는 뜻은 아닙니다. 이 진단 항목에는 검색어·학교 식별자·예외 메시지를 기록하지 않습니다. 재시도 대기 중 같은 캐시 키가 다시 조회될 때는 중복 로그를 남기지 않습니다.

```bash
journalctl --user -u opensigan -n 100 --no-pager
```

## 상태 배지 및 GitHub Actions

| 배지 | 대상 | 통과의 의미 | 통과해도 확인되지 않는 것 |
| --- | --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | `main` 및 PR의 `Check and deploy` | Python·Svelte 검사, Chromium·WebKit 테스트 및 빌드. `main`에서는 Pages도 배포 | 원본 서비스 가용성, 운영 네트워크, 모바일 실기기 동작 |
| [Parser health](../.github/workflows/parser-health.yml) | `main`의 스케줄/수동 실행 | `대전` 학교 검색 한 번의 결과 형식/파싱 정상 | 전체 시간표 데이터 정확성, 모든 학교, 공개 API 가용성 |

**Parser health 일정:** `17 0 * * 1` (UTC) = 매주 월요일 **09:17 KST**. GitHub Actions의 예약 실행은 지연되거나 실행되지 않을 수 있으며, 워크플로가 아직 실행된 적 없으면 배지가 미확정일 수 있습니다. 동작은 `backend/parser_health_probe.py`에 정의돼 있으며 **하나의 검색 작업이 내부적으로 여러 HTTP 교환을 사용할 수 있습니다**. 재시도나 전체 시간표 조회를 하지 않습니다.

수동 검증은 GitHub 저장소 → **Actions → Parser health → Run workflow**에서 할 수 있습니다. 파서 검사 실패 시 즉시 원본 프로토콜 변경이라고 단정하지 말고, 설치·DNS/네트워크·원본 403/429·응답 스키마를 순서대로 구분하세요. 불필요한 재시도는 원본에 부담을 줍니다.

학교 시간표 파싱을 따로 확인해야 할 때는 백엔드 실행 환경에서 `python -m backend.parser_health_probe --timetable '학교코드:학교명'`을 사용합니다. 해당 학교의 이번 주 시간표 조회 작업을 한 번 실행하며, 검사 도구에서 학교 검색이나 재시도를 추가하지 않습니다. 한 번의 조회 작업이 내부적으로 여러 HTTP 교환을 사용할 수 있습니다. Pi에서는 기존 컴시간 전용 WARP 프록시 설정을 유지하세요. 수업이 한 건 이상이면 정규화 경로를 확인한 것이며 전체 데이터의 정확성을 보장하지 않습니다. 수업이 0건이면 방학·시험 등의 정상 상황일 수 있어 결과는 **판정 보류**(종료 코드 2)이며 학교 일정과 원본을 확인해야 합니다. 자동 주간 검사에는 이 추가 조회를 포함하지 않습니다.

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

## Cloudflare Pages + Workers VPC 구성 (2026-11-17 공식 사이트 이전 완료 보고)

**사용자 확인:** `opencigan.mcv.kr`의 Cloudflare Pages 이전을 마쳤다. 기존 배포 기록에는 Pages Functions → Worker Service Binding → Workers VPC → Pi `cloudflared` QUIC → 로컬 Python API의 상태 응답이 확인돼 있다. 다만 공식 호스트의 현재 DNS/TLS·전체 기능·원본 IP·Rate Limiting·ICS 자동 갱신은 별도의 운영 QA가 필요하다. `mcv.kr`은 타사 DNS zone이므로 전체 NS나 zone-wide WAF는 변경하지 않는다.

- 사이트 배포·기본 API 연결은 **완료 보고/기존 기록**, 기능별 검증은 [P0 체크리스트](cloudflare-tunnel-rollout.md)의 **2026-11-17 예정 QA**에 남겨 둔다.
- GitHub Pages는 별도 복구 판단 전까지 유지한다. Tailscale Funnel은 아래 실행 기록과 같이 중지했다. Cloudflare Workers VPC는 베타 기능이므로 버전·가용성 변화를 관찰한다.
- Pi의 컴시간 전용 WARP 출구 `OPENCIGAN_COMCIGAN_PROXY`는 **Funnel과 별개**이므로 중단하지 않는다.

**클라이언트 IP·보안:** PR #96의 서명된 IP 전달 코드는 Worker에 배포했고 Pi의 서명 키를 Worker 비밀값에 등록했다. 서로 다른 외부망에서의 실제 서명 검증·IP·로그·429 실측은 미확인이다. 임의 X-Forwarded-For·Forwarded를 신뢰하지 않으며 자세한 조건은 [IP 보안 문서](proxy-client-ip.md)를 따른다. 관리자 인증·Webhook 기본 비활성·CORS/ICS 304·429/503 계약을 유지한다.

### Tailscale Funnel 단계적 퇴역

**2026-11-17 23:14 KST 확인:** 사용자가 기존 `.ts.net` 캘린더 구독자가 없다고 확인하고 Pi에서 `sudo tailscale funnel --https=443 off`를 실행했다. `tailscale funnel status --json`은 `{}`이고 기존 공개 주소는 연결되지 않았다. 중지 전 HTTPS 443의 `/api`는 `http://127.0.0.1:8000/api`, `/api/v1/status`는 `http://127.0.0.1:8000/api/v1/status`를 가리켰다. 중지 전 설정은 작업 PC의 `AppData/Local/Temp/opencigan-funnel-before-20261117.json`에도 기록되어 있으나 임시 파일이므로 장기 보관을 보장하지 않는다. Tailscale 사설 연결은 활성이고 `opencigan-cloudflared.service`는 active였다. WARP 설정은 이 작업에서 변경하지 않았으며 별도 동작 검사는 하지 않았다.

**같은 시각 검증·주의:** `opencigan.pages.dev`에서 상태·학교 검색·NEIS 학교 검색·시간표·급식·ICS가 각각 HTTP 200이었고 ICS는 `VCALENDAR`를 포함했다. `opencigan.mcv.kr`은 PC와 Pi에서 DNS 조회가 실패했고 Cloudflare·Google 공개 DNS도 `mcv.kr` 권한 DNS 관련 SERVFAIL을 반환했다. **23:16 KST 재확인에서는** Cloudflare DNS가 `opencigan.pages.dev` CNAME을 반환했고 공식 주소 상태 API도 HTTP 200으로 회복됐다. 장애 원인과 Funnel 중지와의 인과관계는 확인되지 않았다. 실제 캘린더 앱 자동 갱신, 외부망 복수 지점, 공식 주소의 전체 기능과 지속적인 DNS 안정성 검증은 남아 있다.

Funnel은 `*.ts.net` 공개 HTTPS 주소를 제공하는 별도 진입점이다. 기존 외부 스크립트는 자동으로 새 URL을 사용하지 않는다. 아래는 향후 재활성화 또는 점검 시 참고할 절차다.

1. 현재 Funnel 구성을 읽기 전용으로 확인해 공개 포트·경로와 복귀할 원래 명령을 기록한다. 기존 `.ts.net` ICS 링크가 앱/UI/문서·사용자의 캘린더 구독에 남아 있는지, 신규 링크가 Cloudflare URL인지 확인한다.
2. 서로 다른 네트워크에서 새 Cloudflare 주소의 웹·API·ICS(TLS, VCALENDAR, ETag/304, 새 구독·갱신), 인증·오류·Rate Limit을 점검한다. 기존 구독자에게 URL 재등록을 안내하거나 병행 제공 방침을 결정한다.
3. 대체 경로가 검증되고 기존 주소에 의존하는 구독자가 없거나 이전을 안내했다면, **Funnel만 중지**한다. 중지 전후 `tailscale funnel status --json`으로 상태를 확인하고 원래 포트/옵션의 명령에 `off`를 붙인다. 예를 들어 443 HTTPS 설정이라면 `tailscale funnel --https=443 off`다. 실제 설정이 다르면 그대로 복사해 사용한다. `tailscale funnel reset`, `tailscale down`, `tailscale up` 또는 클라이언트 제거를 종료 방법으로 사용하지 않는다.
4. 중지 후 새 Cloudflare 주소에서 웹/API/ICS가 계속 동작하는지 확인하고 429/503·VPC 연결·사용자 오류를 관찰한다. 문제가 생기면 기록한 원래 Funnel 명령으로 공개 경로를 복구한다.

**범위:** Funnel 외부 공개만 중지한다. Tailscale 사설 네트워크, Cloudflare `cloudflared` Tunnel, Pi의 컴시간 전용 WARP 출구는 서로 다른 구성 요소이므로 그대로 보존한다. 위 번호 목록은 향후 운영 절차이며 현재 실행 상태는 위 확인 기록을 따른다.

공식 문서: [Cloudflare Pages Custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/) · [Workers VPC](https://developers.cloudflare.com/workers-vpc/) · [Pages Service bindings](https://developers.cloudflare.com/pages/functions/bindings/) · [Worker Rate Limiting](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)

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
