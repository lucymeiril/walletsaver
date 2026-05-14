# 바이어 평가 보고서 — 지갑 지키미 v0.1

> **평가일:** 2025-07  
> **평가 대상:** `packages/website/frontend/` (사용자 대면 웹 프론트엔드)  
> **평가팀:** UX 디자이너 · 프로그래머 · 기획자 · 테스터 · 고객 대표  

---

## 종합 평가: B−

| 영역 | 등급 | 한줄평 |
|------|------|--------|
| UX/UI | B | 정보 계층이 잘 잡혀 있고 다크모드까지 지원하나, 접근성·반응형 검증 부족 |
| 기능 완성도 | C+ | 핵심 기능 스켈레톤은 갖춰졌으나, 100% mock 데이터로 구동 — 실서비스 불가 |
| 코드 품질 | B+ | Zustand + CSS Modules + lazy loading 등 현대적 아키텍처, 다만 테스트 커버리지 극히 낮음 |
| 안정성/에러 처리 | C | 네트워크 에러, 빈 상태, 404 등 edge case 대부분 미처리 |
| 경쟁력 | B− | 가격 판단 엔진(타이밍 뱃지, DB 평균 비교)은 차별화 포인트, 그러나 아직 데모 수준 |

**결론:** MVP 데모로서는 인상적인 완성도. 구매 결정을 위해서는 **(1) 실 API 연결, (2) 에러 처리 보강, (3) 접근성·반응형 검증**이 선행되어야 함.

---

## 1. UX/UI 평가

### 강점

1. **명확한 가치 제안 (Value Proposition)**
   - `HomePage.jsx:42-43` — 히어로 섹션 "이 가격, 진짜 싼 건가요?" 카피가 사용자 pain point를 정확히 짚음
   - "정부 공식 물가 + 마트 전단 데이터로 지금 사도 될지 알려드립니다" — 데이터 신뢰성 강조

2. **직관적 가격 판단 시스템**
   - `PricePage.jsx:36-39` — 4단계 타이밍 뱃지 (🔥 역대급 / 💙 좋은 가격 / ✅ 괜찮음 / ⏳ 기다려) — 비전문가도 즉시 이해 가능
   - `PricePage.jsx:99-109` — 가격 등급 바 (5단계 컬러 존 + 마커) — 현재 가격이 전체 범위에서 어디인지 시각적으로 표현

3. **다크 모드 지원**
   - `tokens.css:170-187` — 완전한 다크 모드 변수 세트
   - `appStore.js:117-120` — 테마 토글 + localStorage 영속화

4. **코드 스플리팅**
   - `App.jsx:12-17` — 6개 페이지 모두 `lazy()` + `Suspense` 적용 — 초기 로드 최소화

5. **잘 구성된 정보 계층**
   - 홈 → 검색 히어로 → 관심 품목 → 오늘의 물가 → 핫딜 → 마트 BEST → 레시피 계산기
   - 사용자 관심도 순으로 자연스러운 스크롤 흐름

6. **공유 기능 통합**
   - `ShareButton.jsx` — 링크 복사 / 카카오톡 / 트위터 공유 팝업
   - 홈페이지 마트 카드, 핫딜 카드, 가격비교 페이지 등 주요 지점에 배치

### 개선 필요사항 (우선순위별)

#### 🔴 P0 — 즉시 수정

1. **index.html `lang="en"` → `lang="ko"` 변경 필요**
   - `index.html:2` — 한국어 서비스인데 `<html lang="en">` → 스크린리더가 영어로 읽으려 시도
   - 검색 엔진 최적화(SEO)에도 악영향

2. **LoginModal: DOM 직접 조작 안티패턴**
   - `LoginModal.jsx:9` — `document.getElementById('modal-login')?.classList.add('open')` 
   - `Header.jsx:43-44` — 동일한 패턴으로 모달 열기
   - React 상태가 아닌 DOM classList로 모달 visibility 제어 → **React DevTools에서 상태 추적 불가**, 테스트 불가
   - **수정안:** Zustand store에 `isLoginModalOpen` 상태 추가, `Modal.jsx` 공통 컴포넌트 활용

3. **404 페이지 미구현**
   - `App.jsx:39-47` — 정의되지 않은 경로 접근 시 빈 화면 표시
   - `<Route path="*" element={<NotFoundPage />} />` 추가 필요

4. **검색 입력 접근성 부재**
   - `HomePage.jsx:48-56` — `<input>` 에 `aria-label`, `role="combobox"`, `aria-expanded`, `aria-activedescendant` 누락
   - 자동완성 드롭다운(`acList`)에 `role="listbox"` 누락
   - 키보드 네비게이션(ArrowUp/Down) 미구현 — 마우스 없이 선택 불가

