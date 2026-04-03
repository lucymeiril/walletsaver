# 지갑 지키미 — API 계약서

## 프로젝트 간 데이터 흐름
```
크롤러관리자(8001) --POST /api/ingestions--> DB관리자(8002)
DB관리자(8002) --GET /api/products,prices,categories--> 웹사이트(8000)
웹사이트(8000) --자체 DB--> 커뮤니티/인증
```

## 1. DB 관리자 API (port 8002)

### 상품
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/products | 상품 목록 (source, category, q, page, per_page, sort, order) | ⚠️ 정렬/소스필터 강화 |
| GET | /api/products/{id} | 상품 상세 | ✅ |
| POST | /api/products | 상품 추가 (name, category_id, keywords[]) | ⚠️ 카테고리 자동완성 |
| PUT | /api/products/{id} | 상품 수정 | ✅ |
| DELETE | /api/products/{id} | 상품 삭제 | ✅ |
| POST | /api/products/bulk-delete | 벌크 삭제 (ids[]) | ✅ |
| POST | /api/products/bulk-category | 벌크 카테고리 변경 (ids[], category_id) | ✅ |
| GET | /api/products/{id}/history | 가격 이력 | ⚠️ 차트 데이터 포맷 |
| GET | /api/products/stats | 소스별/카테고리별 통계 | ❌ 신규 |

### 카테고리
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/categories | 전체 트리 구조 | ✅ |
| POST | /api/categories | 카테고리 추가 (id, name, parent_id) | ✅ |
| PUT | /api/categories/{id} | 카테고리 수정 | ✅ |
| DELETE | /api/categories/{id} | 카테고리 삭제 | ✅ |
| PUT | /api/categories/{id}/move | 카테고리 이동 (new_parent_id) | ❌ 신규 |
| GET | /api/categories/{id}/products | 카테고리별 상품 목록 | ❌ 신규 |

### 키워드
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/keywords | 키워드 목록 (q, category_id, page, per_page) | ⚠️ 페이지네이션 |
| POST | /api/keywords | 키워드 추가 (word, synonyms[], category_id) | ⚠️ 중복 처리 |
| PUT | /api/keywords/{id} | 키워드 수정 | ✅ |
| DELETE | /api/keywords/{id} | 키워드 삭제 | ✅ |
| GET | /api/keywords/autocomplete | 자동완성 (q, limit) | ❌ 신규 |

### 가격
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/prices/tiers | 티어 설정 조회 | ✅ |
| POST | /api/prices/tiers | 티어 설정 저장 | ✅ |
| GET | /api/prices/outliers | 이상치 목록 | ✅ |
| GET | /api/prices/history | 가격 데이터 (product_id, source, page) | ✅ |
| GET | /api/prices/stats | 통계 요약 | ✅ |

### 수집 (Ingestion)
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/ingestions | 수집 목록 (status 필터) | ✅ |
| GET | /api/ingestions/{id} | 수집 상세 + 데이터 미리보기 | ✅ |
| POST | /api/ingestions/{id}/db-review | DB 승인/거부 | ✅ |
| POST | /api/ingestions/bulk-approve | 벌크 승인 (ids[]) | ❌ 신규 |
| GET | /api/ingestions/stats | 수집 통계 | ✅ |

### 분석
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/analytics/summary | 전체 요약 | ✅ |
| GET | /api/analytics/price-trends | 가격 추이 (product_id, days) | ✅ |
| GET | /api/analytics/quality-report | 품질 리포트 | ⚠️ 실데이터 |

### 대시보드
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/dashboard/stats | 대시보드 통계 | ⚠️ 신선도 개선 |

---

## 2. 크롤러 관리자 API (port 8001)

### 크롤러
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/crawlers | 크롤러 목록 | ✅ |
| POST | /api/crawlers/{id}/run | 크롤러 실행 | ✅ |
| GET | /api/crawlers/{id}/status | 실행 상태 조회 | ✅ |
| PUT | /api/crawlers/{id}/toggle | 활성/비활성 토글 | ✅ |
| GET | /api/crawlers/{id}/settings | 설정 조회 | ✅ |
| PUT | /api/crawlers/{id}/settings | 설정 변경 | ✅ |
| POST | /api/crawlers/bulk-run | 벌크 실행 (ids[]) | ❌ 신규 |

