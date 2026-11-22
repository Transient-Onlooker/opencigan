# 기능 제안 API (격리 구현)

기능 제안 접수는 기본적으로 비활성화되어 있으며 공개 운영을 위한 데이터 보존·삭제 정책은 아직 정해지지 않았다. Cloudflare 게이트웨이에 공개 경로를 추가하거나 운영에서 활성화하려면 별도의 운영 결정을 거쳐야 한다.

격리된 테스트 환경에서는 `OPENCIGAN_SUGGESTIONS_ENABLED=1`과 별도 SQLite 파일 경로인 `OPENCIGAN_SUGGESTION_DB`를 지정할 수 있다. 기존 시간표 이력·접속 로그·분석 DB와 같은 파일은 사용할 수 없다. 관리 작업에는 `OPENCIGAN_SUGGESTION_ADMIN_TOKEN`에 충분히 긴 무작위 토큰을 설정하고 `Authorization: Bearer <token>`을 사용한다. 길이 검사만으로 토큰의 무작위성이 보장되지는 않는다.

프런트엔드는 별도의 `VITE_SUGGESTIONS_ENABLED=1` 시험 빌드에서만 설정 화면에 제안 기능을 준비한다. 이때도 API 조회가 성공할 때만 진입점이 나타난다. 기본 빌드는 요청을 보내거나 진입점을 표시하지 않는다. 현재 공개 게이트웨이에는 이 API 경로가 없으며, 빌드 플래그만 설정해도 공개 접수가 활성화되지 않는다.

- `POST /api/v1/suggestions`: 제목과 설명, 선택적인 이용 상황을 제출하고 본인 조회용 토큰을 받는다.
- `GET /api/v1/suggestions`: 승인된 제안만 검색한다.
- `GET /api/v1/suggestions/{id}`: 제출 시 받은 토큰으로 자신의 제안을 확인한다.
- `GET /api/v1/admin/suggestions`: 관리자용 목록을 조회한다.
- `PATCH /api/v1/admin/suggestions/{id}` 및 `DELETE /api/v1/admin/suggestions/{id}`: 관리자가 상태를 변경하거나 제안을 삭제한다.

제안 저장소는 접속 IP나 브라우저 정보를 저장하지 않는다. 제출 내용에는 사용자가 개인정보를 직접 입력할 수 있으므로 공개 승인 시 내용을 확인해야 한다. 제안 내용은 일반 텍스트로 취급하고 화면 출력 시 HTML로 해석하지 않아야 한다.

SQLite는 WAL 모드를 사용하므로 실행 중인 DB 파일 하나만 복사해 백업하지 않는다. SQLite 백업 API 등 일관된 스냅샷을 사용하고 복원본에서 데이터와 접근 권한을 확인한다.
