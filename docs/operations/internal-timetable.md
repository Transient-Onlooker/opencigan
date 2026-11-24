# 내부 시간표 API (구현 중)

별도 프로세스가 `127.0.0.1:8001`에서 수신한다. 외부 공개 서비스나 Cloudflare 경로에 연결하지 않는다. 기존 공개 API와 캐시·셔터·요청 처리 스레드를 공유하지 않는다. 운영 배포와 자원 우선권 설정은 아직 검증되지 않았다.

`GET /internal/v1/timetable?school=<학교 ID>&week=<월요일 YYYY-MM-DD>`는 요청마다 컴시간을 실조회한다. `Authorization: Bearer <토큰>`이 필요하며 서버 환경 변수 `OPENCIGAN_INTERNAL_TOKEN`이 비어 있으면 프로세스를 시작하지 않는다. 토큰은 서비스 계정만 읽을 수 있는 환경 파일에 둔다. 응답은 `Cache-Control: no-store`이며 기존 시간표의 `schoolId`, `weekStart`, `records`, `sourceUpdatedAt`, `fetchedAt`, `stale` 구조를 따른다. 각 수업에는 기존 필드와 함께 `originalSubject`, `originalTeacher`가 포함된다. 제공되지 않은 원본 값은 `null`이며 임의로 만들어내지 않는다.

인증 실패는 401, 잘못된 입력은 400, 상류 조회 실패는 503이다. 200의 빈 `records`는 빈 결과이며 503과 구분한다. 이 구분은 상류 라이브러리가 오류를 발생시키거나 잘못된 구조를 반환하는 경우에 한한다. 원본이 불완전한 빈 데이터를 정상 응답으로 보내면 별도로 판별할 수 없다.

`deploy/opencigan-internal.service`는 제안된 사용자 서비스 템플릿이다. `current` 릴리스와 `~/.config/opencigan/internal.env`가 준비되어야 하며, 기존 WARP 브리지 설정을 사용한다. 토큰의 발급·권한 설정, 릴리스 설치·검증·롤백 자동화, 실조회 및 공개 경로 차단 검증이 끝나기 전 운영에 적용하지 않는다.

## 컴포넌트 검증 (배포 자동화 미완성)

`python -m deploy.verify_component --manifest deploy-manifest.json --manifest-sha256 <신뢰한 SHA256> --wheel <wheel 경로> --allowed-repository <소유자/저장소>`는 별도 매니페스트의 SHA-256, 허용 저장소, 공식·포크 구분, GitHub의 공개 Release와 태그가 가리키는 40자리 커밋 SHA, wheel의 SHA-256을 검증한다. 매니페스트 형식은 `schemaVersion: 1`, `repository`, `kind` (`official` 또는 `fork`), `releaseTag`, `commit`, `wheelSha256`이다.

매니페스트 해시는 매니페스트와 독립된 신뢰 경로에서 지정해야 한다. 매니페스트와 해시를 같은 미검증 출처에서 함께 받아서는 안 된다. 이 검증만으로 wheel이 해당 커밋에서 빌드됐다는 사실은 증명되지 않으므로, 격리 빌드와 산출물 대조·출처 확인을 추가해야 한다. 검증기는 설치·서비스 재시작·상태 기록·실조회 또는 롤백을 수행하지 않는다.
