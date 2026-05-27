# Round V mart scope report

## 카테고리 스코프

| 마트 | 유지 | 제외 |
|---|---|---|
| 이마트 | 과일, 채소, 정육, 수산, 유제품, 생수, 간편식 검색/카테고리만 | 행사/할인/특가/1+1/반값/세일 같은 전역 검색어로 비식품 유입되는 경로 |
| 홈플러스 | categoryId 1~18, 20, 22, 23: 과일/쌀/채소/견과/수산/정육/델리/유제품/냉장냉동/반찬/커피/음료/과자/베이커리/라면/양념/세탁청소욕실/건강식품/유아동/주방용품 | 주류매직픽업, 제지/위생/뷰티(뷰티 혼재), 반려동물, 리빙/인테리어, 패션, 문구/취미, 가전/디지털, 자동차/레저 |
| 롯데마트 | 과일, 채소, 정육, 계란, 생수, 유제품, 간편식, 라면, 과자 검색/카테고리만 | 헤어/바디/뷰티, 홈인테리어/침구, 패션잡화, 스포츠/자동차, 문구/사무, 완구/취미, 전자게임, 가전/디지털 등 비식품 |
| 코스트코 | cos_10 식품, cos_12 건강/영양제 + 식품/생필품 키워드 | 디지털/TV/컴퓨터, 가구/침구/인테리어, 스포츠/헬스/캠핑, 의류/가방/잡화, 보석/시계, 공구/자동차, 문구/사무, 대형/생활가전, 기프트카드 등 |

## 롯데마트 중복/과잉 방지

- 기본 경로를 범위 없는 promotions cursor 대신 식품/생필품 검색 요청으로 제한.
- cursor 경로가 쓰여도 카테고리당 50페이지 cap, 전체 unique 5,000건 cap 적용.
- product id/source key/detail_url 우선, 없으면 `(name, store)` 로 dedup.
- 페이지 duplicate ratio > 30% 또는 신규 ratio < 5%면 다음 소스로 종료.

## 코스트코 fetch 안정화

- 식품 root(cos_10/cos_12)만 남겨 FurnitureBeddingHome/Bedding 접근을 차단.
- browser JSON parse 실패(`Extra data` 등)는 2회까지 긴 timeout으로 재시도 후 빈 HTML로 fail-fast.

## ingestion

- `_store_to_ingestion` payload를 500건 chunk로 순차 POST.
- chunk 사이 1초 sleep.
- chunk별 실패는 DLQ로 기록하고 다음 chunk는 계속 진행.

## 검증

- pytest: `py -3 -m pytest tests/test_lottemart_crawler.py tests/test_homeplus_crawler.py tests/test_emart_crawler.py tests/test_coupang_crawler.py -q` → 67 passed.
- live food probes(순차, 3초 sleep 재시도): emart 생수 200/764119 bytes/112 markers, homeplus 과일 200/40873 bytes/20 markers, lottemart 생수 200/1652532 bytes/101 markers, costco cos_10 200/2099460 bytes/1 marker.
