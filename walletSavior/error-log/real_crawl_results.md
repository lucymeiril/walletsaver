# 실제 크롤링 테스트 결과 (Real Crawl Test Results)

**테스트 일시**: 2026-03-31 17:58 ~ 18:02  
**테스트 환경**: Windows, Python 3.13, requests + BeautifulSoup4

---

## 테스트 대상

| 크롤러 | 유형 | 대상 사이트 | 결과 |
|--------|------|------------|------|
| 뽐뿌 (PpomppuCrawler) | 핫딜 (HotdealPost) | ppomppu.co.kr | ✅ 성공 (26건) |
| 이마트 (EmartCrawler) | 마트 (DiscountItem) | emart.ssg.com | ✅ 성공 (44건) |

---

## 1. 뽐뿌 핫딜 크롤러 (ppomppu)

### 수정 사항

1. **인코딩 수정** (`crawler.py:70`):
   - 변경 전: `response.encoding = "utf-8"` → 한글 깨짐
   - 변경 후: `response.encoding = "euc-kr"` → 정상 한글 출력
   - 원인: 뽐뿌는 `Content-Type: text/html; charset=euc-kr` 사용

2. **파싱 셀렉터 업데이트** (`_parse_row()` 메서드):
   - 변경 전: `font.list_title` 셀렉터 (존재하지 않음)
   - 변경 후: `a.baseList-title` + `em.baseList-head` (카테고리)
   - 원인: 2026년 기준 뽐뿌 HTML 구조 변경

3. **가격 추출 로직 수정** (`_extract_price()` 메서드):
   - 변경 전: "무료" 체크가 가격 패턴보다 먼저 실행 → "(17,900원/무료)"에서 0원 반환
   - 변경 후: 가격 패턴 먼저 검색 → 숫자 가격 없을 때만 "무료" → 0원
   - 원인: "무료"가 "무료배송"을 의미하는 경우가 많음

### 수집 데이터 샘플

```
[1] [지마켓]탑텐키즈 남아 여아 셋업 티셔츠 등 (10,430원/3만무배)
    가격: 10,430원  |  카테고리: 지마켓

[2] [카카오]참도깨비 의정부식 1960 부대찌개 700g 4봉 (17,900원/무료)
    가격: 17,900원  |  카테고리: 카카오

[3] [11번가]쿨매트 냉감패드 슈퍼싱글 1+1 (49,900원/무료)
    가격: 49,900원  |  카테고리: 11번가

[4] [오늘의집]춘천 왕 닭갈비 750g*2팩 (11,880원/무료배송)
    가격: 11,880원  |  카테고리: 오늘의집

[5] [11번가]블랙라벨 오렌지 M 중과 10과 (9,190원/무료)
    가격: 9,190원  |  카테고리: 11번가
```

### 스키마 검증 (HotdealPost)

| 필드 | 타입 | 상태 |
|------|------|------|
| title | str | ✅ 필수, non-empty |
| url | str | ✅ 유효한 URL |
| source_community | str | ✅ "뽐뿌" |
| price | int/None | ✅ 대부분 추출됨 |
| category | str | ✅ 플랫폼명 (지마켓, 카카오 등) |
| crawled_at | datetime | ✅ |

---

## 2. 이마트 크롤러 (emart)

### 수정 사항

1. **크롤링 전략 전면 개편** (`crawler.py` 전체):
   - 변경 전: `eventMain.ssg` 이벤트 페이지에서 HTML 파싱 → 상품 카드 0개
   - 변경 후: SSG 검색 API + `__NEXT_DATA__` JSON 추출
   - 원인: SSG가 Next.js SPA로 전환, HTML에 상품 데이터가 직접 없음

2. **`__NEXT_DATA__` 파서 추가** (`_extract_next_data_items()`, `_next_data_to_discount_item()`):
   - SSG 페이지의 `<script id="__NEXT_DATA__">` 에서 JSON 추출
   - 상품 위치: `props.pageProps.dehydratedState.queries[N].state.data.areaList[M].dataList`
   - 필드 매핑: `itemName`→name, `finalPrice`→sale_price, `strikeOutPrice`→original_price, `itemImgUrl`→image_url, `itemUrl`→detail_url

