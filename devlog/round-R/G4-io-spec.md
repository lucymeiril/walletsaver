# Round R G4 — 외부 AI 분류 사이클 I/O 스펙

## 0. 목적
크롤러/DB-admin이 미매칭 상품을 외부 경량 AI(haiku/gpt-4.1 등)에 전달하고, AI 산출물 3종을 다시 import해 매칭·카테고리·키워드·상품 메타를 보강하기 위한 파일 계약이다. 새 DB 컬럼이나 마이그레이션은 만들지 않는다.

## 1. Export 번들 4종

### 1.1 `unclassified.jsonl`
분류 대상 상품 목록. JSON Lines이며 한 줄이 한 상품이다.

필드:
- `canon_hash`(string, required): `SHA1(brand|normalized_name|pack_qty|pack_unit)`. 40자 lowercase hex.
- `mart`(string): `emart|homeplus|lottemart|costco`.
- `mart_native_code`(string): 4사 안정 상품 코드. 이마트 `itemId`, 홈플러스 `itemNo`, 롯데마트 EAN-13, 코스트코 `/p/` 숫자.
- `raw_name`(string): 원본 상품명.
- `normalized_name`(string): 정규화 상품명.
- `brand`(string|null): 브랜드.
- `pack_qty`(number|null): 팩 수량.
- `pack_unit`(string|null): `g|kg|ml|L|개|봉|마리|단|망|팩` 등.
- `pack_count`(integer|null): 묶음 개수.
- `mart_native_category_id`(string|null): 마트 원본 카테고리 ID.
- `mart_native_category_path`(string|null): 마트 원본 카테고리 경로.
- `canonical_url`(string|null): 안정 상품 URL.

검증 규칙:
- `canon_hash`는 비어 있으면 안 되며 40자 SHA1 hex여야 한다.
- `mart_native_code`는 가능한 경우 반드시 포함한다. URL은 식별자로 쓰지 않는다.
- 한 파일 안에서 같은 `canon_hash`가 중복되면 같은 상품 후보로 취급한다.

예시 3개:
```jsonl
{"canon_hash":"0123456789abcdef0123456789abcdef01234567","mart":"emart","mart_native_code":"1000123456789","raw_name":"[행사] CJ 햇반 210g*12","normalized_name":"CJ 햇반 210g 12개","brand":"CJ","pack_qty":210,"pack_unit":"g","pack_count":12,"mart_native_category_path":"가공식품 > 즉석밥","canonical_url":"https://emart.ssg.com/item/itemView.ssg?itemId=1000123456789&siteNo=7009"}
{"canon_hash":"abcdefabcdefabcdefabcdefabcdefabcdefabcd","mart":"lottemart","mart_native_code":"8801234567890","raw_name":"국내산 양배추 1통","normalized_name":"국내산 양배추","brand":null,"pack_qty":1,"pack_unit":"개","pack_count":1,"mart_native_category_path":"채소/엽채류","canonical_url":"https://lottemartzetta.com/products/OS8801234567890/details"}
{"canon_hash":"1111111111111111111111111111111111111111","mart":"costco","mart_native_code":"1234567","raw_name":"커클랜드 키친타월 12롤","normalized_name":"커클랜드 키친타월 12롤","brand":"커클랜드","pack_qty":12,"pack_unit":"롤","pack_count":1,"mart_native_category_path":"Household > Paper","canonical_url":"https://www.costco.co.kr/.../p/1234567"}
```

### 1.2 `category_list.yaml`
현재 통합 카테고리 트리. 기본 원본은 `packages\shared\data\category_tree.yaml`이다.

필드:
- `nodes`(array): 카테고리 노드 목록.
- `id`: stable snake_case 카테고리 ID.
- `name_kr`: 한국어 이름.
- `name_en`: 영어 이름.
- `parent_id`: 부모 ID 또는 null.
- `display_order`: 표시 순서.
- `default_unit_kind`: `GRAM_PER_100G|ML_PER_100ML|EACH|ROLL|SET`.

