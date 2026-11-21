# 기능 제안 API (격리 구현)

기능 제안 접수는 기본적으로 비활성화되어 있으며 공개 운영을 위한 데이터 보존·삭제 정책은 아직 정해지지 않았다. Cloudflare 게이트웨이에 공개 경로를 추가하거나 운영에서 활성화하려면 별도의 운영 결정을 거쳐야 한다.

격리된 테스트 환경에서는 `OPENCIGAN_SUGGESTIONS_ENABLED=1`과 별도 SQLite 파일 경로인 `OPENCIGAN_SUGGESTION_DB`를 지정할 수 있다. 기존 시간표 이력·접속 로그·분석 DB와 같은 파일은 사용할 수 없다. 관리 작업에는 `OPENCIGAN_SUGGESTION_ADMIN_TOKEN`에 충분히 긴 무작위 토큰을 설정하고 `Authorization: Bearer <token>`을 사용한다. 길이 검사만으로 토큰의 무작위성이 보장되지는 않는다.

- `POST /api/v1/suggestions`: 제목과 설명, 선택적인 이용 상황을 제출하고 본인 조회용 토큰을 받는다.
- `GET /api/v1/suggestions`: 승인된 제안만 검색한다.
- `GET /api/v1/suggestions/{id}`: 제출 시 받은 토큰으로 자신의 제안을 확인한다.
- `GET /api/v1/admin/suggestions`: 관리자용 목록을 조회한다.
- `PATCH /api/v1/admin/suggestions/{id}` 및 `DELETE /api/v1/admin/suggestions/{id}`: 관리자가 상태를 변경하거나 제안을 삭제한다.

제안 저장소는 접속 IP나 브라우저 정보를 저장하지 않는다. 제출 내용에는 사용자가 개인정보를 직접 입력할 수 있으므로 공개 승인 시 내용을 확인해야 한다. 제안 내용은 일반 텍스트로 취급하고 화면 출력 시 HTML로 해석하지 않아야 한다.
