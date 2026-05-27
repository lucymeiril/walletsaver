# t-emart-legacy-restore — 보고서

## 결론 (요약)
- **이마트 옛 검증된 requests 기반 크롤러 복원 완료, 라이브 7.5초/44~48건 추출 SUCCESS.**
- Round R/S 의 Playwright + Semaphore(3) 동시성 코드는 백업(`crawler.round_s.py.bak`) 후 폐기.
- 라이브 endpoint: `https://emart.ssg.com/search.ssg?target=all&query={...}&page={n}` — `__NEXT_DATA__` JSON 임베드, 한 페이지 40~80건.

## 채택 옛 커밋
- `ea02467` (extracted into `devlog/round-T/legacy-emart-{crawler,entrypoints}.py.txt`).
- 핵심: requests-only, `__NEXT_DATA__` 파서, `SLEEP_BETWEEN_LIVE_GETS=3.0`.

## 라이브 probe 표
| URL | status | len | markers |
| --- | --- | --- | --- |
| `https://emart.ssg.com/` | 200 | ~265KB | 홈, 워밍업용 |
| `https://emart.ssg.com/search.ssg?target=all&query=행사&page=1` | 200 | 1.36~1.39MB | `__NEXT_DATA__` 1개, `itemView.ssg` 80개, `itemId`/`siteNo`/`finalPrice`/`priceInfo.unitPriceDescription` 정상 |

## 코드 변경
- `packages/crawler-admin/backend/crawlers/marts/emart/crawler.py` 전면 교체 (옛 코드 복원 + 아래 패치)
- 백업: 같은 폴더 `crawler.round_s.py.bak`

### 패치 1 — `_retry_request` last_exc/last_resp 버그 수정
- Round S/R 양쪽에 있던 `raise last_exc` (last_exc=None) → `TypeError: exceptions must derive from BaseException` 크래시 제거.
- 429 시 백오프 `5.0 + 2^attempt + jitter(1~3s)`로 강화. 동시성 추가 절대 금지.

### 패치 2 — 세션 워밍업
- `requests.Session()` 재사용, `BASE_URL` 한 번 GET + 3초 대기 후 본 호출. 봇 검출 완화.
- 헤더에 `User-Agent`(Chrome 120) / `Accept-Language: ko-KR,ko;q=0.9` / `Referer` 명시. 헤더 없이 호출 시 즉시 429 발생함을 라이브로 확인.

### 패치 3 — `AntiDetect(delay_min=2.5, delay_max=5.0)`
- 옛 1.0~3.0 → 2.5~5.0 으로 상향. rate limit 대응은 sleep ↑, 동시성 금지 룰.

### 패치 4 — R 필드 머지 (`_next_data_to_discount_item`)
attributes 에 부착:
- `mart="이마트"` (source 자동 채움)
- `mart_native_code` = `itemId` (SSG 영구 식별자)
- `site_no` = `siteNo` (셀러 식별용)
- `external_seller` = `siteNo not in {6001,7009,1000,2300}` (자사 화이트리스트 추정; 후속 라이브 분석으로 조정)
- `promo_label` = itemName의 `\d+\+\d+` 또는 `itemFeatureList`의 `1+1`/`반값`/`특가` 마커
- `unit_price_display` = `priceInfo.unitPriceDescription` (예: "100g당 1,100원" — 사이트 노출 그대로)

## 라이브 검증 출력
```
[이마트] 크롤링 시작
[이마트] __NEXT_DATA__ 상품 44개 발견
[이마트] 검색 '행사' p1: 원천 후보 44개, 44개 신규 (44개 중)
[이마트] 크롤링 완료: 44개, 7.79초
STATUS: CrawlStatus.SUCCESS
ITEMS: 44
 - 태국산 무지개 망고 1.8kg (5~8입) 팩 | 19800 | 1.8kg | https://emart.ssg.com/item/itemView.ssg?itemId=1000648645570&siteNo=7009
 - 성주 고당도 꿀 참외 2kg (6~8입) 봉 | 13800 | 2kg | itemId=1000796033832&siteNo=7009
 - [농할 20%쿠폰 상세 다운] 김제 햇 감자 1.5kg 박스 | 7984 | 1.5kg | itemId=1000024820453&siteNo=6001
 - 프링글스 양파맛110g | 3330 | 110g | itemId=1000641966988&siteNo=6001
 - 신상 농심 신라면로제 큰사발 108g | 1460 | 108g | itemId=1000823771164&siteNo=6001
```

## DB SELECT — 미실시 (후속)
db-admin ingestion 경로 호출은 fleet 결과 통합 시 한꺼번에 진행 예정. 본 단계 책임 범위는 라이브 추출 + DiscountItem 직렬화까지로 한정.

## 재현 명령어
```powershell
cd E:\pdf\capston01
py -3 devlog\round-T\verify_emart_legacy.py
```

## 잔여 cross-cut
- `unit_price_display` / `external_seller` / `promo_label` 등 R 필드를 **DiscountItem 정식 필드 또는 attributes 보존**으로 받는 db-admin ingestion 검증 필요 (이번 라운드 내 후속).
- `siteNo` 자사 화이트리스트는 라이브 N페이지 수집 후 다수결로 결정 필요. 현재 추정값 사용.
- 검색어를 1개로 빠른 검증만 했음. 풀 SEARCH_QUERIES + CATEGORY_QUERIES + MAX_PAGES=3 으로 돌리면 200+건 예상 (6 검색어 × ~50 = 300건). 처리 시간 ~3~5분.
