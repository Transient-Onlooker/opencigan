# 관리자 이상 접근 알림

관리자 알림 작업자는 기본적으로 꺼져 있으며 별도 프로세스에서만 실행됩니다. 접속 로그를 읽기 전용으로 조회하고, 알림 상태는 전용 SQLite 파일에 보관합니다. 기존 접속 로그·시간표 이력 DB를 상태 DB로 지정할 수 없습니다. 이 기능은 자동 차단을 수행하지 않습니다.

실행하려면 다음 환경 변수를 명시적으로 설정합니다. 키와 수신 주소는 비밀로 보관하고 명령행이나 저장소에 넣지 마세요.

- `OPENCIGAN_ADMIN_ALERT_ENABLED=1`, `OPENCIGAN_ACCESS_LOG_DB`, `OPENCIGAN_ADMIN_ALERT_DB`
- `OPENCIGAN_ADMIN_ALERT_DESTINATION`: 기존 Webhook 전송기가 허용하는 Discord 또는 Google Chat 주소
- `OPENCIGAN_ADMIN_ALERT_SIGNING_KEY`, `OPENCIGAN_ADMIN_ALERT_ID_KEY`: 각각 32바이트 이상의 독립적인 비밀값. ID 키는 IP를 직접 저장하지 않고 식별값을 만드는 데 사용합니다.
- `OPENCIGAN_ADMIN_ALERT_WINDOW_HOURS`, `OPENCIGAN_ADMIN_ALERT_MAX_REQUESTS`, `OPENCIGAN_ADMIN_ALERT_MAX_ERROR_RATIO`, `OPENCIGAN_ADMIN_ALERT_MAX_SCHOOLS`, `OPENCIGAN_ADMIN_ALERT_MIN_REQUESTS`, `OPENCIGAN_ADMIN_ALERT_MAX_STATUS_ERRORS`: 운영자가 정한 검토 기준
- `OPENCIGAN_ADMIN_ALERT_INTERVAL_SECONDS`: 10~3600초. 접속 로그 보존 기간은 기존 `OPENCIGAN_ACCESS_LOG_RETENTION_DAYS`를 따릅니다.

완전하고 유효한 설정이 있을 때만 `python -m backend.admin_anomaly_alert_worker`로 별도 작업자를 시작할 수 있습니다. 기본 OFF 상태나 설정 누락 상태에서는 조회·발송하지 않습니다. 저장소는 전용 식별표식과 제한된 권한을 검사하며, 알림 본문에는 IP·학교·수신 주소를 포함하지 않습니다.

동일한 활성 징후는 재시작과 동시 실행 후에도 중복 예약하지 않고, 해소 후 재발하면 새 사건으로 기록합니다. 실패한 전송은 같은 이벤트 ID로 제한적으로 재시도합니다. **외부 수신 성공 직후 완료 기록 전에 작업자가 종료되면 중복 수신될 수 있습니다.** 이미 시작한 외부 요청도 취소할 수 없습니다. 수신처가 이벤트 ID로 중복을 제거하는지 별도 확인해야 합니다.

상태 파일은 운영자가 안전한 전용 디렉터리에서 관리해야 합니다. 완료된 기록은 기본 31일 후 정리하며 활성·대기 중인 작업은 유지합니다. 운영 임계치, 수신처 등록 및 작업자 자동 실행은 별도 결정 사항입니다.
