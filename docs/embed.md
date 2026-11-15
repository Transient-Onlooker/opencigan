# Opencigan 시간표 임베드 위젯 및 Embed Builder 가이드

이 문서는 외부 웹사이트, 개인 블로그, 학교 홈페이지, 노션(Notion) 대시보드 등 다양한 웹 환경에 Opencigan 시간표를 iframe으로 삽입할 수 있는 컴팩트 읽기 전용 위젯(`embed.html`)과 위젯 생성기(`embed-builder.html`)의 연동 규약 및 보안 경계를 설명합니다.

---

## 1. 개요 및 구조

- **`frontend/embed.html`**: 외부 iframe 삽입용 컴팩트 읽기 전용 시간표 위젯 페이지입니다.
- **`frontend/embed-builder.html`**: 관리자나 웹마스터가 실제 학교를 검색하고 학년/반/주간/테마를 선택하여 위젯을 실시간으로 미리보고 iframe 코드를 복사할 수 있는 도구입니다.
- **독립적인 번들**: 메인 앱(`index.html`)과 분리되어 가벼운 읽기 전용 렌더링을 제공하며, 불필요한 설정 저장소나 개인화 로직 없이 순수 API 데이터만 안전하게 표 형태로 표시합니다.

---

## 2. URL 해시(Fragment) 연동 규약

위젯 설정은 **URL fragment (`#`)** 에 들어가며 페이지 요청에는 전송되지 않습니다. 시간표를 불러올 때 학교·학년·반 정보는 API 서버에 전달됩니다.

### 파라미터 형식
`embed.html#school={id}&grade={grade}&class={class}&name={name}&region={region}&week={current|next}&theme={auto|light|dark}`

| 매개변수 | 필수 여부 | 형식 / 유효 범위 | 설명 |
|---|---|---|---|
| `school` | **필수** | `^[0-9]+:[^:]{1,50}$` (최대 100자) | 컴시간 학교 고유 식별자 (예: `2:봄빛고등학교`) |
| `grade` | **필수** | `^[1-6]$` | 학년 (1~6) |
| `class` | **필수** | `^[1-9][0-9]?$` | 반 (1~99) |
| `name` | 선택 | 문자열 (최대 50자) | 학교 표시명 (생략 시 `school`의 뒷부분 사용) |
| `region` | 선택 | 문자열 (최대 100자) | 관할 교육청/지역명 |
| `week` | 선택 | `current` 또는 `next` (기본값: `current`) | `current`: 현재 주차 (월요일 기준 자동 롤링), `next`: 다음 주차 |
| `theme` | 선택 | `auto`, `light`, `dark` (기본값: `auto`) | `auto`: 시스템 prefers-color-scheme 감지 |

---

## 3. iframe 삽입 코드 형식 및 옵션

### 기본 권장 코드 (Default / Safe)
```html
<iframe
  src="https://your-domain.com/embed.html#school=2%3A%EB%B4%84%EB%B9%9B%EA%B3%A0%EB%93%B1%ED%95%99%EA%B5%90&grade=2&class=7&week=current&theme=auto"
  width="100%"
  height="380"
  frameborder="0"
  loading="lazy"
  title="봄빛고등학교 2학년 7반 시간표"
  style="border:1px solid #d4d4d4;border-radius:0">
</iframe>
```

---

## 4. iframe sandbox 속성과 보안 경계 (Security Boundary)

### 왜 기본 스니펫에는 `sandbox` 속성을 강제하지 않는가?
1. **CORS 및 Fetch 제약**:
   - `sandbox="allow-scripts"`만 지정하고 `allow-same-origin`을 생략하면, iframe 내부 문서의 origin이 고유 불투명(opaque origin: `null`)으로 취급됩니다.
   - 이 경우 API 서버(`/api/v1/timetable`)로 요청을 보낼 때 `Origin: null`이 전송되어, 엄격한 CORS 정책이 적용된 환경이나 동일 출처 프록시 환경에서 시간표 API 조회가 브라우저 보안에 의해 차단될 수 있습니다.
2. **`allow-scripts allow-same-origin` 조합의 주의점**:
   - 동일 도메인(Same Origin)에서 호스팅되는 위젯에 `sandbox="allow-scripts allow-same-origin"`을 동시에 부여하면, 스크립트가 iframe 내부에서 상위 페이지의 쿠키나 DOM에 접근할 수 있어 sandbox 탈출(Sandbox Escape)이 가능해집니다.
3. **권장 모델**:
   - **일반 웹페이지/홈페이지/블로그**: 기본적으로 `sandbox` 속성을 생략하거나 위젯을 별도 서브도메인(별도 Origin)에 호스팅하여 격리하는 것이 안전하고 호환성이 높습니다.
   - **엄격한 보안 환경 (Strict Sandbox)**:
     - 만약 외부 사이트 정책상 `sandbox`가 강제되는 경우: `sandbox="allow-scripts allow-same-origin"`을 명시해야 API 요청(fetch)과 동적 DOM 렌더링이 정상 동작합니다.
     - 단, 완전히 다른 도메인(Cross-Origin)에서 임베드하는 경우에는 상위 페이지 탈출 위험이 없으므로 안전합니다.

---

## 5. 보안 및 프라이버시 보장 (Privacy & Security)

- **`localStorage` / 쿠키 / 세션 격리**:
  - 위젯(`embed.ts`)은 브라우저의 `localStorage`, `sessionStorage`, `IndexedDB` 또는 사용자 설정(알레르기, 개인 시간표, 숨김 과목 등)에 전혀 접근하지 않습니다.
  - 위젯은 부모 페이지의 사용자 설정을 읽거나 전송하는 기능을 제공하지 않습니다. 호스팅 출처와 부모 사이트의 자체 정책은 별도입니다.
- **XSS 및 인젝션 방지**:
  - URL fragment 매개변수는 엄격한 정규식(`^[0-9]+:[^:]{1,50}$`, `^[1-6]$`, `^[1-9][0-9]?$`)과 길이 제한(4,096자)으로 검증됩니다.
  - API 응답값(과목명, 교사명 등)은 HTML raw string(`innerHTML`)으로 삽입되지 않으며, `textContent`를 통해서만 안전하게 DOM에 바인딩됩니다.
- **API 주소 설정**:
  - 하드코딩된 API 주소를 사용하지 않으며, `src/api.ts`에 정의된 Vite 환경 변수(`VITE_API_BASE_URL`)를 준수합니다.
