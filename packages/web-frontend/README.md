# WalletSavior Web Frontend (Phase E3)

마트 4사 데이터 기반 핫딜 비교 웹 프론트엔드. React + TypeScript + Vite.

## 실행 방법

```bash
cd packages/web-frontend

# 의존성 설치
npm install

# 개발 서버 시작 (포트 5173, API 프록시 → 8010)
npm run dev

# 빌드
npm run build

# 테스트
npm test
```

## 환경 / 의존성

| 항목 | 버전 |
|------|------|
| Node.js | 18+ |
| React | 19 |
| Vite | 8 |
| react-router-dom | 6 |
| vitest | 4 |

백엔드(`packages/web-api/backend`)가 포트 8010에서 실행 중이어야 합니다.

## 페이지 구성

| 경로 | 컴포넌트 | 설명 |
|------|----------|------|
| `/` | HomePage | 검색바 + 카테고리 타일 + 오늘의 핫딜 |
| `/c/:slug` | CategoryPage | 카테고리 트리 + 상품 그리드 + 정렬/필터 |
| `/p/:canonical_id` | ProductDetailPage | 마트별 비교 테이블 + 가격 게이지 |

## 컴포넌트

- `SearchBar` — 200ms debounce 자동완성 검색바
- `ProductCard` — HOT_DEAL/SALE/NORMAL/OVERPRICED 배지 + 가격 표시
- `CategoryTree` — 계층 카테고리 트리 내비게이션
- `PriceGauge` — P10/P25/P50/P75 시각화 게이지
- `GradeBadge` — 가격 등급 배지

## 가격 등급 색상 규칙

| 배지 | 색상 | 의미 |
|------|------|------|
| 🔥 핫딜 | 빨강 | 현재가 ≤ P10 (역대 하위 10%) |
| 🏷️ 세일 | 주황 | P10 < 현재가 ≤ P25 |
| 일반가 | 회색 | P25 < 현재가 ≤ P75 |
| ⚠️ 높은가격 | 파랑 | 현재가 > P75 (비싼 편) |
| 데이터 부족 | 회색 | 표본 5건 미만 |

## Vite 프록시 설정

`vite.config.ts`에서 `/api` → `http://127.0.0.1:8010` 으로 프록시하므로,
개발 중에는 CORS 없이 백엔드 API를 호출할 수 있습니다.

## 알려진 한계

- 가격 추이 그래프: Phase D 스냅샷에 PriceObservation이 canonical당 1건이므로 추이 표시 불가 (Phase F에서 누적 후 구현)
- 실시간 가격: 스냅샷 기반 읽기 전용 — 실시간 갱신 미지원
- 회원/게시판/댓글: Phase F 이후
