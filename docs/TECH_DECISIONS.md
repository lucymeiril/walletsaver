# 기술 스택 선정 근거 (Tech Decisions)

> 이 문서는 프론트엔드 기술 스택 선정의 **이유**를 기록한다.
> "왜 그걸 선택했고, 대안은 뭐였고, 왜 대안을 안 썼는지"가 면접에서 중요하다.

---

## 1. 빌드 도구: Vite

| 항목 | Vite | Create React App (CRA) | Next.js |
|---|---|---|---|
| 빌드 속도 | 수백ms (esbuild) | 수십초 (webpack) | 수초 (turbopack) |
| HMR | 즉시 | 느림 | 빠름 |
| 설정 | 최소 | 숨김 | 프레임워크 종속 |
| SSR | 불필요 (SPA) | 없음 | 기본 |

**선택 이유**: CRA는 2023년부터 관리 중단 상태. Next.js는 SSR/SSG가 강점이지만 우리는 순수 SPA로 충분하고, 백엔드를 Python FastAPI로 별도 운영할 예정이라 Next.js의 서버 기능이 오히려 복잡도만 높임. Vite는 설정 최소, 빌드 최속.

---

## 2. UI 프레임워크: React 18

**선택 이유**:
- 한국 취업 시장 점유율 1위 (Vue, Angular 대비)
- 생태계 최대 (라이브러리, 커뮤니티, 문서)
- Concurrent Mode로 큰 리스트 렌더링 최적화 (핫딜 피드)
- 졸업작품 → 포트폴리오 → 취업 직결

**안 쓴 것들**:
- **Vue 3**: 좋은 프레임워크지만 한국 채용 시장에서 React보다 수요 적음
- **Svelte**: 번들 작지만 생태계가 아직 작음
- **Angular**: 대기업 레거시 위주, 학습 곡선 높음

---

## 3. 상태 관리: Zustand

| 항목 | Zustand | Redux Toolkit | Jotai | Context API |
|---|---|---|---|---|
| 번들 크기 | ~1KB | ~11KB | ~3KB | 0 (내장) |
| Boilerplate | 거의 없음 | Action+Slice | 거의 없음 | Provider 중첩 |
| DevTools | 지원 | 지원 | 지원 | 없음 |
| 학습 곡선 | 낮음 | 중간 | 낮음 | 낮음 |

**선택 이유**: 우리 앱의 전역 상태는 많지 않다 (현재 선택된 상품, 검색어, 로그인 상태 정도). Redux의 action/reducer/slice 구조는 이 규모에서 과도한 boilerplate. Zustand는 10줄로 스토어 완성 + React 외부에서도 접근 가능 (크롤러 연동 시 유용).

```js
// Zustand 스토어 예시: 이게 전부
const useStore = create((set) => ({
  selectedProduct: null,
  setProduct: (p) => set({ selectedProduct: p }),
}));
```

---

## 4. 스타일링: CSS Modules

| 항목 | CSS Modules | Tailwind | styled-components | Vanilla CSS |
|---|---|---|---|---|
| 스코프 격리 | ✅ 자동 | ❌ 전역 | ✅ 자동 | ❌ 전역 |
| 번들 크기 | 최소 | 큼 (purge 필요) | JS 번들 포함 | 최소 |
| 런타임 비용 | 0 | 0 | 있음 (CSS-in-JS) | 0 |
| DEV_PHILOSOPHY 부합 | ✅ 플러그인 원칙 | ❌ class 범람 | △ JS 의존 | ❌ 전역 충돌 |

**선택 이유**: DEV_PHILOSOPHY에서 "각 컴포넌트는 자기 CSS만 가져야 한다"고 명시. CSS Modules는 파일명 기반 자동 스코프 (`Header.module.css`의 `.nav`는 `Header_nav_a3x2f`로 변환). 컴포넌트 삭제 시 CSS도 같이 삭제 — 누더기 CSS 방지.

**안 쓴 것들**:
- **Tailwind**: class가 너무 길어서 JSX 가독성 파괴. `className="flex items-center gap-2 px-4 py-2 ..."` 이런 JSX는 디자인 변경 시 모든 컴포넌트를 뒤져야 함
- **styled-components**: JS 번들에 CSS가 포함되어 런타임 비용 발생. SSR 시 추가 설정 필요
- **Vanilla CSS**: 기존 프로토타입에서 클래스명 충돌 이미 경험함

---

## 5. 차트: Recharts

**선택 이유**: 기존에 Canvas API로 직접 그래프를 그렸는데, 반응형 리사이즈, 축 라벨, 툴팁, 애니메이션을 다 직접 구현해야 했음. Recharts는 React 컴포넌트 형태로 `<LineChart>`, `<Area>` 등을 조합하면 끝. SVG 기반이라 해상도 독립적.

**안 쓴 것들**:
- **Chart.js + react-chartjs-2**: Canvas 기반이라 SVG보다 고해상도에서 불리, 리사이즈 이벤트 직접 처리 필요
- **D3**: 너무 저수준. 학습 곡선 높음.
- **Nivo**: 무겁고 커스터마이징 복잡

---

## 6. HTTP 클라이언트: Axios

**선택 이유**: fetch API 대비 장점:
- 인터셉터 (토큰 자동 주입, 에러 핸들링 중앙화)
- 요청 취소 (검색 자동완성: 이전 요청 취소 후 새 요청)
- 응답 자동 JSON 파싱
- 타임아웃 설정

---

## 7. 이미지 전략 (핫딜 특화)

핫딜 서비스 특성상 **사진이 매우 많다**. 커뮤니티 글마다 사진, 마트 전단 이미지, 상품 사진 등.

**최적화 전략**:
1. **Lazy Loading**: IntersectionObserver로 뷰포트 진입 시에만 로드
2. **Skeleton UI**: 이미지 로딩 중 회색 플레이스홀더 표시 (레이아웃 시프트 방지)
3. **썸네일**: 서버에서 원본 + 썸네일(300px) 생성, 목록에서는 썸네일만 로드
4. **WebP 우선**: 서버에서 WebP 변환, `<picture>` 태그로 fallback
5. **CDN**: 이미지는 별도 CDN에 저장 (DB에는 URL만)
6. **React.lazy**: 페이지 단위 코드 스플리팅으로 초기 로드 최소화

---

## 8. 라우팅: React Router v6

**선택 이유**: 기존 `data-tab` 방식은 URL이 안 바뀌어서 뒤로가기/북마크 불가. React Router v6는 URL 기반 라우팅 + 중첩 라우트 + lazy loading 기본 지원.

---

## 9. 아이콘: Lucide React

**선택 이유**: 기존에 emoji + inline SVG 혼용했는데, 일관성 없음. Lucide는 200+ 아이콘, 트리 셰이킹 지원 (안 쓰는 아이콘은 번들에 안 들어감), React 컴포넌트 형태.
