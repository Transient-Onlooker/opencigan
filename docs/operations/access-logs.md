# 접속 로그

요청 수신 시각·일자(KST, `+09:00`), 원시 클라이언트 IP, 메서드·경로, 학교 식별자·학급·조회 주차/날짜, 데이터 종류, 응답 코드·처리 시간·캐시 상태, 출처와 User-Agent(최대 300자)를 SQLite에 기록합니다. User-Agent는 요청자가 임의로 지정할 수 있는 값입니다. 기본은 비활성화입니다. 운영 활성화 시 IP와 User-Agent 수집·보관 안내와 접근 권한을 확인하세요.

## 설정

- `OPENCIGAN_ACCESS_LOG_DB`: SQLite 파일 경로. 미설정·빈 값이면 기록하지 않습니다.
- `OPENCIGAN_ACCESS_LOG_RETENTION_DAYS`: 당일을 포함한 보관 일수. 기본 7일, API 설정 범위 1~90일입니다. 쓰기·조회 시 만료 자료를 정리합니다. 접근이 전혀 없으면 다음 접근 때 정리됩니다.
- `OPENCIGAN_ADMIN_TOKEN`: 조회 전용 Bearer 토큰. 분석·이력 통계·제안 관리와 공유하며 긴 무작위 값을 사용하세요. 미설정 시 조회할 수 없습니다.
- `ALLOWED_ORIGIN`: 프런트 요청 분류에 사용하는 출처 목록. Origin/Referer는 조작 가능한 관측 신호이며 인증 수단이 아닙니다. 헤더가 없으면 `unknown`입니다.

IP는 기존 신뢰 프록시 설정으로 확인한 클라이언트 값입니다. 실제 프록시의 전달 헤더와 신뢰 CIDR 검증은 [프록시 문서](proxy-client-ip.md)를 따릅니다. 누락된 IP는 `unknown`이며 임의 주소를 만들지 않습니다.

## 관리자 API와 화면

`GET /api/v1/admin/access-logs`에 `Authorization: Bearer <전용 토큰>`을 보냅니다. HEAD도 지원합니다. 응답은 `Cache-Control: no-store`입니다. 저장 비활성화는 503, 토큰 오류는 401, 조회 조건 오류는 400입니다.

필터: `client_ip`, `school_id`, `grade`, `class`, `start_day`, `end_day`, `route`, `status`, `origin_class`, `cache_status`. 날짜는 KST 일자 `YYYY-MM-DD`입니다. `origin_class`는 `frontend`, `external`, `unknown` 중 하나입니다.

JSON은 `items`, `next_cursor`, `limit`, `has_more`, `dropped`를 반환합니다. 각 행의 `timestamp`는 KST ISO 문자열이며 User-Agent가 없거나 도입 이전에 저장된 행의 `user_agent`는 null입니다. `limit`은 기본 50·최대 100이며 다음 페이지는 반환된 `cursor`로 조회합니다. `format=csv`는 같은 필터를 적용한 최신 최대 5,000건을 UTF-8 BOM CSV로 반환합니다. 수식으로 해석될 수 있는 셀을 인용 처리합니다.

화면은 `/access-logs.html`입니다. 토큰은 저장하지 않고 잠금 시 요청·표시·입력값을 지웁니다. [화면 설명](access-log-ui.md).

## 수집 경계와 비동기 처리

전체 URL, 검색어, Authorization·인증 토큰, 원문 Referer, 요청 본문은 저장하지 않습니다. 허용한 API 경로 외에는 `/unknown`으로 기록하고 임의 경로의 쿼리는 보관하지 않습니다. 관리자 요청 자체는 이 로그에서 제외합니다. Origin/Referer는 경로·쿼리·인증정보를 버리고 출처만 남깁니다. 외부 프록시나 별도 웹서버의 로그 정책은 운영자가 별도로 관리해야 합니다.

용량 1,024의 비동기 큐로 처리하며, 포화·저장 실패는 요청을 차단하지 않고 `dropped`에 집계합니다. `flush(timeout)`은 처리 대기를 지원하고 `close(timeout=2)`는 새 제출을 차단합니다. 종료 대기 시간이 지나도 워커는 남은 큐를 비운 뒤 자동 종료합니다. 강제 프로세스 종료 시 미처리 로그는 유실될 수 있습니다.

## 관리자 이상 조회 검토 (백엔드)

백엔드의 `GET /api/v1/admin/access-anomalies`는 접속 로그 전용 Bearer 토큰을 사용합니다. 기존 로그가 비활성화되어 있으면 503을 반환하며 별도 수집을 시작하지 않습니다. 게이트웨이는 기본적으로 이 경로를 노출하지 않으며 `ACCESS_ANOMALIES_ENABLED=1`로 별도 설정한 경우에만 기존 관리자 요청 제한과 백엔드 인증을 거쳐 전달합니다. 접속 로그 화면의 검토 폼도 기본 숨김이며 빌드 시 `VITE_ACCESS_ANOMALIES_ENABLED=1`로 켤 수 있습니다. 두 설정과 운영 배포는 별도입니다.

- `window_hours`: 최근 조회 시간, 기본 24·범위 1~720시간. 실제 보존 기간을 넘는 기록은 조회하지 않습니다.
- `max_requests_per_ip`: IP별 요청 수, 기본 1,000·범위 1~100,000.
- `max_error_ratio`: 전체 요청 중 상태 코드 400 이상 응답의 비율, 기본 0.5·범위 0 초과~1 이하.
- `max_distinct_schools`: IP별 서로 다른 학교 식별자 수, 기본 50·범위 1~100,000.
- `min_requests`: 판정 최소 요청 수, 기본 20·범위 0~1,000,000.
- `max_status_errors`: 선택적 상태별 오류 횟수 기준, 범위 1~100,000. 지정한 경우에만 IP별 404, 429, 5xx를 각각 세어 기준을 초과한 그룹을 `status_errors`와 `status_group`으로 반환합니다. `min_requests`와 보존·조회 구간도 적용합니다.

최소 요청 수 이상이며 각 임계치를 **초과**할 때만 검토 결과를 반환합니다. IP 미확인(`unknown`) 요청은 한 사람의 요청으로 합산하지 않습니다. 최초·최종 시각은 저장 순서가 아닌 수신 시각으로 집계합니다. 반환값은 `findings`, `window_hours`, `thresholds`입니다.

이는 운영자용 검토 신호이며 자동 차단·외부 알림·남용 확정 기능은 아닙니다. NAT·공용 IP 및 정상적인 대량 조회에 의해 오탐이 발생할 수 있습니다. 운영 활성화·임계치 정책은 별도입니다.