검증 규칙:
- 기존 ID를 임의 변경하지 않는다.
- 새 카테고리는 이 파일에 직접 쓰지 않고 import 파일 `category_keyword_updates.yaml`에 제안한다.

예시 3개:
```yaml
nodes:
  - id: fresh_food
    name_kr: 신선식품
    parent_id: null
    default_unit_kind: GRAM_PER_100G
```
```yaml
nodes:
  - id: rice
    name_kr: 쌀
    parent_id: grain
    default_unit_kind: GRAM_PER_100G
```
```yaml
nodes:
  - id: kitchen_towel
    name_kr: 키친타월
    parent_id: sanitary
    default_unit_kind: ROLL
```

### 1.3 `keyword_list.yaml`
기존 키워드 목록. G4 skeleton은 빈 목록도 허용한다.

필드:
- `keywords`(array): 기존 키워드.
- `keyword`(string): 한국어 키워드.
- `category_id`(string|null): 연결 카테고리.
- `synonyms`(array): 동의어.

검증 규칙:
- 키워드는 한국어 명사 중심으로 유지한다.
- 기존 키워드는 재사용 우선, 신규/동의어는 import 파일에 제안한다.

예시 3개:
```yaml
keywords: []
```
```yaml
keywords:
  - keyword: 백미
    category_id: rice
    synonyms: [쌀]
```
```yaml
keywords:
  - keyword: 키친타월
    category_id: kitchen_towel
    synonyms: [주방타월]
```

### 1.4 `instructions.md`
공용 지침 링크/본문. 원본은 `packages\ai-admin\backend\prompts\external_classify_instructions_v1.md`이다.

검증 규칙:
- 외부 AI에는 지침, 카테고리 목록, 키워드 목록, 상품 목록을 함께 전달한다.
- AI는 지정된 import 3종 파일 외 임의 파일을 만들지 않는다.

예시 3개:
```md
공용 지침 원본: packages\ai-admin\backend\prompts\external_classify_instructions_v1.md
```
```md
출력 파일: matching_updates.jsonl, category_keyword_updates.yaml, product_updates.jsonl
```
```md
기존 카테고리 우선, 없으면 신규 카테고리 제안
```

## 2. Import 파일 3종

### 2.1 `matching_updates.jsonl`
`canon_hash`를 통합 카테고리와 키워드에 연결한다.

필드:
- `canon_hash`(string, required): export의 상품 키. 40자 lowercase SHA1 hex.
- `category_id`(string, required): 기존 또는 `category_keyword_updates.yaml`에 제안한 신규 카테고리 ID.
- `keywords`(array[string], required): 한국어 키워드 1~20개.
- `confidence`(number, required): 0.0~1.0.
- `source`(string, required): 항상 `external-ai`.
- `reason`(string|null): 분류 근거.

검증 규칙:
- `canon_hash`는 입력 목록에 존재해야 한다(실제 대조는 후속 DB 연동 단계).
- `category_id`는 stable snake_case여야 한다.
- `keywords`는 중복 제거 후 1개 이상이어야 한다.
- `source`는 `external-ai`만 허용한다.

예시 3개:
```jsonl
{"canon_hash":"0123456789abcdef0123456789abcdef01234567","category_id":"rice","keywords":["쌀","백미"],"confidence":0.94,"source":"external-ai","reason":"상품명과 원본 카테고리가 쌀"}
{"canon_hash":"abcdefabcdefabcdefabcdefabcdefabcdefabcd","category_id":"cabbage","keywords":["양배추","채소","엽채류"],"confidence":0.91,"source":"external-ai","reason":"국내산 양배추 1통"}
{"canon_hash":"1111111111111111111111111111111111111111","category_id":"kitchen_towel","keywords":["키친타월","주방타월","롤타월"],"confidence":0.88,"source":"external-ai","reason":"생활용품 종이류"}
```

