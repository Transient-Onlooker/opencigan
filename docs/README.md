# OpenCigan 문서 안내

프로젝트 문서의 **현재 참고 기준**과 **과거 QA·실험 기록**을 구분합니다. 처음 방문했다면 [루트 README](../README.md) → [아키텍처](architecture.md) → [전체 로드맵](roadmap.md) 순서로 읽으면 됩니다.

## 바로 찾아보기

| 주제 | 문서 | 용도 |
| --- | --- | --- |
| 프로젝트 소개 | [메인 README](../README.md) | 공식·보조 주소, 기능, 기본 이용 방법 |
| 서비스 흐름 | [아키텍처](architecture.md) | Pages → Worker → VPC → Pi, 컴시간/NEIS |
| 오늘의 개발 | [2026-11-21 단기 로드맵](roadmap/short-term-2026-11-21.md) | 구현·자동 테스트에 집중한 ST-00~ST-14 작업 큐 |
| 장기 백로그 | [전체 로드맵](roadmap.md) | P0~P4 우선순위와 의존 관계 |
| 구현·기여 | [개발 가이드](development.md) · [기여](../CONTRIBUTING.md) | 로컬 실행·테스트·PR |
| 외부 연동 | [API 가이드](api-guide.md) · [OpenAPI](openapi.yaml) · [클라이언트](client-examples.md) | REST/ICS 계약·예시 |
| 운영·보안 | [운영 절차](operations.md) · [IP 신뢰](proxy-client-ip.md) · [접속 로그](access-logs.md) | 배포·인증·개인정보 경계 |
| 알림·관리 | [Webhook](webhooks.md) · [분석](analytics.md) · [접속 로그 UI](access-log-ui.md) | 일부 기능은 비활성/운영 조건 적용 |
| 라이선스·원본 | [라이선스](licensing.md) · [급식 출처](neis-nutrition.md) | 소스 코드 권한과 제3자 데이터 조건 구분 |

## 상세 로드맵

- [P0 · 안정성·보안·공개 전 검증](roadmap/core-quality.md)
- [P1 · 사용자 경험·성능](roadmap/user-experience.md)
- [P2 · API·연동·클라우드 설정](roadmap/api-operations.md)
- [P3/P4 · 알림·장기 확장](roadmap/automation-and-future.md)
- [리팩터링·릴리스 게이트](roadmap/refactoring-and-release.md)

## QA·운영 사실을 확인할 때

| 내용 | 근거 |
| --- | --- |
| Cloudflare Worker/Pi 배포 이력·롤백 절차 | [Cloudflare 전환·운영 기록](cloudflare-tunnel-rollout.md) |
| 알려진 결함과 사용자 제보 | [알려진 문제](known-issues.md) · [2026-11-16 QA](qa-2026-11-16.md) · [2026-11-17 QA](qa-2026-11-17.md) |
| 리팩터링 결정과 검증 | [리팩터링 계획](refactoring-plan.md) · [기준선](refactoring-baseline-2026-11-15.md) |
| 과거 테스트 증거 | [2026-11-14 브라우저 QA](browser-qa-2026-11-14.md) · [2026-11-15 검증](verification-2026-11-15.md) |

**문서 읽기 원칙:** 날짜가 적힌 QA 문서는 그날 확인한 사실을 기록합니다. 이후 PR·배포로 변경된 현재 상태를 추정하지 마세요. 로드맵의 `[x]`는 특정 구현/검증의 완료이지 서비스 전체 출시 승인이 아닙니다.
