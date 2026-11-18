# 라이선스 및 저작권 안내 (Licensing)

Opencigan의 코드 라이선스, 원작자 출처 표시 규정, 외부 데이터 및 종속 소프트웨어 권한 관계를 설명합니다.

## 1. 코드 라이선스 (AGPL-3.0-only)

별도 라이선스가 있는 제3자 코드를 제외한 Opencigan 코드는 [GNU Affero General Public License v3.0 전용 (AGPL-3.0-only)](../LICENSE)으로 제공합니다.

- **저작권자**: `Transient-Onlooker` (저작권 표시: `Copyright (c) 2026 Transient-Onlooker`)
- **식별자 (SPDX)**: `AGPL-3.0-only`
- **전문**: 루트의 [LICENSE](../LICENSE)에 AGPL v3 전문을 수록했습니다. 공식 GNU 배포 URL은 <https://www.gnu.org/licenses/agpl.txt>입니다. 직접 다운로드에 실패해 아래 SPDX 자료와 독립 대조했습니다.

### LICENSE 출처와 검증

- 수록본 출처: 로컬 `AppleRemoteWin/LICENSE`에 있던 라이선스 문서 전문입니다. 해당 프로젝트의 코드나 추가 조건은 가져오지 않았습니다.
- 독립 대조 자료: [SPDX AGPL-3.0-only 전문](https://raw.githubusercontent.com/spdx/license-list-data/31846481de7ea17d92f2f46fad76abe58b2e9bb0/text/AGPL-3.0-only.txt). [SPDX 메타데이터](https://raw.githubusercontent.com/spdx/license-list-data/31846481de7ea17d92f2f46fad76abe58b2e9bb0/json/details/AGPL-3.0-only.json)는 위 GNU 공식 URL을 참조합니다.
- 검증 결과: 공백·줄바꿈을 단일 공백으로 정규화하고 FSF/GNU URL 세 곳의 `https`를 SPDX의 `http`와 맞추면 문서 전체가 일치합니다. 원시 바이트가 같은 파일이라는 뜻은 아닙니다. LICENSE 자체는 이 대조를 위해 변경하지 않았습니다.
- 수록본 SHA-256 (UTF-8, LF, 34,523바이트): `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`.

LICENSE 말미의 적용 예시에 있는 “or any later version”은 예시 문구입니다. Opencigan의 라이선스 선택은 `AGPL-3.0-only`이며, 제7조(b) 추가 조건은 [NOTICE](../NOTICE)에 따로 명시합니다.

수정한 프로그램이 네트워크를 통해 사용자와 상호작용하면 AGPL 제13조에 따라 해당 사용자에게 대응 소스에 접근할 기회를 제공해야 합니다. 구체적인 의무는 LICENSE 전문을 따릅니다.

## 2. AGPL-3.0 제7조 (b) 항에 따른 원작자 출처 표시 요건

AGPL-3.0 제7조(Additional Terms) (b) 항에 따라, 본 저작물을 바탕으로 네트워크를 통해 대외 서비스를 제공하거나 배포하는 경우 다음과 같은 합리적 출처 표시 보존 조건을 적용합니다.

- **웹사이트 및 웹 애플리케이션**: 메인 랜딩 페이지 하단(푸터) 또는 이용자가 쉽게 확인할 수 있는 공개 영역에 원작자(`Transient-Onlooker`)와 [원본 GitHub 저장소](https://github.com/Transient-Onlooker/opencigan)로 연결되는 클릭 가능한 하이퍼링크를 유지해야 합니다.
- **비웹 애플리케이션 및 모바일 앱**: 웹 형태가 아닌 배포물(예: 네이티브 앱, 위젯, 데스크톱 앱)은 '정보(About)', '설정', 또는 그에 준하는 공개 화면에 원작자명과 원본 저장소 링크를 사용자가 명확히 확인할 수 있도록 표시해야 합니다.
- **적용 범위**: 이 조건은 해당 저작물과 수정본의 합리적 저작자 표시에 한정합니다. API만 호출하는 독립 프로그램에는 적용하지 않습니다. 제7조가 허용하는 추가 허락·추가 제한 제거 권리는 제한하지 않습니다.

## 3. 코드 라이선스와 데이터 이용 권한의 분리

Opencigan의 코드 라이선스는 오직 프로그램 구현물에만 적용되며, 연동되는 원본 데이터의 저작권이나 지식재산권을 포함하지 않습니다.

- **컴시간 (시간표 원본 데이터)**: 코드 라이선스는 컴시간 데이터의 조회·캐싱·재배포 허락을 부여하지 않습니다. 이용하려는 방식에 적용되는 출처의 조건을 별도로 확인해야 합니다.
- **NEIS OpenAPI (학교·급식 정보)**: 코드 라이선스는 NEIS 데이터에 새 라이선스를 부여하지 않습니다. 해당 API 및 개별 데이터의 이용 조건을 별도로 확인해야 합니다.

2026-11-18 확인: [나이스 교육정보 개방 포털 이용약관(안) 제11조](https://open.neis.go.kr/portal/userAgreementPage.do)는 기관 제공 데이터의 저작자·출처 표시를 원칙으로 하며, 제3자 권리가 있는 개별 데이터에는 해당 권리자의 조건이 적용된다고 안내합니다. [공공데이터포털 급식식단정보](https://www.data.go.kr/data/15139198/openapi.do)는 제공기관을 교육부로 표시합니다. 급식 화면과 API 안내에 출처를 표시했으며, 개별 데이터 조건 및 컴시간 자료의 이용 허락은 별도로 확인해야 합니다.

이 문서는 데이터의 소유권을 판단하거나 컴시간·NEIS 데이터의 재사용 허락을 검증했다는 의미가 아닙니다.

## 4. 외부 의존성 및 제3자 라이선스 고지

확인한 주요 의존성은 다음과 같습니다. 각 구성요소의 저작권·허락·면책 고지와 번들된 의존성 고지 전문을 보존해야 하며, 아래 요약으로 대체할 수 없습니다.

- **pycomcigan**: MIT, `Copyright (c) 2023 hegelty`. [requirements.txt의 고정 커밋 LICENSE](https://github.com/hegelty/pycomcigan/blob/6fc801068e3793d17bc3523082e7afbcf05d2d92/LICENSE)를 확인했습니다. 설치본 1.4.4는 다른 커밋 `6ac58dd6304b8bb0a3c22c6543bbcfccc2988dd1`이므로 설치 메타데이터만으로 고정 커밋을 검증하지 않았습니다.
- **Pretendard Font**: SIL Open Font License, Version 1.1 (Copyright (c) 2021 Kil Hyung-jin). 상세 라이선스는 [PRETENDARD-LICENSE.txt](../frontend/PRETENDARD-LICENSE.txt) 참조.
- **Svelte 5.57.3 / Vite 6.4.6**: 코어 MIT. 설치된 각 패키지의 `LICENSE.md`를 확인했습니다. Vite 파일에는 번들된 의존성의 별도 라이선스도 포함됩니다.
- **pdf-lib 1.17.1**: MIT. 설치된 패키지의 `LICENSE.md`를 확인했습니다.
- **requests 2.34.2**: Apache-2.0. `.venv/Lib/site-packages/requests-2.34.2.dist-info/licenses/`의 `LICENSE`와 `NOTICE`를 확인했습니다.
- **waitress**: ZPL-2.1. 현재 `.venv`에는 설치되어 있지 않습니다. [v3.0.0 LICENSE.txt](https://github.com/Pylons/waitress/blob/v3.0.0/LICENSE.txt) 및 [COPYRIGHT.txt](https://github.com/Pylons/waitress/blob/v3.0.0/COPYRIGHT.txt)를 확인했으며, 향후 설치되는 버전까지 검증한 것은 아닙니다.

확인한 저작권 문구와 근거 위치는 [NOTICE](../NOTICE)에 정리했습니다. 전체 직접·전이 의존성의 라이선스 호환성이나 다른 저장소에서 가져온 코드의 재사용 권한을 전수 검증한 것은 아닙니다.
