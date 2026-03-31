# API 계약서 — 프로젝트 간 통신 규격

## 개요

WalletSavior는 3개의 독립 프로젝트로 구성되며, 각 프로젝트는 REST API로만 통신합니다.

| 프로젝트 | 기본 포트 | 역할 |
|----------|----------|------|
| Website Backend | 8000 | 사용자향 API |
| Crawler-Admin Backend | 8001 | 크롤러 관리 API |
| DB-Admin Backend | 8002 | 데이터 관리 API |

## 통신 흐름

```
[Website BE :8000] ←──API──→ [DB-Admin BE :8002]
       ↑                           ↑
       │ API                       │ API
       ↓                           ↓
[Crawler-Admin BE :8001] ──API──→ [DB-Admin BE :8002]
```

## 인증

- 프로젝트 간 통신: 내부 API 키 (환경변수 `INTERNAL_API_KEY`)
- 사용자 → Website: JWT Bearer 토큰
- 관리자 → Admin 패널: JWT Bearer 토큰 + 관리자 권한

## 공통 응답 형식

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 100
  }
}
```

## 에러 코드 체계

| 코드 범위 | 프로젝트 | 설명 |
|-----------|----------|------|
| 1000-1999 | Website | 사용자 API 에러 |
| 2000-2999 | Crawler | 크롤러 관리 에러 |
| 3000-3999 | DB-Admin | 데이터 관리 에러 |

### 공통 에러 코드
- 1001: 인증 실패
- 1002: 권한 부족
- 1003: 리소스 없음
- 1004: 유효성 검증 실패
- 1005: 내부 서버 에러

---

## DB-Admin API (포트 8002)

### 상품 (Products)

#### GET /api/products
상품 목록 조회 (페이지네이션, 검색, 필터)

**Query Parameters:**
- `q` (string): 검색어
- `category` (string): 카테고리 ID
- `page` (int, default: 1)
- `per_page` (int, default: 20)

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": "prod_001",
      "name": "삼겹살 (냉장, 국내산)",
      "category": "meat.pork.belly",
      "unit": "100g",
      "baseline_price": 2500,
      "current_avg": 2300,
      "price_tier": "good",
      "updated_at": "2026-03-30T12:00:00Z"
    }
  ],
  "meta": { "page": 1, "per_page": 20, "total": 1234 }
}
```

#### GET /api/products/{id}/prices
상품 가격 이력 조회

**Query Parameters:**
- `days` (int, default: 30): 조회 기간
- `source` (string): 출처 필터 (mart, hotdeal, baseline)

#### POST /api/products
상품 등록 (관리자)

#### PUT /api/products/{id}
상품 수정 (관리자)

---

### 가격 (Prices)

#### POST /api/prices/bulk
대량 가격 데이터 저장 (크롤러→DB)

**Request Body:**
```json
{
  "source": "crawler-emart",
  "crawled_at": "2026-03-30T12:00:00Z",
  "items": [
    {
      "product_id": "prod_001",
      "price": 1990,
      "original_price": 2500,
      "discount_rate": 20.4,
      "source_url": "https://emart.com/...",
      "valid_from": "2026-03-30",
      "valid_to": "2026-04-05"
    }
  ]
}
```

#### GET /api/prices/statistics
가격 통계 조회

---

### 카테고리 (Categories)

#### GET /api/categories
카테고리 트리 조회

#### POST /api/categories
카테고리 추가 (관리자)

#### PUT /api/categories/{id}
카테고리 수정 (관리자)

---

### 키워드 (Keywords)

#### GET /api/keywords/autocomplete
자동완성 키워드 조회

**Query Parameters:**
- `q` (string): 입력 텍스트
- `limit` (int, default: 10)

#### POST /api/keywords
키워드 추가 (관리자)

---

## Crawler-Admin API (포트 8001)

### 크롤러 (Crawlers)

#### GET /api/crawlers
크롤러 목록 및 상태

#### GET /api/crawlers/{id}/status
특정 크롤러 상태 조회

#### POST /api/crawlers/{id}/run
크롤러 수동 실행

#### PUT /api/crawlers/{id}/config
크롤러 설정 변경

---

### 스케줄 (Schedule)

#### GET /api/schedules
스케줄 목록

#### POST /api/schedules
스케줄 추가

#### PUT /api/schedules/{id}
스케줄 수정

#### DELETE /api/schedules/{id}
스케줄 삭제

---

### 로그 (Logs)

#### GET /api/logs
크롤 로그 조회 (페이지네이션, 필터)

#### GET /api/logs/{crawl_id}
특정 크롤 세션 로그

---

## Website API (포트 8000)

### 검색 (Search)

#### GET /api/search
통합 검색

**Query Parameters:**
- `q` (string): 검색어
- `type` (string): 결과 유형 (product, hotdeal, mart, post)
- `sort` (string): 정렬 (price_asc, price_desc, discount, popular, recent)
- `page`, `per_page`

#### GET /api/search/autocomplete
자동완성 (내부적으로 DB-Admin의 /api/keywords/autocomplete 호출)

---

### 핫딜 (Hotdeals)

#### GET /api/hotdeals
핫딜 피드

**Query Parameters:**
- `category` (string)
- `source` (string): 출처 사이트
- `sort` (string): price_asc, discount, popular, recent
- `min_price`, `max_price`
- `page`, `per_page`

---

### 마트 (Marts)

#### GET /api/marts
마트 목록

#### GET /api/marts/{name}/promotions
마트별 프로모션/세일

---

### 주유소 (Gas)

#### GET /api/gas/nearby
주변 주유소 가격

**Query Parameters:**
- `lat` (float): 위도
- `lng` (float): 경도
- `radius` (int, default: 5000): 반경 (미터)
- `fuel_type` (string): gasoline, diesel, lpg
- `sort` (string): price_asc, distance

---

### 식당 (Restaurants)

#### GET /api/restaurants/nearby
주변 식당 정보

#### GET /api/recipes/compare
레시피 가격 비교 (직접 해먹기 vs 배달 vs 외식)

---

### 커뮤니티 (Community)

#### GET /api/posts
게시글 목록

#### POST /api/posts
게시글 작성 (인증 필요)

#### GET /api/posts/{id}
게시글 상세

#### POST /api/posts/{id}/comments
댓글 작성 (인증 필요)

#### POST /api/posts/{id}/vote
핫딜 여부 투표 (인증 필요)

---

### 인증 (Auth)

#### POST /api/auth/register
회원가입 (이메일/비밀번호)

#### POST /api/auth/login
로그인

#### POST /api/auth/refresh
토큰 갱신

#### GET /api/auth/oauth/{provider}
OAuth 로그인 (google, kakao, naver)

#### GET /api/auth/oauth/{provider}/callback
OAuth 콜백
