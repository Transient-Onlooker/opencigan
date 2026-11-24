# OpenCigan 문서 안내

문서는 **현재 참고 문서**, **운영 문서**, **QA 기록**, **로드맵**, **과거 보관 자료**로 나눕니다. 처음 방문했다면 [프로젝트 README](../README.md) → [아키텍처](architecture.md) → [전체 로드맵](roadmap/README.md) 순서로 읽으면 됩니다.

## 시작하기와 API 참고

| 주제 | 문서 | 용도 |
| --- | --- | --- |
| 프로젝트 소개 | [메인 README](../README.md) | 서비스 주소·기능·사용 방법 |
| 구조 이해 | [아키텍처](architecture.md) | 공개 서비스 흐름과 코드 책임 |
| 개발 시작 | [개발 가이드](development.md) · [기여 가이드](../CONTRIBUTING.md) | 로컬 실행·테스트·PR |
| API 사용 | [API 가이드](api-guide.md) · [OpenAPI 3.1](openapi.yaml) | REST·ICS 계약 |
| API 계약 유지 | [버전·호환 정책](api-versioning.md) | API 버전·오류·캐시 계약 |
| 클라이언트 | [Python/TypeScript 예제](client-examples.md) | SDK 사용법 |
| 임베드 | [위젯 가이드](embed.md) | iframe 연동 |
| 기타 | [라이선스](licensing.md) · [내비게이션 상태](navigation.md) · [NEIS 영양 필드](neis-nutrition.md) | 권한·구현 참고 |

## 운영 문서

운영·보안·관측 문서는 [운영 문서 색인](operations/README.md)에서 찾을 수 있습니다.

- [운영 절차](operations/operations.md)
- [내부 시간표 API와 컴포넌트 배포](operations/internal-timetable.md)
- [프록시 IP 신뢰 경계](operations/proxy-client-ip.md)
- [접속 로그](operations/access-logs.md) · [관리자 화면](operations/access-log-ui.md)
- [이용 통계](operations/analytics.md) · [Webhook](operations/webhooks.md)
- [Cloudflare 이전 검증 기록](operations/cloudflare-tunnel-rollout.md)

## 품질 및 QA

[QA 문서 색인](qa/README.md)에서 현재 알려진 문제와 과거 검증 기록을 구분합니다.

- [알려진 문제](qa/known-issues.md)
- [QA·브라우저·성능·검증 기록](qa/)

## 로드맵

[전체 로드맵](roadmap/README.md)에서 P0~P4의 진행 방향과 세부 작업을 확인합니다.

- [2026-11-21 단기 작업 기록](roadmap/short-term-2026-11-21.md)
- [핵심 품질·운영](roadmap/core-quality.md)
- [사용자 경험](roadmap/user-experience.md)
- [API·운영](roadmap/api-operations.md)
- [자동화·장기 확장](roadmap/automation-and-future.md)
- [리팩터링·릴리스](roadmap/refactoring-and-release.md)
- [리팩터링 실행 설계](roadmap/refactoring-plan.md)

## 과거 자료

[보관 문서 색인](archive/README.md)에는 초기 기획과 과거 작업 메모를 보존합니다. 현재 구현·정책의 기준으로 사용하지 마세요.
