# Opencigan API 가이드

이 문서는 직접 실행한 Python API를 호출하는 방법을 설명합니다. 요청과 응답 형식은 [OpenAPI 3.1](openapi.yaml)을 기준으로 합니다. 공개 사이트의 주소가 외부 개발자용 API 주소나 원본 데이터 재배포 권한을 보장하지는 않습니다.

## 호출 기본

### 입력한 교시 시각으로 구독

`/api/v1/timetable.ics?school=...&grade=1&class=2&mode=timed&times=1%3A0900-0950%2C2%3A1000-1050`

`times`는 `교시:HHMM-HHMM`을 쉼표로 연결합니다. 1~20교시의 중복·역전·겹침을 거부합니다. 입력은 한국 시각(KST)이며 ICS에는 같은 순간을 UTC로 기록하므로 한국 캘린더에 오전 9시로 표시됩니다. 시각이 없는 교시는 ‘교시 시각 미설정’ 종일 일정입니다. 기존 `periods`·`summary` 모드는 유지합니다.

서버 코드의 `timed` 모드는 선택적으로 `weekday_times=2.1%3A1000-1050`처럼 요일별 예외도 받습니다. 요일은 월요일 1부터 일요일 7이며, 이 예시는 화요일 1교시를 지정합니다. 지정하지 않은 교시는 `times`의 공통 시각을 사용합니다. 예외를 적용한 각 요일의 시각이 겹치거나 순서가 바뀌면 요청을 거부합니다. 이 기능의 운영 배포와 웹 설정·백업 연동은 별도입니다.

교시 시각은 URL에 포함되어 API 서버와 캘린더 서비스에 전달됩니다. UI는 이에 동의한 경우에만 시각이 포함된 링크를 생성합니다. 서버에 개인 시각 프로필을 저장하지 않으며, 시각을 수정하면 캘린더 앱에도 새 URL을 추가해야 합니다.

- 기본 경로: `/api/v1`
- 이 문서에 나오는 조회 API는 `GET`, `HEAD`, `OPTIONS`를 지원합니다.
- 개발용 API 주소: `http://127.0.0.1:8000` (API를 실행하는 **같은 기기**에서만 접근)
- HTTP 응답: JSON (UTF-8), 시간표 구독은 `text/calendar`, 변경 이력 피드는 `application/rss+xml`입니다. 두 구독 피드는 비공유 캐시에서 재검증할 수 있으며, 나머지는 `Cache-Control: no-store`를 사용합니다.
- 브라우저에서 다른 출처로 호출하려면 서버의 `ALLOWED_ORIGIN`과 배포 경로를 함께 맞춰야 합니다.

`/api-docs.html`에서 API 주소를 설정하고 필터와 캘린더 구독을 시험할 수 있습니다. 다른 출처의 API는 서버에서 해당 문서의 출처를 CORS로 허용해야 합니다.

### 버전 및 호환성

현재 경로의 `v1`은 API 계약의 주요 버전입니다. 기존 필드나 의미를 유지하는 선택적 응답 필드와 엔드포인트 추가는 같은 버전에서 제공할 수 있으므로 클라이언트는 알 수 없는 응답 필드를 무시해야 합니다. 기존 요청이나 응답의 호환성을 깨는 변경이 필요하면 새 주요 버전을 도입하고 이전 버전의 지원 종료 일정과 이전 방법을 별도로 안내합니다. 운영 시작이나 지원 기간은 아직 확정되지 않았습니다.

## 엔드포인트

| 메서드 | 경로 | 필수 쿼리 | 주의 |
| --- | --- | --- | --- |
| GET | `/api/v1/status` | 없음 | 프로세스 생존 확인. 원본 서버 검사 아님 |
| GET | `/api/v1/schools` | `q` | 컴시간 학교 검색, 검색어 1~50자 |
| GET | `/api/v1/neis/schools` | `q` | NEIS 학교 검색, 서버 측 API 키 필요 |
| GET | `/api/v1/timetable` | `school`, `week` | 컴시간 학교 ID와 이번/다음 주 월요일(KST) |
| GET | `/api/v1/timetable.ics` | `school`, `grade`, `class` | 지속해서 사용하는 iCalendar 구독 URL, 기본 이번 주·`weeks=2`면 다음 주까지 |
| GET | `/api/v1/meals` | `school`, `from`, `to` | NEIS 학교 ID와 최대 7일(양 끝 포함) |
| GET | `/api/v1/timetable/history` | `school`, `week` | 선택적 `cursor`. 변경 이력 미설정 시 503 |
| GET | `/api/v1/timetable/history.rss` | `school`, `grade`, `class` | 학급별 관측 변경 RSS. 이력 미설정 시 503 |

