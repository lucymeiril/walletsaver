# RD8 E0 — 마트 4사 라이브 크롤 결과 보고서

**실행일**: 2026-05-26  
**Export 폴더**: `artifacts/exports/raw-batch/rd8-live-20260526/`

---

## 1. 크롤 결과 요약

| 마트 | 상태 | 데이터 출처 | 수집 건수 | distinct_name | 캡 의심 | 전략 | 소요시간 |
|------|------|------------|---------|-------------|---------|------|--------|
| **코스트코** | ✅ success | 🟢 라이브 | 880건 | 878 | - | occ_rest_api | 152초 |
| **이마트** | ❌ failed_empty | 🔴 fixture | 200건 | 20 | ⚠ | requests (SSG 429) | 15초 |
| **홈플러스** | ✅ success | 🟢 라이브 | 886건 | 877 | - | playwright (mfront HTTP) | 209초 |
| **롯데마트** | ✅ success | 🟢 라이브 | 314건 | 293 | - | playwright_scroll | 78초 |

**라이브 실성공 3사**: 코스트코 + 홈플러스 + 롯데마트 = **2,080건**  
**전체 (emart fixture 포함)**: 2,280건

---

## 2. 내보낸 파일 목록

| 파일 | 크기 | 비고 |
|------|------|------|
| `costco.jsonl` | 2,101 KB | 라이브 880행 |
| `emart.jsonl` | 145 KB | fixture 200행 (`_fallback_fixture: true`) |
| `homeplus.jsonl` | 1,701 KB | 라이브 886행 |
| `lottemart.jsonl` | 679 KB | 라이브 314행 |
| `stats.json` | 2 KB | 마트별 통계 |

---

## 3. plugin.yaml 캡 변경 전후 비교

| 마트 | 변경 항목 | 변경 전 | 변경 후 |
|------|---------|--------|--------|
| 이마트 | `max_pages` | 3 | 8 |
| 이마트 | `max_items` | (미설정) | null |
| 홈플러스 | `max_pages` | 1 | 8 |
| 홈플러스 | `max_items` | 653 | null |
| 롯데마트 | `max_pages` | 2 | 8 |
| 롯데마트 | `max_items` | 300 | null |

### 코드 캡 변경 (crawler.py)

| 파일 | 변수 | 변경 전 | 변경 후 |
|------|------|--------|--------|
| `emart/crawler.py` | `MAX_PAGES` | 3 | 8 |
| `homeplus/crawler.py` | `MAX_ITEMS` | 300 | None |
| `lottemart/crawler.py` | `MAX_ITEMS` | 300 | None |
| `lottemart/crawler.py` | `MAX_PAGES` | 2 | 8 |
| `lottemart/crawler.py` | `PLAYWRIGHT_FALLBACK_QUERY_CAP` | 3 | 10 |

---

## 4. 마트별 상세

### 코스트코 (880건, ✅ 라이브)
- SAP Commerce Cloud OCC REST API 사용
- 카테고리: SpecialPriceOffers(567) + OnlineDeals(313) = 880건, 중복 제거 후 878 distinct
- PAGE_SLEEP_SECONDS=10 준수 (총 152초)
- 중복 2건: SpecialPriceOffers/OnlineDeals 간 미세 overlap

### 이마트 (200건, ❌ fixture)
- **SSG(신세계 CDN) IP 차단**: 첫 번째 크롤 실행(~840건 수집 성공)에서 asyncio 타임아웃 취소로 데이터 유실
- 이후 모든 요청에 HTTP 429(Rate Limited) — 지수 백오프 재시도 후 "exceptions must derive from BaseException"
- 실제 데이터를 수집했으나 asyncio.wait_for 취소 시 코루틴 내 수집 버퍼 소실
- **권장 조치**: 1–2시간 대기 후 재시도 or 별도 IP/프록시 사용
- 이 라운드: 합성 fixture 200행 대체 (`_fallback_fixture: true` 마킹됨)

### 홈플러스 (886건, ✅ 라이브)
- mfront.homeplus.co.kr HTTP API — Playwright 없이 순수 HTTP 접근 가능
- 24개 검색 쿼리 × 최대 50건 = 총 886건, distinct_name=877
- 1회 타임아웃 실패(120초) → 스크립트 타임아웃을 300초로 상향 후 성공(209초)

### 롯데마트 (314건, ✅ 라이브)
- 초기 HTTP 검색에서 AWS WAF HTTP 202 → Playwright headless 스크롤 escalation
- XHR 인터셉트: 11단계 × 24건 = 264건 + DOM 24건 + HTTP 50건(할인/특가) = 314건
- distinct_name=293 (동일 상품 카테고리 간 중복 21건)

---

## 5. 적대적 자기검열 (솔직한 한계 기록)

1. **이마트 실패 원인은 내부 실수**: 첫 번째 크롤 실행에서 `asyncio.wait_for(timeout=300s)` 내에 ~840건 실제 수집에 성공했으나, 타임아웃 취소 후 fixture fallback 코드가 실행되어 진짜 데이터를 버리고 합성 데이터 200행을 내보냈다. SSG IP-block은 그 이후 발생. 결과적으로 이 라운드 이마트는 "수집 성공했으나 저장 실패 → fixture로 대체"가 정확한 서술.

2. **홈플러스 캡 의심 오판 가능성**: 886건은 100의 배수가 아니므로 캡 의심이 없지만, 각 쿼리는 50건 고정 반환이다. API가 최대 50건/쿼리로 자체 제한하는 것이며, 이 쿼리 수집 구조상 실제 할인상품이 더 많을 수 있다. distinct_name=877/886 = 99.0% 유일성으로 실 데이터임은 확인됨.

3. **롯데마트 314건은 프로모션 페이지 1개 출처**: `lottemartzetta.com/promotions` 페이지 스크롤로만 수집하여 매장 카탈로그 전체 대비 매우 일부분이다. WAF 제한으로 일반 검색 페이지 접근이 차단되어 promotions SPA fallback을 사용한 것이며, 이는 의도적 설계가 아니라 WAF 우회 결과다.

---

## 6. E1 검증 준비

RD8 E1 (`full-chain validation`) 입력 파일:

```
artifacts/exports/raw-batch/rd8-live-20260526/
  ├── costco.jsonl      (880행, 라이브)
  ├── emart.jsonl       (200행, fixture — _fallback_fixture:true)
  ├── homeplus.jsonl    (886행, 라이브)
  ├── lottemart.jsonl   (314행, 라이브)
  └── stats.json
```

E1 주의사항:
- `emart.jsonl`: `_fallback_fixture: true` 플래그 있는 행은 파이프라인 dedup/enrichment 검증 시 제외 권장
- `source_record_key` 패턴: fixture는 `{mart}-fxt-{5digit}`, 라이브는 실 식별자
- `collected_at`: fixture 행도 export 시각으로 재기록됨 (필드 신뢰 불가)