#### 🟡 P1 — 다음 스프린트

5. **Header 알림 벨: 빈 기능**
   - `Header.jsx:96-98` — 알림 버튼이 존재하지만 클릭 시 아무 동작 없음
   - `appStore.js` — `notifications` 상태 자체가 정의되지 않음 → `unreadCount`는 항상 0
   - 사용자 기대를 깨뜨리는 데드 버튼

6. **Header 프로필 버튼: 로그아웃만 됨**
   - `Header.jsx:102-103` — 로그인 상태에서 프로필 아이콘 클릭 시 즉시 로그아웃
   - 프로필 페이지, 설정 메뉴 없이 바로 로그아웃 → UX 혼란

7. **핫딜 카드: 외부 링크 미연결**
   - `HotdealPage.jsx:40` — 카드 클릭 시 DetailModal만 열림, 원본 핫딜 사이트 링크(`d.url`) 접근 불가
   - 사용자가 실제 구매 페이지로 이동할 수 없음

8. **LocalPage 지도: 완전한 placeholder**
   - `LocalPage.jsx:22-26` — "지도 API 연결 시 위치가 표시됩니다" 텍스트만 존재
   - 주유소/식당 데이터가 강남구 고정 — 위치 기반 기능 전무
   - 지도 없는 "동네 물가 지도" 페이지는 사용자 신뢰도 하락

9. **ToastContainer: 두 벌 존재**
   - `components/common/ToastContainer.jsx` — 인라인 스타일 기반, Zustand `toasts` 사용
   - `components/common/Toast.jsx` — CSS Module 기반, 별도 props 기반
   - `App.jsx:52` — 전자만 마운트됨. 후자(Toast.jsx)의 `ToastContainer`는 사장 코드
   - 토스트 type이 `error`일 때도 `borderLeft` 색상이 `var(--accent)` (파란색) → 에러 느낌 미전달

10. **Footer 링크: 모두 `href="#"`**
    - `Footer.jsx:13-15` — 이용약관, 개인정보처리방침, 문의 — 전부 빈 링크

#### 🟢 P2 — 향후 개선

11. **BottomNav 뱃지 카운트 미연결**
    - `BottomNav.jsx:13` — `badgeCounts` prop 받지만, `App.jsx:51`에서 prop 전달 없음 → 항상 0

12. **검색 히어로에서 "결과 없음" 상태 미처리**
    - `HomePage.jsx:59-72` — `matches.length > 0` 일 때만 드롭다운 → 검색어 입력했는데 결과 없으면 아무 피드백 없음
    - "검색 결과가 없습니다" 메시지 필요

13. **인기 검색어 하드코딩**
    - `HomePage.jsx:11` — TRENDING 배열이 코드에 직접 박혀있음 → 실시간 반영 불가

14. **가격 추이 차트: 매 렌더마다 랜덤 데이터 생성**
    - `mockData.js:56-68` — `genPriceHistory`에 `Math.random()` 사용 → 같은 상품이라도 페이지 재방문 시 다른 차트
    - `PricePage.jsx:20` — `useMemo` 적용했지만 `range` 변경 시 재생성 → 30일→90일→30일 전환 시 차트 불일치

---

## 2. 기능 완성도 평가

### 구현된 기능 ✅

