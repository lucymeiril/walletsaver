# RD8 결함 카탈로그 (1차)

## 1. products.source_type 분포 (현 스키마)
- mart_crawl: 800
→ 마트별 분리가 안 됨. products 테이블에 mart code 컬럼 부재.

## 2. products name 중복 Top 10
- CJ 다시다 쇠고기: 40건
- CJ 햇반: 40건
- 농심 신라면: 40건
- 농심 오징어 땅콩: 40건
- 동서식품 맥심 모카골드: 40건
- 동원 참치 라이트: 40건
- 롯데 초코파이: 40건
- 롯데칠성 칠성사이다: 40건
- 매일유업 바리스타룰스 라떼: 40건
- 브랜드없음 골드키위 EA: 40건
→ products total=800, distinct names=20, dup_rows(name>1)=800

## 3. 같은 name이 같은 mart 안에서도 중복?
→ products.source_type가 mart_crawl 단일이라 mart 분리 불가. raw에서 확인:
- costco :: CJ 다시다 쇠고기 300g: 10건
- costco :: CJ 햇반 210g: 10건
- costco :: [1+1] 롯데 초코파이 12개입: 10건
- costco :: [농할할인가] 애호박 1개: 10건
- costco :: [행사] 농심 신라면 120g: 10건
- costco :: [행사] 농심 오징어 땅콩 85g: 10건
- costco :: 국내산 돼지 삼겹살 구이용 냉장 600g: 10건
- costco :: 동서식품 맥심 모카골드 11.7g x 100T: 10건
- costco :: 동원 라이트참치 100g: 10건
- costco :: 롯데칠성 칠성사이다 1.5L: 10건

## 4. brand 결측 / 합성 타이틀 중복어 케이스
- title 첫 단어 반복(예: 코카콜라 코카콜라) 후보: 0건

## 5. matching_entries 적재 카운트 vs products
- matching_entries: 21
- products: 800
→ matching 21 vs products 800. raw 800건이 matching_entries 21건에 의존해 들어간 게 아니라 직접 매칭 없이 들어간 구조.

## 6. 단위 분포 (products.unit)
- 'g': 490
- 'ml': 200
- '개': 80
- 'kg': 30

## 7. raw_payload 키 분포 (마트별 첫 50건)
- emart: {'name': 50, 'store': 50, 'brand': 50, 'name_core': 50, 'pack_qty': 50, 'pack_unit': 50, 'sale_price': 50, 'original_price': 50, 'attributes': 50, 'attributes.source_name': 50, 'attributes.brand': 50, 'attributes.source_record_key': 50}
- homeplus: {'name': 50, 'store': 50, 'brand': 50, 'name_core': 50, 'pack_qty': 50, 'pack_unit': 50, 'sale_price': 50, 'original_price': 50, 'attributes': 50, 'attributes.source_name': 50, 'attributes.brand': 50, 'attributes.source_record_key': 50}
- lottemart: {'name': 50, 'store': 50, 'brand': 50, 'name_core': 50, 'pack_qty': 50, 'pack_unit': 50, 'sale_price': 50, 'original_price': 50, 'attributes': 50, 'attributes.source_name': 50, 'attributes.brand': 50, 'attributes.source_record_key': 50}
- costco: {'name': 50, 'store': 50, 'brand': 50, 'name_core': 50, 'pack_qty': 50, 'pack_unit': 50, 'sale_price': 50, 'original_price': 50, 'attributes': 50, 'attributes.source_name': 50, 'attributes.brand': 50, 'attributes.source_record_key': 50}

## 8. products.attributes / image_url / description 채움 비율
- attributes: 0/800
- image_url: 0/800
- description: 0/800

## 9. baseline_prices 마트별 분포 (가격 비교 가능성)
(error: no such column: mart_code)

## 10. 한 product 당 평균 baseline_prices 수 (=마트 비교 가능 product 비율)
- avg=1.00, min=1, max=1, products_with_>=2_marts=0