3. **검색 API 사용** (`crawl()` 메서드):
   - 검색어 `["행사", "할인", "특가"]`로 SSG 검색 페이지 요청
   - 30건 이상 수집되면 조기 종료 (사이트 부하 방지)

4. **가격 파서 추가** (`_parse_price_str()`):
   - "29,780원" → 29780, "29780" → 29780

### 수집 데이터 샘플

```
[1] 농장직송 성주 꿀 참외 못난이 혼합과 2kg
    매장: 이마트  |  할인가: 15,900원

[2] 파스타소스(미트) 600g
    매장: 이마트  |  할인가: 7,480원

[3] 에콰도르산 달콤 바나나 1kg
    매장: 이마트  |  할인가: 3,480원

[4] [더느림+] 무항생제 등갈비 (100g)
    매장: 이마트  |  할인가: 2,506원

[5] 아임리얼 100 레몬_730ml
    매장: 이마트  |  할인가: 3,490원
```

### 스키마 검증 (DiscountItem)

| 필드 | 타입 | 상태 |
|------|------|------|
| name | str | ✅ 필수, non-empty |
| store | str | ✅ "이마트" |
| sale_price | int | ✅ > 0 |
| original_price | int/None | ⚠️ 일부 None (검색 결과에 원가 미포함) |
| discount_percent | float/None | ⚠️ 원가 없으면 계산 불가 |
| unit | str | ✅ (sellUnitCapacity) |
| category | str | ✅ (brandName 매핑) |
| image_url | str | ✅ SSG CDN URL |
| detail_url | str | ✅ itemView URL |
| event_name | str | ✅ "이마트 할인" |

---

## 3. 파이프라인 통합 테스트

### 검증→변환 파이프라인

| 단계 | 뽐뿌 | 이마트 |
|------|-------|--------|
| normalize_prices | ✅ 통과 | ✅ 통과 |
| enrich_with_category | ✅ 적용 (바나나→과일류) | ✅ 적용 |
| to_hotdeal_prices / to_discount_history | ✅ 5개 레코드 | ✅ 5개 레코드 |

### DB-Admin 연결 테스트

- **서버 상태**: 포트 8002에서 실행 중 (`/health` → 200 OK)
- **Ingestion API**: 404 (기존 서버 인스턴스에서 ingestion 라우트 미등록)
- **원인**: 서버 재시작 필요 (코드에는 `/api/ingestions` 라우트 존재)

---

## 4. 알려진 이슈

1. **뽐뿌 가격 추출률**: 일부 게시글에서 가격이 "원" 단위 없이 표시되어 None 반환
   - 예: "크래미(6,500/네멤무배)" → "원" 없어서 미추출
   - 개선안: 괄호 안 숫자를 가격으로 추정하는 fallback 패턴 추가

2. **이마트 원가 누락**: SSG 검색 결과에서 `strikeOutPrice`가 항상 제공되지 않음
   - 할인율 계산이 불가능한 경우 있음
   - 개선안: 상품 상세 페이지에서 원가 추가 크롤링

3. **뽐뿌 간헐적 0건**: `__pycache__` 오래된 캐시로 인코딩 변경이 반영되지 않는 경우
   - 해결: `__pycache__` 삭제 후 재실행하면 정상 동작

---

## 5. 변경된 파일

| 파일 | 변경 내용 |
|------|-----------|
| `crawlers/hotdeals/ppomppu/crawler.py` | 인코딩 euc-kr, 셀렉터 업데이트, 가격 추출 로직 수정 |
| `crawlers/marts/emart/crawler.py` | __NEXT_DATA__ 기반 전면 개편, 검색 API 사용 |
| `test_real_crawl.py` | 실제 크롤링 테스트 스크립트 (신규) |