| 기능 | 파일 | 완성도 | 비고 |
|------|------|--------|------|
| 상품 검색 + 자동완성 | `HomePage.jsx:18-30` | 70% | mock 데이터 12개 상품만 검색 가능 |
| 가격 추이 차트 | `PricePage.jsx:112-141` | 80% | Recharts AreaChart, 30/90/365일 전환 |
| 가격 타이밍 뱃지 | `PricePage.jsx:35-39` | 90% | 4단계 등급 + 설명 텍스트 |
| 마트별 가격 비교 | `PricePage.jsx:159-178` | 85% | 4개 마트 실제 가격 비교 |
| 상품 속성 변형 | `PricePage.jsx:69-83` | 90% | 냉장/냉동/국산/수입 분류 |
| 핫딜 목록 + 필터/정렬 | `HotdealPage.jsx:9-19` | 75% | 카테고리 필터, 최신/할인율/인기순 정렬 |
| DB 평균 대비 비교 뱃지 | `HotdealPage.jsx:34-37` | 85% | 핫딜 가격 vs DB 평균 자동 비교 |
| 마트 전단 할인 정보 | `MartPage.jsx:5-41` | 70% | 4개 마트 탭, 상품별 할인율 |
| 동네 주유소 가격 비교 | `LocalPage.jsx:11-13` | 60% | 정렬 + 전국 평균 비교, 지도 미구현 |
| 동네 식당 가격 비교 | `LocalPage.jsx:58-81` | 60% | 메뉴별 시세 대비 비교 |
| 커뮤니티 핫딜 공유 | `CommunityPage.jsx:17-68` | 75% | 글쓰기 + 카테고리 + 이미지 업로드 |
| 자동 가격 검증 | `mockData.js:263-271` | 80% | 커뮤니티 글쓰기 시 허위가격 탐지 |
| 관심 품목 관리 | `appStore.js:41-49` + `FavoritesDashboard.jsx` | 85% | 추가/삭제 + localStorage 영속화 |
| 장보기 리스트 | `ShoppingListPanel.jsx` + `ShoppingOptimizer.jsx` | 80% | FAB + 패널 + 마트별 최적 조합 |
| 집밥 비용 계산기 | `RecipeCalculator.jsx` | 90% | 외식 vs 집밥 비교, 5개 레시피 |
| 다크 모드 | `tokens.css:170-187` | 90% | 완전한 변수 세트 + 토글 |
| 최근 검색 | `appStore.js:53-59` | 85% | 10개까지 저장 + 삭제 |
| 공유 기능 | `ShareButton.jsx` | 65% | 링크 복사 작동, 카카오톡은 TODO |

### 미구현/불완전 기능 ❌

| 기능 | 현황 | 심각도 |
|------|------|--------|
| **실 API 연결** | 서비스 레이어(`api.js`, `hotdealService.js` 등) 존재하나 **어디서도 호출되지 않음**. 모든 페이지가 `mockData.js` import | 🔴 Critical |
| **로그인/회원가입** | `LoginModal.jsx:12-14` — form submit 시 입력값 무시, 하드코딩된 '테스트유저'로 로그인 | 🔴 Critical |
| **소셜 로그인** | `LoginModal.jsx:40-41` — 카카오/네이버 버튼 존재하나 클릭 시 아무 동작 없음 | 🟡 Important |
| **회원가입 검증** | `LoginModal.jsx:44-48` — 비밀번호 확인 일치 검증 없음, 최소 길이 검증 없음 | 🟡 Important |
| **게시글 영속화** | `CommunityPage.jsx:56` — "게시글이 등록되었습니다! (데모)" → 실제 저장 없음 | 🔴 Critical |
| **댓글 영속화** | `DetailModal.jsx:13` — 댓글 추가는 로컬 state만 → 새로고침 시 소멸 | 🟡 Important |
| **지도 API 연동** | `LocalPage.jsx:22-26` — 완전한 placeholder | 🟡 Important |
| **알림 시스템** | `Header.jsx:96-98` — UI만 존재, 기능 없음 | 🟡 Important |
| **가격 알림** | `appStore.js:89-98` — store에 `addPriceAlert` 정의되어 있으나 UI에서 호출하는 곳 없음 | 🟡 Important |
| **무한 스크롤** | `useInfiniteScroll.js` 훅 존재하나 어디서도 사용되지 않음 | 🟢 Nice-to-have |
| **프로필 페이지** | 미구현 — 로그인 후 프로필 확인/수정 불가 | 🟡 Important |
| **404 페이지** | 미구현 | 🟡 Important |
| **검색 결과 페이지** | Header 검색 시 `/price`로 navigate하며 `state.searchQuery` 전달하나, PricePage에서 이 state를 **수신하지 않음** (`PricePage.jsx`에 `useLocation` 없음) | 🔴 Critical |
| **핫딜 외부 링크** | 각 핫딜에 `url` 필드 존재하나 UI에서 접근 불가 | 🟡 Important |
| **페이지네이션** | 핫딜 20개, 커뮤니티 8개 — 고정 개수, 더보기/페이징 없음 | 🟡 Important |
| **이미지 업로드** | `CommunityPage.jsx:39-45` — FileReader로 미리보기만, 서버 업로드 없음 | 🟡 Important |
| **플러그인 시스템** | `src/plugins/` 디렉토리에 매니저/SDK/런타임 있으나 UI 연결 없음 | 🟢 Nice-to-have |

---

## 3. 코드 품질 평가

### 아키텍처

**등급: B+**

