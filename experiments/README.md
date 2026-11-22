# 실험 프로젝트

현재 서비스의 운영 경로와 분리해 보존하는 과거 Cloudflare Workers 실험입니다. 현재 운영 Worker 소스는 [cloudflare-gateway](../cloudflare-gateway/README.md)에 있습니다.

| 프로젝트 | 역할 | 유지 이유 |
| --- | --- | --- |
| [phase0](phase0/README.md) | pycomcigan import 중심의 초기 로컬 스파이크 | 당시 호환성 판정과 재현 기록 |
| [phase0-mvp](phase0-mvp/README.md) | 고정 MVP 버전의 로컬 Workers 실험 | 패키징·wheel·런타임 호환성 재현 |
| [workers-api](workers-api/README.md) | 과거 Workers/D1 API 실험 | Worker·D1·마이그레이션 테스트가 CI에서 계속 실행됨 |

**폴더 관계:** 세 프로젝트는 재현 스크립트와 wheelhouse를 상대 경로로 참조하므로 같은 experiments 아래의 형제 디렉터리로 유지합니다. 특히 phase0-mvp는 ../workers-api/wheelhouse/의 wheel을 사용합니다.

이 디렉터리의 코드는 현재 공개 서비스 요청 경로에 연결되지 않습니다. 다만 CI에서 검사하는 workers-api를 임의로 삭제하거나 테스트 대상에서 제외하지 마세요.
