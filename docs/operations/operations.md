# 배포·운영·상태 모니터링

정적 웹앱과 Raspberry Pi API를 배포하거나 점검하는 운영자를 위한 문서입니다. **구성 및 마지막 배포 기록**과 **현재 실측한 상태**를 구별하세요.

- 공식 웹: [opencigan.mcv.kr](https://opencigan.mcv.kr/) · 보조 주소: [opencigan.pages.dev](https://opencigan.pages.dev/) — 동일한 Cloudflare Pages 및 API 백엔드 경로를 사용합니다.
- 2026-11-19의 Worker/Pi 배포 기록은 [운영 기록](cloudflare-tunnel-rollout.md), 이후 내부 API와 검증된 컴포넌트 배포는 [내부 시간표 운영 문서](internal-timetable.md)에 있습니다. 현재 상태는 실제 버전과 서비스 상태로 확인해야 합니다.
- [서비스 토폴로지](../architecture.md) · [Cloudflare 게이트웨이 구성](../../cloudflare-gateway/README.md)

## 실행 경로 구분

| 환경 | 제공 내용 | 접근 및 상태 |
| --- | --- | --- |
| **Cloudflare Pages** | 공식/보조 웹 주소, Svelte 정적 프런트엔드, Pages Functions | `opencigan.mcv.kr` · `opencigan.pages.dev` |
| **Cloudflare API Worker** | Service Binding `OPENCIGAN_GATEWAY`, VPC `PRIVATE_API` | 외부에 독립 `workers.dev` API 호스트를 열지 않는 비공개 연결 |
| **Pi Python API** | `backend.app` / Waitress, 데이터 조회·캐시 | `127.0.0.1:8000` 루프백 수신, Cloudflare Tunnel로 연결 |
| **Pi 내부 시간표 API** | 토큰 인증, 캐시 없는 시간표 조회 | `127.0.0.1:8001`, 공개 경로에 연결하지 않음 |
| **Pi LAN 미리보기** | 선택적인 개발/검수 화면 및 API | 2026-11-25 중지 및 자동 시작 해제; 필요한 경우 별도 확인 후 사용 |
| **기존 GitHub Pages** | 보존된 별도 정적 프런트엔드 배포 | 저장소 변수 `API_BASE_URL`로 별도 API 출처 지정 |
| **과거 Workers/D1 실험** | `experiments/workers-api/`의 예전 실험 코드 | 현재 운영하는 `cloudflare-gateway/` Worker와 다름 |

운영 파일: `deploy/opensigan.service`, `deploy/opencigan-internal.service`, `deploy/opencigan-release-watch.service`와 `.timer`. 이전 미리보기용 `deploy/opensigan-preview.service` 및 관련 설정은 선택적입니다. 서비스는 `systemd --user`에서 실행하며 실제 설치·자동 시작 상태는 Pi에서 확인합니다.

2026-11-25 확인 기준 Release 감지는 30분 타이머와 최대 2분의 지연을 사용하며 게시 직후 이벤트 전달 경로는 아직 구성되지 않았습니다. `1.4.8`의 초기 매니페스트에는 기존 검증기가 요구하는 `name` 필드가 없어 정기 감시가 `Release manifest identity mismatch`로 실패했고 이후 의존성 검증 실패도 기록됐습니다. 매니페스트가 교체된 뒤 20:04 KST 정기 감시에서 `85bf4db852fad74c280e5225d730c8f83e163f7a` 배포가 성공했습니다. 상태 파일에는 릴리스·패키지·내부·공개 검증 성공, 롤백 없음, 핀 동기화 성공이 기록됐습니다. 서비스 실패는 `journalctl --user -u opencigan-release-watch.service`에서 확인할 수 있습니다.

## 외부 데이터 연결

데이터 제공처에 대한 연결 방식과 내부 네트워크 설정은 **운영자 전용 비공개 구성**으로 관리합니다. 공개 문서에서는 실제 주소·포트·접속 계정·서비스별 출구 경로를 제공하지 않습니다.

## 비밀키와 설정

- NEIS 키: `~/.config/opensigan/neis.env` (예: `NEIS_API_KEY=...`). 키 자체를 로그·Issue·PR에 붙이지 마세요.
- LAN 주소: `~/.config/opensigan/preview.env`의 `LAN_HOST`. 저장소에 실제 내부망 주소를 고정하지 마세요.
- 공개 CORS Origin: 서비스의 `ALLOWED_ORIGIN`. 실제 프런트엔드 출처와 정확히 맞추세요.
- 이력 저장: `OPENCIGAN_HISTORY_DB` 기본 미설정. 실제 데이터에 대한 수집·재제공 허용을 확인하기 전 활성화하지 마세요.
- GitHub Pages 배포: 저장소 변수 `API_BASE_URL`을 프런트엔드 빌드에서 `VITE_API_BASE_URL`로 전달합니다. 값이 없으면 Pages에 정적 화면만 표시될 수 있습니다.

## 비파괴적 점검 (RPi 내부)

```bash
systemctl --user status opensigan opencigan-internal opencigan-release-watch.timer --no-pager
curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/status
journalctl --user -u opencigan-release-watch.service -n 30 --no-pager
```

`/api/v1/status`는 프로세스가 응답하는지만 확인하며 컴시간 또는 NEIS 상태를 보장하지 않습니다. 자세한 외부 API 점검은 [API 가이드](../api-guide.md) 참조. 실제 학교 검색/시간표·급식 호출은 원본 서버에 트래픽을 발생시키므로 캐시/제한을 고려해 필요한 경우만 하세요.

캐시가 원본 갱신에 실패하면 API 로그에 `cache refresh failed`가 기록됩니다. `resource`는 시간표·학교 검색·급식 중 작업 종류이고, `fallback=stale`은 기존 데이터를 반환했음을, `fallback=none`은 대체 데이터가 없음을 뜻합니다. `error_type`은 예외 종류이며 원인이 반드시 원본 서버라는 뜻은 아닙니다. 이 진단 항목에는 검색어·학교 식별자·예외 메시지를 기록하지 않습니다. 재시도 대기 중 같은 캐시 키가 다시 조회될 때는 중복 로그를 남기지 않습니다.

```bash
journalctl --user -u opensigan -n 100 --no-pager
```

## 상태 배지 및 GitHub Actions

| 배지 | 대상 | 통과의 의미 | 통과해도 확인되지 않는 것 |
| --- | --- | --- | --- |
| [CI](../../.github/workflows/ci.yml) | `main` 및 PR의 `Check and deploy` | Python·Svelte 검사, Chromium·WebKit 테스트 및 빌드. `main`에서는 Pages도 배포 | 원본 서비스 가용성, 운영 네트워크, 모바일 실기기 동작 |
| [Parser health](../../.github/workflows/parser-health.yml) | `main`의 스케줄/수동 실행 | `대전` 학교 검색 한 번의 결과 형식/파싱 정상 | 전체 시간표 데이터 정확성, 모든 학교, 공개 API 가용성 |

**Parser health 일정:** `17 0 * * 1` (UTC) = 매주 월요일 **09:17 KST**. GitHub Actions의 예약 실행은 지연되거나 실행되지 않을 수 있으며, 워크플로가 아직 실행된 적 없으면 배지가 미확정일 수 있습니다. 동작은 `backend/parser_health_probe.py`에 정의돼 있으며 **하나의 검색 작업이 내부적으로 여러 HTTP 교환을 사용할 수 있습니다**. 재시도나 전체 시간표 조회를 하지 않습니다.

수동 검증은 GitHub 저장소 → **Actions → Parser health → Run workflow**에서 할 수 있습니다. 파서 검사 실패 시 즉시 원본 프로토콜 변경이라고 단정하지 말고, 설치·DNS/네트워크·원본 403/429·응답 스키마를 순서대로 구분하세요. 불필요한 재시도는 원본에 부담을 줍니다.

학교 시간표 파싱을 따로 확인해야 할 때는 백엔드 실행 환경에서 `python -m backend.parser_health_probe --timetable '학교코드:학교명'`을 사용합니다. 해당 학교의 이번 주 시간표 조회 작업을 한 번 실행하며, 검사 도구에서 학교 검색이나 재시도를 추가하지 않습니다. 한 번의 조회 작업이 내부적으로 여러 HTTP 교환을 사용할 수 있습니다. 수업이 한 건 이상이면 정규화 경로를 확인한 것이며 전체 데이터의 정확성을 보장하지 않습니다. 수업이 0건이면 방학·시험 등의 정상 상황일 수 있어 결과는 **판정 보류**(종료 코드 2)이며 학교 일정과 원본을 확인해야 합니다. 자동 주간 검사에는 이 추가 조회를 포함하지 않습니다.

## 내부망 미리보기: 선택적 검수 및 되돌리기

이 절은 과거 미리보기 구성을 유지하거나 다시 검수해야 할 때만 적용합니다. 2026-11-25 운영 정리에서 해당 서비스는 중지하고 자동 시작을 해제했습니다. 공개·내부 API의 현재 실행 경로는 `current`이며, 아래 과거 P0 경로는 현재 운영 릴리스가 아닙니다.

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

**클라이언트 IP·보안:** PR #96의 서명된 IP 전달은 Worker와 Pi에 적용됐다. 2026-11-17 외부 요청의 서명 전달 및 활성화 이후 로그 관찰 기록이 있다. 해당 기록은 모든 외부망이나 실제 제한 초과 시 429 발생까지 검증한 것은 아니다. 임의 X-Forwarded-For·Forwarded를 신뢰하지 않으며 자세한 조건은 [IP 보안 문서](proxy-client-ip.md)를 따른다. 관리자 인증·Webhook 기본 비활성·CORS/ICS 304·429/503 계약을 유지한다.

### 과거 Tailscale Funnel 경로

이전 공개 접근 경로는 종료됐습니다. 현재 사용자용 주소는 공식·보조 Cloudflare Pages 호스트이며, 과거 구독 주소를 다시 사용하거나 내부 네트워크를 변경하기 전에는 운영자 확인이 필요합니다. 내부 접속·중지·복구 명령과 장비 정보는 비공개 운영 기록에서 관리합니다.

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

[지연 계측 자료](../qa/latency-2026-11-13.md) · [개발 가이드](../development.md)