```
src/
├── App.jsx                  # 라우팅 + 전역 레이아웃
├── main.jsx                 # 엔트리포인트
├── pages/                   # 페이지 컴포넌트 (lazy loaded)
│   ├── Home/                # 각 페이지별 디렉토리
│   ├── Price/
│   ├── Hotdeal/
│   ├── Mart/
│   ├── Local/
│   └── Community/
├── components/
│   ├── common/              # 재사용 가능한 UI 프리미티브
│   ├── layout/              # Header, Footer, BottomNav
│   ├── modals/              # 모달 컴포넌트
│   └── features/            # 도메인 특화 컴포넌트
├── services/                # API 클라이언트 레이어
├── stores/                  # Zustand 전역 상태
├── hooks/                   # 커스텀 훅
├── data/                    # Mock 데이터
└── styles/                  # 디자인 토큰 + 전역 CSS
```

**장점:**
- Feature-based 디렉토리 구조가 잘 잡혀있음
- 각 페이지별 `.jsx` + `.module.css` 쌍으로 정리
- 서비스 레이어가 미리 설계되어 있어 API 연결 시 변경 최소화 가능
- `mockData.js:1-8` 주석에 명시: "이 파일만 교체하면 전체 데이터 소스가 바뀜"

**우려:**
- 서비스 레이어가 존재하지만 **실제로 사용되는 곳이 단 하나도 없음** — 설계만 하고 연결 안 됨
- `pages/HomePage.jsx`와 `pages/Home/HomePage.jsx` — 두 벌 존재 (루트 레벨 파일은 사용되지 않는 잔여 파일로 추정)
- 같은 구조가 모든 페이지에 해당 (`CommunityPage.jsx` 등이 `pages/` 루트와 하위 디렉토리에 중복)

### 모듈화

**등급: B**

**장점:**
- CSS Modules 전면 적용 → 스타일 충돌 제로
- `tokens.css` — 디자인 토큰 중앙 관리 (색상, 폰트, 간격, 그림자, 브레이크포인트)
- 공통 컴포넌트 풍부: `Button`, `Badge`, `Card`, `Input`, `Modal`, `Spinner`, `EmptyState`, `Tabs`, `SearchBar`, `Toast`
- 커스텀 훅 분리: `useDebounce`, `useInfiniteScroll`, `useLocalStorage`, `useMediaQuery`, `useToast`

**우려:**
1. **공통 컴포넌트 미활용**
   - `EmptyState.jsx`, `SearchBar.jsx`, `Tabs.jsx`, `Toast.jsx` 등이 만들어져 있지만 페이지에서 사용하지 않음
   - 각 페이지가 자체적으로 빈 상태/탭/검색 UI를 inline으로 구현
   - 예: `MartPage.jsx:12-17`의 탭 UI vs `Tabs.jsx` 공통 컴포넌트 — 후자 미사용

2. **`mockData.js` 거대 파일 (29KB)**
   - 상품, 핫딜, 마트, 주유소, 식당, 레시피, 커뮤니티 데이터 + 유틸 함수가 단일 파일에 혼재
   - `seedData.js`는 실제 크롤러 데이터 변환 로직이지만 어디서도 import 안 됨

3. **Zustand store 단일 파일 비대화**
   - `appStore.js` — 150줄, 20개 이상의 액션이 단일 store에 밀집
   - 도메인별 slice 분리 필요 (auth, search, shopping, price, community, ui)

### 에러 처리

**등급: C−**

1. **API 클라이언트 에러 처리 미흡**
   - `api.js:33-40` — 401 시 `refreshToken()` 후 실패하면 `window.location.href = '/login'` 강제 이동
   - `/login` 라우트가 존재하지 않음 → **무한 새로고침 발생 가능**
   - 다른 HTTP 에러 코드(403, 500 등) 처리 없음 — response를 그대로 반환

2. **서비스 레이어: throw만 하고 catch 없음**
   - `hotdealService.js`, `productService.js`, `authService.js` — 모든 함수가 에러 시 `throw new Error()`
   - 이를 호출하는 코드가 없으므로 현재는 문제 없지만, 연결 시 try-catch 누락 시 크래시

3. **네트워크 에러 UI 부재**
   - 어떤 페이지에도 "데이터 로드 실패" / "네트워크 오류" / "다시 시도" 화면 없음
   - 현재 mock 데이터라 문제 없지만, API 전환 시 즉시 문제됨

4. **`fmt()` 함수 null 안전성**
   - `mockData.js:274-277` — `n == null` 체크는 있지만, `n`이 문자열일 때 `toLocaleString()` 실패
   - `LocalPage.jsx:13`에서 `s` 변수명 shadowing: 매개변수 `s`가 `reduce`의 accumulator지만 외부 CSS module `s`와 같은 이름

---

## 4. 사용자 시나리오 테스트

### 시나리오 1: 첫 방문자가 핫딜을 찾는 흐름