### 2.2 `category_keyword_updates.yaml`
신규 카테고리와 신규/보강 키워드를 제안한다.

필드:
- `new_categories`(array): 신규 카테고리 제안 목록.
  - `id`(string): stable snake_case ID.
  - `name_kr`(string): 한국어 이름.
  - `parent_id`(string|null): 기존 또는 함께 제안한 부모 ID.
  - `default_unit_kind`(string): `GRAM_PER_100G|ML_PER_100ML|EACH|ROLL|SET`.
  - `reason`(string): 신규 필요 사유.
- `keywords`(array): 키워드 제안 목록.
  - `keyword`(string): 한국어 키워드.
  - `category_id`(string|null): 연결 카테고리.
  - `synonyms`(array[string]): 동의어.
  - `reason`(string|null): 보강 사유.

검증 규칙:
- 신규 카테고리 ID는 기존 카테고리 ID와 충돌하면 안 된다(실제 충돌 검사는 후속 DB 연동 단계).
- `parent_id`는 가능하면 기존 카테고리를 사용한다.
- 키워드와 동의어는 1~20자 허용(가능하면 2자 이상 권장), 한국어 중심이다.

예시 3개:
```yaml
new_categories: []
keywords:
  - keyword: 백미
    category_id: rice
    synonyms: [쌀]
    reason: 쌀 검색 보강
```
```yaml
new_categories:
  - id: instant_rice
    name_kr: 즉석밥
    parent_id: processed_food
    default_unit_kind: GRAM_PER_100G
    reason: 즉석밥 전용 분류 필요
keywords:
  - keyword: 즉석밥
    category_id: instant_rice
    synonyms: [햇반, 컵밥]
```
```yaml
new_categories:
  - id: roll_cleaning_paper
    name_kr: 롤형 청소지
    parent_id: household
    default_unit_kind: ROLL
    reason: 키친타월과 청소포 중간 성격 상품 대응
keywords:
  - keyword: 롤청소지
    category_id: roll_cleaning_paper
    synonyms: [청소타월]
```

### 2.3 `product_updates.jsonl`
상품 메타 보강 파일. 분류만으로 충분하면 빈 파일 가능하다.

필드:
- `canon_hash`(string, required): export의 상품 키.
- `brand`(string|null): 보강 브랜드.
- `normalized_name`(string|null): 보강 정규화명.
- `raw_name`(string|null): 원문명 보정.
- `pack_qty`(number|null): 팩 수량.
- `pack_unit`(string|null): 팩 단위.
- `pack_count`(integer|null): 묶음 개수.
- `unit_price_basis`(string|null): 단위가격 기준 raw.
- `canonical_url`(string|null): 안정 URL.
- `mart_native_category_path`(string|null): 원본 카테고리 경로 보강.
- `notes`(string|null): 보강 근거.

검증 규칙:
- `canon_hash` 외에 보강 필드가 1개 이상 있어야 한다.
- `pack_qty`, `pack_count`는 양수여야 한다.
- URL은 표시/이동용이며 식별자는 `mart_native_code`/`canon_hash`다.

예시 3개:
```jsonl
{"canon_hash":"0123456789abcdef0123456789abcdef01234567","brand":"CJ","normalized_name":"CJ 햇반 백미 210g 12개","pack_qty":210,"pack_unit":"g","pack_count":12,"notes":"상품명에서 팩 정보 보강"}
{"canon_hash":"abcdefabcdefabcdefabcdefabcdefabcdefabcd","normalized_name":"국내산 양배추 1통","pack_qty":1,"pack_unit":"개","notes":"수량 단위 보강"}
{"canon_hash":"1111111111111111111111111111111111111111","brand":"커클랜드","pack_unit":"롤","mart_native_category_path":"Household > Paper > Kitchen Towel","notes":"원본 카테고리 경로 보강"}
```

## 3. 테스트 명령
```powershell
cd packages\db-admin\backend; py -3 -m pytest tests\test_external_ai_export.py tests\test_external_ai_import.py -q
```