### 수집 (크롤러→DB 파이프라인)
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/ingestions | 수집 목록 | ✅ |
| POST | /api/ingestions | 수집 데이터 제출 | ✅ |
| GET | /api/ingestions/{id} | 수집 상세 | ✅ |
| POST | /api/ingestions/{id}/crawler-review | 1차 승인/거부 | ✅ |

### 플러그인
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/plugins | 플러그인 목록 | ✅ |
| PUT | /api/plugins/{id}/toggle | 활성/비활성 | ✅ |

### 스케줄
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/schedules | 스케줄 목록 | ✅ |
| POST | /api/schedules | 스케줄 추가 | ✅ |
| PUT | /api/schedules/{name} | 스케줄 수정 | ✅ |
| DELETE | /api/schedules/{name} | 스케줄 삭제 | ✅ |
| PUT | /api/schedules/{name}/toggle | 활성/비활성 | ✅ |
| POST | /api/schedules/{name}/run-now | 즉시 실행 | ❌ 신규 |

### 로그
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/logs | 로그 목록 (crawler, status, date_from, date_to, page) | ⚠️ 날짜필터 |
| GET | /api/logs/export | CSV 내보내기 | ⚠️ 전체필드 |

### 대시보드
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/dashboard/stats | 대시보드 통계 | ✅ |

---

## 3. 웹사이트 API (port 8000)

### 상품/가격
| Method | Path | 설명 | 데이터소스 |
|--------|------|------|----------|
| GET | /api/products/search | 상품 검색 | DB |
| GET | /api/products/trending | 인기 검색어 | DB |
| GET | /api/products/popular | 인기 상품 | DB |
| GET | /api/products/categories | 카테고리 목록 | DB |
| GET | /api/products/{id} | 상품 상세 | DB |
| GET | /api/products/{id}/price-history | 가격 이력 | DB |
| GET | /api/products/{id}/price-compare | 출처별 비교 | DB |

### 핫딜
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/hotdeals | 핫딜 목록 | ✅ |
| GET | /api/hotdeals/sources | 출처 목록 | ✅ |
| GET | /api/hotdeals/{id} | 핫딜 상세 | ✅ |
| POST | /api/hotdeals/{id}/vote | 투표 | ⚠️ DB 저장 |

### 마트
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/marts/{store}/promotions | 마트 프로모션 | ✅ |
| GET | /api/marts/{store}/flyers | 전단지 | ✅ |

### 커뮤니티
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/posts | 게시글 목록 | ✅ |
| POST | /api/posts | 게시글 작성 | ✅ |
| GET/PUT/DELETE | /api/posts/{id} | 게시글 CRUD | ✅ |
| GET/POST | /api/posts/{id}/comments | 댓글 | ✅ |
| POST | /api/posts/{id}/vote | 투표 | ✅ |

### 지역 검색
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/local/naver-search | 네이버 검색 | ✅ |
| GET | /api/local/area-explore | 지역 탐색 | ✅ |
| GET | /api/local/subcategory-search | 서브카테고리 | ✅ |
| GET | /api/local/geocode | 지오코딩 | ✅ |

### 인증
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| POST | /api/auth/register | 회원가입 | ⚠️ 메모리저장 |
| POST | /api/auth/login | 로그인 | ⚠️ 메모리저장 |
| POST | /api/auth/refresh | 토큰갱신 | ✅ |

### 검색
| Method | Path | 설명 | 상태 |
|--------|------|------|------|
| GET | /api/search | 통합 검색 | ✅ |
| GET | /api/search/autocomplete | 자동완성 | ✅ |

---

## 표준 응답 형식

### 성공
```json
{ "data": [...], "total": 100, "page": 1, "per_page": 20 }
```

### 에러
```json
{ "error": "에러 메시지", "code": "ERROR_CODE", "detail": "상세" }
```