| 단계 | 기대 동작 | 실제 결과 | 판정 |
|------|-----------|-----------|------|
| 1. 홈 진입 | 히어로 + 검색창 | ✅ 잘 보임 | ✅ |
| 2. "삼겹살" 검색 | 자동완성 목록 | ✅ 1개 결과 표시 | ✅ |
| 3. 결과 클릭 | 가격비교 페이지 이동 | ✅ `/price/2` 이동 + 차트 | ✅ |
| 4. 핫딜 탭 클릭 | 핫딜 목록 | ✅ 20개 핫딜 표시 | ✅ |
| 5. 핫딜 카드 클릭 | 상세 보기 + 구매 링크 | ⚠️ 모달은 열리나 **외부 구매 링크 없음** | ⚠️ |
| 6. 뒤로 가기 | 이전 페이지 | ⚠️ 모달 닫힘이 아닌 페이지 이동 (History 미관리) | ⚠️ |

**문제점:**
- 핫딜 모달(`DetailModal.jsx`)에 "원본 글 보기" / "구매하러 가기" 버튼 없음 — 사용자가 실제 거래로 이어질 수 없음
- 검색 시 한글 초성 검색 미지원 (예: "ㅅㄱㅅ"로 삼겹살 검색 불가)

### 시나리오 2: 마트 전단지 세일 확인

| 단계 | 기대 동작 | 실제 결과 | 판정 |
|------|-----------|-----------|------|
| 1. 마트 탭 이동 | 마트 선택 화면 | ✅ 4개 마트 탭 | ✅ |
| 2. 이마트 선택 | 이마트 전단 상품 | ✅ 8개 상품 + 할인율 | ✅ |
| 3. DB 평균 비교 | 할인가 vs 시세 | ✅ "DB 평균 대비 -XXX원" 표시 | ✅ |
| 4. 상품 클릭 → 상세 | 가격비교 페이지 이동 | ❌ **카드 클릭 이벤트 없음** | ❌ |
| 5. 행사 기간 확인 | 남은 기간 표시 | ⚠️ 기간은 표시되나 "D-3" 같은 countdown 없음 | ⚠️ |

**문제점:**
- `MartPage.jsx:21-38` — 마트 상품 카드에 `onClick` 핸들러 없음 → 상품 클릭해도 아무 반응 없음
- 전단지 이미지(`flyerImg`) 데이터는 존재하나 UI에 표시 안 됨
- 장보기 리스트 추가 버튼 없음 — 마트에서 본 세일 품목을 리스트에 추가할 수 없음

### 시나리오 3: 주변 주유소/식당 가격비교

| 단계 | 기대 동작 | 실제 결과 | 판정 |
|------|-----------|-----------|------|
| 1. 동네 탭 이동 | 지도 + 목록 | ⚠️ 지도 자리에 placeholder, 목록은 표시 | ⚠️ |
| 2. 위치 허용 | 현재 위치 기반 데이터 | ❌ **위치 요청 없음**, 강남구 하드코딩 데이터만 | ❌ |
| 3. 주유소 가격 확인 | 정렬된 리스트 | ✅ 가격순 정렬 + 전국 평균 비교 | ✅ |
| 4. 식당 탭 전환 | 카테고리 필터 | ✅ 전체/한식/중식/카페 필터 | ✅ |
| 5. 식당 클릭 → 상세 | 상세 정보 / 지도 | ❌ **클릭 이벤트 없음** | ❌ |

**문제점:**
- `appStore.js:109-114` — `location`, `setNearbyGasStations` 등 상태는 정의되어 있으나 `navigator.geolocation` 호출 코드 없음
- 식당/주유소 항목에 클릭 이벤트 없음 — 상세 정보 확인 불가

### 시나리오 4: 커뮤니티 핫딜 공유

| 단계 | 기대 동작 | 실제 결과 | 판정 |
|------|-----------|-----------|------|
| 1. 커뮤니티 진입 | 게시글 목록 | ✅ 8개 게시글 + 검증 뱃지 | ✅ |
| 2. "글쓰기" 클릭 | 로그인 확인 → 폼 | ✅ 미로그인 시 자동 데모 로그인 + 폼 열기 | ✅ |
| 3. 품목명 입력 | DB 자동 매칭 | ✅ `<datalist>` 기반 자동완성 | ✅ |
| 4. 가격 입력 | 자동 검증 | ✅ 4단계 검증 뱃지 (핫딜/검증/의심/차단) | ✅ |
| 5. 이미지 첨부 | 미리보기 | ✅ FileReader 기반 미리보기 | ✅ |
| 6. 등록 | 게시글 저장 | ❌ **toast만 뜨고 실제 저장 안 됨** | ❌ |
| 7. 게시글 클릭 | 상세 + 댓글 | ✅ 모달에 본문 + 이미지 + 댓글 | ✅ |
| 8. 댓글 작성 | 댓글 등록 | ⚠️ 로컬 state에만 추가, 새로고침 시 소멸 | ⚠️ |