NEIS 학교·급식 정보의 출처는 교육부·시도교육청의 [나이스 교육정보 개방 포털](https://open.neis.go.kr/)입니다. 데이터 재사용 시 [서비스 이용약관](https://open.neis.go.kr/portal/userAgreementPage.do)과 개별 데이터의 조건을 확인하고 출처를 표시하세요. Opencigan의 코드 라이선스는 원본 데이터의 이용 권한을 대신하지 않습니다.

### 학교 ID는 출처별로 다릅니다

- 컴시간: `학교코드:학교명` (예시: `1234:예시학교`)
- NEIS: `시도교육청코드:학교코드` (예시: `B10:1234567`)

한쪽 ID를 다른 엔드포인트에 넘기지 마세요. 사용자 화면에서는 컴시간 학교를 선택한 뒤 NEIS 학교를 별도로 검색·확인합니다.

### 예제: 로컬 시간표 조회

```bash
# 합성 ID이며 실제 서버에서 유효한 학교라는 뜻이 아닙니다.
curl --get 'http://127.0.0.1:8000/api/v1/timetable' \
  --data-urlencode 'school=1234:예시학교' \
  --data-urlencode 'week=2026-11-16'
```

이 예제의 날짜는 **2026-11-14 기준 다음 주 월요일**입니다. API는 호출 시점에 해당하는 이번/다음 주만 허용하므로 다른 날짜에는 `week`를 바꿔야 합니다. 먼저 `/api/v1/schools`에서 얻은 **실제 학교 ID**를 사용하세요.

응답 필드의 형태(아래는 합성 데이터):

```json
{
  "schoolId": "1234:예시학교",
  "weekStart": "2026-11-16",
  "records": [
    {
      "grade": 2, "class": 3, "date": "2026-11-16",
      "period": 1, "subject": "수학", "teacher": "예시교사",
      "isChanged": false
    }
  ],
  "sourceUpdatedAt": "2026-11-13T18:00:00+09:00",
  "fetchedAt": "2026-11-14T00:00:00+00:00",
  "stale": false,
  "cacheStatus": "miss"
}
```

기본 `records`는 요청한 학교의 **전체 학급**을 포함합니다. 특정 반만 원하면 `grade=2&class=3`, 교사 이름 일부로 검색하려면 `teacher=김`을 추가할 수 있습니다. 필터 요청은 학교·주별 서버 캐시를 재사용하므로 원본 요청이 늘지 않습니다.

### 시간표 캘린더 구독 (.ics)

웹 화면의 **캘린더 구독 링크**를 눌러 URL을 복사한 뒤, 캘린더 앱에 URL 구독으로 등록할 수 있습니다. 시간이 지나도 같은 URL이 현재 주를 가리키며 `weeks=2`를 선택하면 다음 주까지 포함합니다. 구독 요청도 JSON 시간표와 같은 서버 캐시를 이용합니다.

```bash
curl --get 'http://127.0.0.1:8000/api/v1/timetable.ics' \
  --data-urlencode 'school=1234:예시학교' \
  --data-urlencode 'grade=2' \
  --data-urlencode 'class=3' \
  --data-urlencode 'weeks=2'
```

기본값 `mode=periods`는 수업마다 종일 일정을 만들고, `mode=summary`는 하루 수업을 종일 일정 하나로 묶습니다. 원본에는 실제 교시 시각이 없습니다. 응답의 `ETag`를 다음 요청의 `If-None-Match`로 보내면 피드가 같을 때 본문 없이 `304`로 응답합니다. 앱마다 갱신 주기가 다르며, 구독 주소는 캘린더 앱에서 접근할 수 있어야 합니다.

## 캐시와 변경 이력

- `cacheStatus`: `hit`(신선한 캐시), `miss`(새로 가져옴), `stale`(원본 갱신 실패 등으로 이전 값 제공). **시간표에만 포함**됩니다.
- `stale`: 최신 값임을 보장할 수 없는 응답 표시. 검색·급식 등에도 사용됩니다.
- `sourceUpdatedAt`: 원본이 제공한 갱신 시각. 없으면 `null`.
- `fetchedAt`: 이 백엔드가 데이터를 수집한 시각. **사용자의 요청 시각과 다를 수 있습니다**.
- `isChanged`: 컴시간이 표시한 수업 변경 여부. 변경 이력 엔드포인트의 before/after와 구분됩니다.

이력 API는 `OPENCIGAN_HISTORY_DB`로 명시적으로 활성화된 경우에만 동작합니다. 최초 관측은 기준 데이터만 만들고, 이후 관측한 차이를 `added`/`deleted`/`changed`로 제공합니다. 응답의 `nextCursor`가 있다면 그대로 `cursor`에 넘깁니다. 관측 이력 보존 기간은 최대 30일입니다.

RSS는 `/api/v1/timetable/history.rss?school=1234%3A예시학교&grade=2&class=3` 형식으로 구독합니다. 기본적으로 한국 시간 기준 현재 주의 최근 50건이며, `week=YYYY-MM-DD`로 특정 월요일을 지정할 수 있습니다. 피드 조회는 원본 시간표를 갱신하지 않습니다. 다른 시간표 조회에서 새로 관측된 변경만 표시하므로 모든 변경이나 실시간 알림을 보장하지 않습니다. `ETag`와 `If-None-Match`로 변경 없는 응답을 재검증할 수 있습니다. 원본 데이터의 보존·재제공 조건을 확인하기 전에는 이력 기능을 운영 환경에서 활성화하지 마세요.

필요하면 `subject`, `teacher`(각 1~50자 부분 일치, 대소문자 구분), `weekday`(월~금 1~5), `period`(1~20), `type`(`added`, `deleted`, `changed`)을 조합할 수 있습니다. 과목과 교사는 각각 변경 전이나 변경 후 어느 쪽이든 일치하면 됩니다. 조건을 모두 적용한 뒤 최신 50건을 반환합니다.

`group=daily`를 사용하면 조회된 최대 50건을 수업 날짜별 항목으로 묶습니다. 새 관측이 포함되면 요약 항목의 식별자가 바뀌며, 알림 횟수와 갱신 방식은 RSS 리더에 따라 다릅니다. 기본값 `group=changes`는 변경별 항목입니다.

## 오류 및 호출 정책

| HTTP | `code` | 의미 |
| --- | --- | --- |
| 400 | `invalid_request` | 쿼리 누락/형식 오류 |
| 404 | `not_found` | 지원하지 않는 경로 |
| 405 | `method_not_allowed` | 지원하지 않는 메서드 |
| 429 | `rate_limited` | 현재 프로세스 기준 호출 제한; `Retry-After` 사용 |
| 503 | `history_disabled` | 변경 이력 저장 비활성화 |
| 503 | `upstream_unavailable` | 원본/키/기타 조회 실패. 캐시에 데이터가 없고 재시도 대기 중이면 `Retry-After`에 남은 초를 표시 |

응답 오류에는 `error`(메시지)와 `code`(식별자)가 포함됩니다. Python API의 요청 제한은 **프로세스별 `REMOTE_ADDR`당 60회/60초**이며 `status` 조회는 제외됩니다. 역방향 프록시 뒤에서는 여러 사용자가 같은 IP로 인식될 수 있으므로 이 설정을 그대로 인터넷에 공개하지 마세요. 실패 시 과도한 동시 재시도 대신 `Retry-After`와 백오프를 지키세요.

**공개 API 정책:** CORS 허용은 브라우저의 출처 제한일 뿐 인증이나 원본 데이터 재배포 권한의 대체가 아닙니다. 이용 약관·데이터 권리·악용 방지·프록시 뒤 IP 식별을 검토한 후 별도로 활성화해야 합니다.

[구현 구조](architecture.md) · [운영 가이드](operations/operations.md)
