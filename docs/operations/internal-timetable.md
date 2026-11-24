# 내부 시간표 API (구현 중)

별도 프로세스가 `127.0.0.1:8001`에서 수신한다. 외부 공개 서비스나 Cloudflare 경로에 연결하지 않는다. 기존 공개 API와 캐시·셔터·요청 처리 스레드를 공유하지 않는다. Pi에서 내부 서비스 `Nice=0`, 공개 서비스 `Nice=5`를 적용하고 루프백 수신, 무인증 401, 인증 후 실조회 및 정식 도메인 내부 경로 404를 확인했다.

`GET /internal/v1/timetable?school=<학교 ID>&week=<월요일 YYYY-MM-DD>`는 요청마다 컴시간을 실조회한다. `Authorization: Bearer <토큰>`이 필요하며 서버 환경 변수 `OPENCIGAN_INTERNAL_TOKEN`이 비어 있으면 프로세스를 시작하지 않는다. 토큰은 서비스 계정만 읽을 수 있는 환경 파일에 둔다. 응답은 `Cache-Control: no-store`이며 기존 시간표의 `schoolId`, `weekStart`, `records`, `sourceUpdatedAt`, `fetchedAt`, `stale` 구조를 따른다. 각 수업에는 기존 필드와 함께 `originalSubject`, `originalTeacher`가 포함된다. 제공되지 않은 원본 값은 `null`이며 임의로 만들어내지 않는다.

인증 실패는 401, 잘못된 입력은 400, 상류 조회 실패는 503이다. 200의 빈 `records`는 빈 결과이며 503과 구분한다. 이 구분은 상류 라이브러리가 오류를 발생시키거나 잘못된 구조를 반환하는 경우에 한한다. 원본이 불완전한 빈 데이터를 정상 응답으로 보내면 별도로 판별할 수 없다.

`deploy/opencigan-internal.service`는 사용자 서비스 템플릿이다. `current` 릴리스와 `~/.config/opencigan/internal.env`가 필요하며, 기존 WARP 브리지 설정을 사용한다. Pi의 환경 파일은 0600으로 설정되어 있다. 서비스 설치 및 수동 실조회는 확인했지만 컴포넌트 자동 전환·롤백은 별도 작업이다.

## 컴포넌트 검증 (배포 자동화 미완성)

실제 포크 Release의 `deploy-manifest.json`은 버전에 따라 `repo`·`tag`·파일명 또는 `name`·`version`·`pycomcigan/` 접두 경로를 사용한다. 두 형식 모두 `git_sha`, `origin`, `files`를 포함한다. `deploy.fork_manifest`는 고정된 포크 저장소에서 Release와 태그를 직접 확인하고 요청 SHA·자산 SHA-256 및 각 Python 파일의 SHA-256을 대조한다. `python -m deploy.prepare_component --tag <태그> --sha <40자리 SHA> --components <후보 디렉터리> --release <현재 릴리스> --school <학교 ID> --week <월요일>`은 검증된 후보를 별도 경로에 설치하고 회귀 테스트와 실조회를 수행한다. 이 단계는 실행 중인 서비스를 전환하지 않는다.

2026-11-24 확인한 포크 `1.4.6+autofix.1` 태그와 매니페스트 SHA는 `106a6b14f265257514d62eb8babb0c460c9c4792`이다. 이전 `1.4.6` 태그의 SHA는 `9a21fffde4a9afd398ce0ce24a64bbd28e8dc987`이며, 상류 동등 SHA `8b2b4644ceec8a37bf01a0ebbc544743410ae1cf`와 서로 다르므로 태그 검증 시 대체하지 않는다.

이전 `deploy.verify_component`는 별도의 wheel 매니페스트 실험 형식을 검증한다. 현재 포크 Release 형식과 호환되지 않으며 자동 배포에 사용하지 않는다.

후보 준비는 Release 태그의 커밋을 체크아웃하고 매니페스트 파일 해시를 복사 전후 대조한다. 임의 빌드 스크립트를 실행하지 않고 검증된 Python 파일만 복사하며, 현재 지원하지 않는 의존성은 거부한다. `deploy.release_deploy`는 후보 준비 후 내부 API, 공개 API 순으로 전환·실조회하고 전환 실패 시 이전 컴포넌트로 복구하도록 구현되어 있다. 이 자동 전환 코드는 아직 Pi 운영에 설치·활성화되지 않았다.

구현된 호출 형식은 다음과 같다. 실행 전 GitHub 호스트 키가 들어 있는 전용 `~/.ssh/opencigan-github-known-hosts`와 OpenCigan 저장소에 대한 전용 쓰기 키 `~/.ssh/opencigan-pin-sync`(각 0600)가 필요하다. 이 키는 아직 Pi에 설치되지 않았다. GitHub 배포 키의 쓰기 권한은 저장소 단위이며 특정 파일 한 줄로 제한되지 않는다. 자동화 코드가 수정 대상을 검증해 한 줄로 제한한다. `--sha`는 **포크 Release 태그와 매니페스트의 SHA**여야 하며 상류 동등 SHA로 대체하면 거부된다.

```sh
cd "$HOME/opensigan-releases/current"
.venv/bin/python -m deploy.release_deploy --tag 1.4.6+autofix.1 \
  --sha 106a6b14f265257514d62eb8babb0c460c9c4792 \
  --root "$HOME/.local/share/opencigan/components/pycomcigan" \
  --release "$HOME/opensigan-releases/current" \
  --school '학교코드:학교명' --week YYYY-MM-DD
```

결과는 컴포넌트 루트의 `deployment-status.json`에 `requestedSha`, `activeSha`, `success`, `verification`, `rollback`, `pinSync`, `phase`, `timestamp`로 기록된다. 성공 후 OpenCigan `backend/requirements.txt`의 포크 SHA 한 줄만 갱신하고 자동 커밋·푸시를 최대 세 번 시도한다. 핀 동기화만 실패했다면 `python -m deploy.release_deploy --root <컴포넌트 루트> --retry-pin`으로 재시도한다. 파일 상태에 `pinSync: failed`가 남으며 검증된 활성 컴포넌트는 유지한다. GitHub 쓰기 인증과 실제 서비스 전환·롤백 실환경 검증은 아직 완료되지 않았다.

운영 감시는 인증된 `/api/v1/admin/analytics` 응답의 `refreshObservations`, `cacheStatuses`, `failureKinds`에서 각각 갱신 실패, stale 응답 및 상류 조회 오류를 확인한다. 이 집계는 요청이 관측된 범위만 나타내며 기존 로그 보존 정책을 따른다.