**문제점:**
- 자동 로그인(`CommunityPage.jsx:63-64`)이 사용자 동의 없이 발생 — "로그인 후 글쓰기" 버튼을 눌렀는데 로그인 모달이 아닌 자동 로그인이 됨
- 허위가격 검증 시 `canPost:false`인 경우(`verifyPrice` ratio < 0.20) 제출 버튼 disabled되나, 가격 필드를 비우면 우회 가능

### 시나리오 5: 상품 가격 추이 확인

| 단계 | 기대 동작 | 실제 결과 | 판정 |
|------|-----------|-----------|------|
| 1. 홈에서 양파 카드 클릭 | 가격 비교 페이지 | ✅ `/price/1` 이동 | ✅ |
| 2. 타이밍 뱃지 확인 | 현재 가격 판단 | ✅ "✅ 지금 사도 괜찮아요!" | ✅ |
| 3. 30일 차트 확인 | 가격 추이 | ⚠️ 차트 표시되나 **매번 랜덤 데이터** | ⚠️ |
| 4. 90일로 전환 | 기간 변경 | ✅ 차트 갱신 (단, 30일 데이터와 불일치) | ⚠️ |
| 5. 마트별 비교 확인 | 4개 마트 가격 | ✅ 색상 dot + 평균 대비 차이 | ✅ |
| 6. 속성 변형 선택 | 냉장/냉동/국산/수입 | ✅ 양파: 국산/수입(중국) 선택 가능 | ✅ |
| 7. 관심 등록 | 하트 버튼 | ✅ 클릭 시 favorites에 저장, 홈에 반영 | ✅ |
| 8. 상세 통계 | 할인 빈도 등 | ⚠️ **하드코딩 값** ("22.4%", "월 2.3회" 등) | ⚠️ |

**문제점:**
- `PricePage.jsx:147-153` — 상세 통계 6개 항목이 모두 하드코딩 → 어떤 상품을 봐도 동일 수치
- `product.stats` 객체에 `avgDiscount`, `discFreq` 등이 이미 정의되어 있으나 사용되지 않음
- URL 직접 접근(`/price/999`) 시 존재하지 않는 상품 → "상품을 검색해보세요" 텍스트만 표시 → "상품을 찾을 수 없습니다" + 검색 유도가 더 적절

---

## 5. 개선 제안 (우선순위별)

### 🔴 Critical (즉시 수정)

1. **API 연결 실현**
   - 현재: 모든 데이터가 `mockData.js` 하드코딩
   - 조치: `services/` 레이어가 이미 존재하므로, 각 페이지에서 `useEffect` + 서비스 호출 패턴 적용
   - 예시 (HotdealPage 변경안):
   ```jsx
   // 현재
   import { HOTDEALS } from '../data/mockData';
   
   // 변경
   const [deals, setDeals] = useState([]);
   const [loading, setLoading] = useState(true);
   const [error, setError] = useState(null);
   
   useEffect(() => {
     hotdealService.getDeals({ category: filter, sort })
       .then(setDeals)
       .catch(setError)
       .finally(() => setLoading(false));
   }, [filter, sort]);
   ```

2. **LoginModal React 상태 관리로 전환**
   - `appStore.js`에 추가:
   ```js
   isLoginModalOpen: false,
   openLoginModal: () => set({ isLoginModalOpen: true }),
   closeLoginModal: () => set({ isLoginModalOpen: false }),
   ```
   - `LoginModal.jsx`에서 `document.getElementById` 대신 store 상태 사용

3. **404 라우트 추가**
   - `App.jsx`에 catch-all 라우트 추가:
   ```jsx
   <Route path="*" element={<NotFoundPage />} />
   ```

4. **`index.html` lang 속성 수정**
   ```html
   <html lang="ko">
   ```

5. **Header 검색 → PricePage 연결 수정**
   - `PricePage.jsx`에서 `useLocation().state?.searchQuery` 수신하여 초기 검색 실행

### 🟡 Important (다음 스프린트)

6. **에러 바운더리 추가**
   - React ErrorBoundary 컴포넌트 추가하여 컴포넌트 크래시 시 전체 화이트스크린 방지

7. **로딩/에러/빈 상태 통일**
   - `EmptyState.jsx`, `Spinner.jsx` 공통 컴포넌트 활용
   - 각 페이지에 3가지 상태 패턴 적용: `loading ? <Spinner /> : error ? <ErrorState /> : data.length === 0 ? <EmptyState /> : <Content />`

