# OpenCigan 아키텍처와 데이터 흐름

OpenCigan의 주요 구성 요소와 데이터 흐름을 설명합니다. 운영 현황은 [운영 문서](operations/README.md)에서 확인할 수 있습니다.

## 공개 서비스 구성

```mermaid
flowchart LR
    Browser["브라우저·클라이언트"] --> Web["웹 프런트엔드"]
    Web --> API["읽기 API"]
    API --> Cache["캐시·데이터 변환"]
    Cache --> Timetable["시간표 데이터 제공처"]
    Cache --> Meal["급식 데이터 제공처"]
    Browser -.-> Local["로컬 설정"]
```

- [공식 웹](https://opencigan.mcv.kr/)과 [보조 웹](https://opencigan.pages.dev/)은 같은 읽기 API를 사용합니다.
- 프런트엔드, API, 캐시와 데이터 제공처는 각각 역할을 나누어 처리합니다.

## 주요 코드와 책임

| 경계 | 대표 파일·위치 | 책임 |
| --- | --- | --- |
| 프런트엔드 | `frontend/src/`, `frontend/functions/` | 선택 상태, 시간표·급식·설정 UI, Pages API 라우팅 |
| Python API | `backend/app.py` 및 `backend/`의 라우트 모듈 | 요청 검증, 캐시·JSON/ICS, 관리자 인증과 관측 |
| 내부 시간표 API | `backend/internal_api.py` | 별도 프로세스·토큰 인증·캐시 없는 원본 조회 |
| 시간표·캐시 | `backend/timetable.py`, `backend/cache.py` | 컴시간 조회, 정규화, 프로세스 캐시와 실패 복구 |
| 컴포넌트 배포 | `deploy/prepare_component.py`, `deploy/release_deploy.py`, `deploy/watch_release.py` | 포크 Release 검증, 실조회 후 전환 및 핀 동기화 |
| 급식 | `backend/neis.py` | NEIS 학교 매칭과 식단 조회 |
| 변경 이력 | `backend/history.py` | 관측 스냅샷 비교, 선택적 SQLite 이력 저장 |

## 시간표·급식 처리

1. 브라우저가 선택한 컴시간 학교 ID와 이번 주 또는 다음 주를 요청합니다. 한 번의 서버 조회는 해당 학교의 주간 수업 데이터를 반환하며, 화면은 학년·반·교사 기준으로 재구성합니다.
2. 서버는 `(school, week)` 키의 캐시를 확인합니다. TTL은 기본 1,800초이고 같은 키의 중복 갱신은 프로세스 내에서 병합합니다. 원본 장애 시 일부 요청은 이전 캐시를 반환할 수 있습니다.
3. 시간표의 `cacheStatus`는 `hit`/`miss`/`stale`입니다. `stale`은 최신 원본을 보장하지 않으며, 서버의 원본 수집 시각과 브라우저의 수신 시각도 서로 다릅니다.
4. 컴시간 학교 ID와 NEIS 학교 ID는 다릅니다. 이름·지역으로 후보를 찾되 동명이교는 주소를 비교해 선택합니다. 급식은 NEIS ID와 기간별 캐시를 사용하고 요청당 조회 기간 제한이 있습니다.
5. NEIS API 키 등 비밀값은 백엔드 환경에서만 읽으며, 공개 JavaScript 번들에 넣지 않습니다.

내부 시간표 API는 공개 API의 셔터·스레드 풀·캐시와 분리된 프로세스로 실행합니다. 두 API는 검증된 버전별 pycomcigan 구성 요소를 공유합니다. 내부 인증·응답과 배포·복구 절차는 [운영 문서](operations/internal-timetable.md)를 참고하세요.

## 캘린더·설정·관측 데이터

- **ICS:** `/api/v1/timetable.ics`에서 학급별 구독 URL을 제공합니다. GET/HEAD·ETag/304는 공개 호스트에서 일부 검증됐지만 실제 Apple/Google Calendar의 자동 갱신은 별도 게이트입니다. 실제 교시 시각을 사용하는 모드는 관련 교시 설정이 유효하고 서버가 지원할 때만 제공됩니다.
- **로컬 설정:** 과목 색상·표시 이름·교시 시각·알레르기 표시와 백업은 기본적으로 사용자 브라우저에 보관합니다. 선택적 클라우드 설정 동기화는 **아직 미구현**입니다.
- **이력:** `isChanged`는 컴시간 원본의 변경 표시입니다. `/api/v1/timetable/history`의 SQLite 비교 이력은 서비스가 *관측한 시점 사이*의 차이이며 모든 실제 변경을 뜻하지 않습니다. 이력 DB가 설정되지 않으면 기록하지 않습니다. 사용자용 과거 이력 보기 UI는 제거됐습니다.
- **접속 로그·운영 통계:** 별도의 관리자 인증과 보관·비활성 설정을 사용합니다. 개인정보 처리·원본 재제공 허락 판단은 운영자가 별도로 수행해야 합니다.

[운영 가이드](operations/operations.md) · [클라우드 배포 기록](operations/cloudflare-tunnel-rollout.md) · [API 문서](api-guide.md) · [로드맵](roadmap/README.md)
