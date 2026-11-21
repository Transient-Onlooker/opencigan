# 리팩터링 전 QA 기준선

기준 코드: `54f89b935491a404dc251713ca652ad048b0599e`. 이후 `main`의 `4c5fbb5`와 `1f937b5`는 리팩터링 순서·설계 문서만 추가했다. Raspberry Pi API는 `release-54f89b9`, LAN 미리보기는 `release-9372745`이며 두 서비스는 별도 배포다. API 이전 복귀 지점은 `release-7bd443e`와 보존된 기존 systemd drop-in이다. GitHub Pages는 `54f89b9` 이후 Actions에서 배포됐다. Webhook API와 작업자는 운영에서 비활성이다.

- 2026-11-15 로컬 백엔드 166개, Svelte 검사, 프런트 단위 101개 통과. Chromium·WebKit E2E 47개 통과, Windows WebKit 오프라인 검사 1개 건너뜀. `54f89b9` GitHub Actions의 Python·Workers·클라이언트·통합·프런트·브라우저·빌드 및 Pages 배포 성공.
- Pi `release-54f89b9`에서 API·이력·Webhook 경계·WSGI 등 75개 테스트 통과, API 상태 200, Webhook 비활성 응답 확인. LAN 미리보기는 실행 중이나 이전 UI 버전이므로 공개 사이트와 동일하다고 취급하지 않는다.
- 브라우저 자동화는 학교/반·주차와 공유 복원, 늦은 응답, 복수 수업, 급식, 설정, Chromium 오프라인, PNG/PDF, ICS 동의, 모바일 내비게이션 및 Webhook 관리 화면을 모의 데이터로 검증한다. API 테스트는 관리자 인증·요청 제한·ICS ETag와 Webhook 비활성 경계를 다룬다.
- 실제 iOS Safari·Android Chrome, 모바일 캘린더 앱과 서로 다른 외부망 두 곳의 클라이언트 IP는 이 기준선에서 확인하지 않았다. `opencigan.mcv.kr`의 API/ICS 경로는 과거 GitHub Pages 404였으며 기존 Tailscale API 경로를 사용한다. 원본 데이터 재제공 조건은 별도 확인이 필요하다.
- 이전 롤백과 DB 복구 절차는 [운영 가이드](../operations/operations.md) 참고. 리팩터링 PR은 운영 서버를 변경하지 않는다.