8. **핫딜 외부 링크 추가**
   - `DetailModal.jsx`에 "원본 글 보기" 버튼 추가:
   ```jsx
   {item.url && (
     <a href={item.url} target="_blank" rel="noopener noreferrer" className={s.externalLink}>
       원본 글 보기 <ExternalLink size={14} />
     </a>
   )}
   ```

9. **마트 상품 카드 클릭 연결**
   - `MartPage.jsx` 카드에 onClick → 해당 상품 가격비교 페이지 이동

10. **Zustand store 분할**
    - `authStore.js`, `searchStore.js`, `shoppingStore.js`, `uiStore.js` 등으로 분리

11. **상세 통계 동적 데이터 사용**
    - `PricePage.jsx:147-153`에서 `product.stats` 객체의 실제 값 사용:
    ```jsx
    <span className={s.statVal}>{product.stats.avgDiscount}%</span>
    ```

12. **알림 벨 기능 구현 또는 제거**
    - 기능 없는 UI 요소는 사용자 혼란 유발 — 구현하거나 v1에서 숨기기

13. **접근성 보강**
    - 홈페이지 검색 입력에 `aria-label="상품 검색"`, `role="combobox"` 추가
    - 자동완성 목록에 `role="listbox"`, 각 항목에 `role="option"` 추가
    - 키보드 ArrowUp/Down 네비게이션 추가 (`SearchBar.jsx`에는 이미 구현되어 있으므로 참조)

### 🟢 Nice-to-have (향후)

14. **무한 스크롤 적용** — `useInfiniteScroll.js` 훅을 핫딜/커뮤니티 페이지에 연결

15. **한글 초성 검색** — "ㅅㄱㅅ" → "삼겹살" 매칭

16. **가격 알림 UI** — `appStore.js`의 `addPriceAlert` 연결하는 UI 추가 ("이 가격 이하로 떨어지면 알려주세요")

17. **PWA 지원** — `manifest.json` + Service Worker로 오프라인/푸시알림

18. **SEO 메타태그** — react-helmet-async로 각 페이지별 title/description

19. **SSR/SSG 검토** — Next.js 마이그레이션 또는 Vite SSR 플러그인

20. **국제화(i18n)** — 현재 한국어 하드코딩, 향후 영어/중국어 지원 시 구조 변경 필요

---

## 6. 경쟁력 분석

### vs 뽐뿌, 클리앙 등 기존 핫딜 사이트

| 비교 항목 | 뽐뿌/클리앙 | 지갑 지키미 | 평가 |
|-----------|-------------|-------------|------|
| 핫딜 수집 | 사용자 직접 등록 (수만 건/일) | 크롤러 자동 수집 (설계는 됨) | ⚠️ 데이터 양에서 열세 |
| 가격 판단 | 사용자 주관적 판단 | **DB 평균 대비 자동 비교** | ✅ 차별화 포인트 |
| 마트 전단 | 없음 | **4대 마트 전단 통합 비교** | ✅ 독자 기능 |
| 커뮤니티 | 수십만 활성 사용자 | 데모 데이터 8개 | ❌ 압도적 열세 |
| 모바일 앱 | 전용 앱 있음 | 웹만 (반응형) | ⚠️ 앱 필요 |

### 차별화 포인트

1. **"지금 사도 될까?" 판단 엔진** — 단순 할인율이 아닌, 시계열 평균 대비 현재가 위치를 판단
   - `PricePage.jsx:36-39` — 4단계 타이밍 뱃지
   - `PricePage.jsx:99-109` — 5단계 가격 등급 바
   - 이것은 뽐뿌/클리앙에 없는 **핵심 차별화**

2. **자동 가격 검증** — 커뮤니티 글쓰기 시 허위가격 자동 탐지
   - `mockData.js:263-271` — ratio 기반 4단계 검증
   - 뽐뿌의 "허위 핫딜" 문제를 구조적으로 해결

3. **장보기 최적화** — 여러 품목을 마트별로 분배하여 최저가 조합 계산
   - `ShoppingOptimizer.jsx:7-49` — 마트별 총합 + 최적 조합 알고리즘
   - 기존 서비스에 없는 실용적 기능

4. **집밥 비용 계산기** — 외식 vs 집밥 실시간 비교
   - `RecipeCalculator.jsx` — 5개 레시피, 재료비 실시간 계산

5. **상품 속성 변형 비교** — 같은 삼겹살도 냉장/냉동/국산/수입으로 세분화
   - `mockData.js:31-53` — 뽐뿌에서는 불가능한 세밀한 비교

