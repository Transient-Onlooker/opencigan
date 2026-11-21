# 관측 변경 통계

관리자용 이력 통계는 기본적으로 꺼져 있다. 격리 환경에서만 `OPENCIGAN_HISTORY_STATS_ENABLED=1`, 기존 `OPENCIGAN_HISTORY_DB`, 관리자 토큰 `OPENCIGAN_ANALYTICS_ADMIN_TOKEN`을 설정해 `/api/v1/admin/history-stats?school=...&week=YYYY-MM-DD`를 조회할 수 있다. 토큰은 `Authorization: Bearer ...` 헤더로 전달한다. 현재 공개 게이트웨이는 이 경로를 제공하지 않는다.

응답은 최근 30일 동안 저장된 관측 변경만 집계한다. `observed=false`와 `totalChanges=null`은 유효한 최근 관측이 없음을 뜻한다. 기준선만 수집된 경우 관측된 변경은 0건일 수 있지만 실제 변경이 없었다는 의미는 아니다. `retainedSince`는 조회 시점 기준 보존 하한이며 최초 관측 시각이 아니다. 수집 사이의 변경이나 삭제된 이전 이력은 통계에 포함되지 않는다. 컴시간 원본의 `isChanged`와 별개다.
