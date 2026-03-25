# 개발일지 #1 — React 마이그레이션 시작

**날짜**: 2026-03-25  
**작업자**: AI + 사용자  
**소요 시간**: ~2시간

---

## 배경

vanilla HTML/CSS/JS로 만든 프론트 프로토타입이 완성된 상태. 6개 페이지(홈, 물가비교, 핫딜, 마트, 동네물가, 커뮤니티) + 6개 모달 + 검색 자동완성 + 가격 차트까지 동작한다.

하지만 이건 프로토타입이고, 실제 서비스로 발전시키려면:
- 컴포넌트 재사용이 안 됨 (DOM 직접 조작)
- 상태 관리가 없음 (전역 변수로 대충 관리)
- 라우팅이 없음 (data-tab으로 show/hide)
- 이미지 최적화가 없음 (핫딜은 사진이 많음)
- 테스트가 안 됨 (UI 단위 테스트 불가)

## 오늘 한 일

### 1. 기술 스택 선정 + 근거 문서화

`proj/TECH_DECISIONS.md`에 각 기술 선택의 WHY를 정리했다. 핵심:

- **Vite**: CRA는 사실상 죽었고, Vite는 빌드 10배 빠름 + HMR 즉시
- **React 18**: 시장 점유율 1위, 생태계 최대, 취업에 직결
- **Zustand**: Redux는 boilerplate 지옥. 우리는 큰 상태 없고, Zustand 10줄로 충분
- **CSS Modules**: DEV_PHILOSOPHY의 "컴포넌트별 CSS 격리" 원칙에 부합
- **Recharts**: Canvas 직접 그리던 차트를 React 컴포넌트로 교체
- **이미지 처리**: React lazy loading + IntersectionObserver + 썸네일 전략

### 2. Vite + React 프로젝트 초기화

`frontend/` 디렉토리에 Vite React 프로젝트 생성.

### 3. 디자인 토큰 이식

vanilla CSS의 `:root` 변수 → `tokens.css`로 이식. 다크 글라스모피즘 테마 유지.

### 4. 더미 데이터 이식

`data.js` → `mockData.js`로 ES Module 형태로 변환. 나중에 API 호출로 교체할 때 이 파일만 바꾸면 됨.

## 다음 할 일

- 공통 컴포넌트 제작 (Header, Footer, Button, Badge, Toast)
- 홈 페이지 + 검색 자동완성
- 물가비교 페이지 (타이밍뱃지 + 차트)

## 겪은 문제

- 없음 (첫 세션이라 세팅 위주)

## 메모

- 핫딜 특성상 이미지를 서버에서 자주, 많이 받아와야 함
- 이미지 lazy loading + 썸네일 + WebP 변환 전략 필수
- 비동기 이미지 로딩 중 Skeleton UI로 UX 유지