### 부족한 점

1. **데이터 없는 플랫폼** — 핵심 경쟁력인 가격 데이터가 전부 mock
2. **네트워크 효과 부재** — 커뮤니티 활성화 전략 미수립
3. **구매 전환 경로 없음** — 핫딜 확인 후 실제 구매 사이트로의 연결 미비
4. **모바일 경험 미검증** — CSS 모듈 내 미디어 쿼리 존재 여부 불확실, BottomNav만으로 부족할 수 있음
5. **SEO 완전 부재** — SPA이므로 검색 엔진 노출 불가, "삼겹살 가격" 검색 시 노출 안 됨
6. **수익 모델 미정의** — 어떻게 monetize 할 것인지 기술적/기획적 고려 없음

---

## 부록: 파일별 이슈 요약

| 파일 | 이슈 | 심각도 |
|------|------|--------|
| `index.html:2` | `lang="en"` → `lang="ko"` | 🔴 |
| `App.jsx` | 404 라우트 없음 | 🔴 |
| `Header.jsx:43-44` | DOM 직접 조작으로 모달 제어 | 🔴 |
| `Header.jsx:96-98` | 알림 버튼 데드 기능 | 🟡 |
| `Header.jsx:102` | 프로필 버튼 = 로그아웃 | 🟡 |
| `Header.jsx:50-51` | 검색 결과 PricePage에서 수신 안 됨 | 🔴 |
| `HomePage.jsx:11` | 인기 검색어 하드코딩 | 🟢 |
| `HomePage.jsx:48-56` | 검색 접근성 (aria, keyboard) 부재 | 🔴 |
| `HomePage.jsx:59-72` | 검색 결과 없음 상태 미처리 | 🟡 |
| `HotdealPage.jsx:40` | 핫딜 외부 URL 접근 불가 | 🟡 |
| `MartPage.jsx:21-38` | 상품 카드 클릭 이벤트 없음 | 🟡 |
| `MartPage.jsx` | 전단지 이미지(`flyerImg`) 미표시 | 🟡 |
| `LocalPage.jsx:22-26` | 지도 placeholder | 🟡 |
| `LocalPage.jsx` | 위치 기반 데이터 미구현 | 🟡 |
| `CommunityPage.jsx:63-64` | 동의 없는 자동 로그인 | 🟡 |
| `CommunityPage.jsx:56` | 게시글 저장 미구현 | 🔴 |
| `PricePage.jsx:147-153` | 상세 통계 하드코딩 | 🟡 |
| `PricePage.jsx:20` | 차트 랜덤 데이터 | 🟡 |
| `LoginModal.jsx:9,12-14` | DOM 조작 + 입력값 무시 | 🔴 |
| `LoginModal.jsx:40-41` | 소셜 로그인 버튼 무기능 | 🟡 |
| `LoginModal.jsx:44-48` | 회원가입 검증 없음 | 🟡 |
| `DetailModal.jsx` | 외부 링크 버튼 없음 | 🟡 |
| `ShareButton.jsx:32-45` | 카카오톡 SDK TODO | 🟢 |
| `ToastContainer.jsx:20` | 에러 타입도 파란색 | 🟡 |
| `Footer.jsx:13-15` | 모든 링크 `href="#"` | 🟡 |
| `BottomNav.jsx:13` | badgeCounts prop 미연결 | 🟢 |
| `api.js:40` | `/login` 라우트 없는데 리다이렉트 | 🔴 |
| `appStore.js:89-98` | priceAlerts 정의만, UI 없음 | 🟡 |
| `appStore.js` | notifications 상태 미정의 | 🟡 |
| `mockData.js:56-68` | 랜덤 기반 가격 히스토리 | 🟡 |
| `useInfiniteScroll.js` | 미사용 | 🟢 |
| `useToast.js` | Zustand 토스트와 중복 | 🟢 |
| 공통 컴포넌트 다수 | 만들어놓고 미사용 | 🟢 |
| `seedData.js` | import 되는 곳 없음 | 🟢 |

---

> **최종 의견:** 지갑 지키미는 "정보 기반 가격 판단"이라는 명확한 차별화 포인트를 가진 유망 제품입니다. 아키텍처와 UI 설계 수준이 프로토타입 치고 높으며, API 서비스 레이어까지 미리 설계해 둔 점은 확장성을 고려한 것입니다. 그러나 현재 상태는 **기능 데모(Functional Demo)**이지 **상용 제품(Production-Ready)**이 아닙니다. 구매 결정 전 최소한 API 연결, 에러 처리, 접근성 3가지가 해결되어야 합니다.
