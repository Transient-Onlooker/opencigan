# 접속 로그 관리자 화면

`/access-logs.html`에서 관리자 접속 로그를 조회합니다. 통계 화면(`/analytics.html`)의 링크로 이동하거나, 화면 상단에서 통계 화면으로 돌아갈 수 있습니다.

## 인증 및 개인정보

- 인증은 분석·이력 통계·제안 관리와 공유하는 `OPENCIGAN_ADMIN_TOKEN` Bearer 토큰을 사용합니다.
- 토큰은 현재 페이지 메모리에서만 사용하며 local/session storage, 쿠키, URL에 저장하지 않습니다. 잠금 버튼은 진행 중인 요청을 취소하고 토큰과 로그 표시를 지웁니다.
- API 요청은 `credentials: omit`, `cache: no-store`, `referrerPolicy: no-referrer`를 사용합니다. 화면에는 `/api/v1/admin/access-logs` 외 분석 요청이나 원격 자원이 없습니다.
- 서버는 응답에 `Cache-Control: no-store`를 적용합니다. CSV도 사용자 입력 필터를 적용해 Bearer 인증 헤더와 함께 직접 요청하며, 서버 CSV 수출 한도는 최신 5,000건입니다.

## 필터와 페이지 이동

클라이언트 IP, 학교 ID, 학년, 반, KST 시작일/종료일, 경로, HTTP 상태 코드, 출처 분류(`frontend`, `external`, `unknown`), 캐시 상태(`hit`, `miss`, `stale`)와 페이지당 조회 건수를 지정할 수 있습니다. JSON 응답의 `next_cursor`가 있으면 “더 보기”로 다음 페이지를 불러옵니다. 새 필터 조회는 이전 요청을 취소하고 처음부터 다시 표시합니다.

CSV 다운로드는 페이지 커서를 보내지 않으며 필터에 맞는 최신 최대 5,000건을 가져옵니다. CSV는 브라우저 Blob으로 다운로드되며 객체 URL은 즉시 해제됩니다.

## 구현

정적 페이지는 `admin.css`를 재사용하고 Vite 다중 페이지 빌드의 `accessLogs` 입력으로 등록합니다. 결과 표는 생성한 셀의 `textContent`로만 렌더링해 로그의 텍스트를 HTML로 해석하지 않습니다.

