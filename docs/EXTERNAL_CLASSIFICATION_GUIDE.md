# 외부 LLM 분류 워크플로우 운영 매뉴얼 (RD7)

> 대상: WalletSavior 운영자(개발 비전공자 포함)
> 목적: 크롤링된 raw 상품 데이터를 **외부 LLM(ChatGPT/Claude 등)** 으로 분류하고 DB에 누적시키는 주간 운영 절차를 정리합니다.
> 이 문서 한 장만 보고 끝까지 수행할 수 있도록 작성했습니다.

---

## 1. 개요

### 왜 외부 LLM인가?

RD6에서 시도한 **라이브 AI 파이프(Google Gemini)** 는 `504 Gateway Timeout`이 잦고 비용/속도 모두 운영 부담이 컸습니다.
대신 RD7부터는 다음 방식으로 전환합니다:

> 크롤러는 raw만 모으고, **분류는 관리자 PC의 외부 LLM**(Codex / Claude / GPT / Haiku 등)에 의뢰한 뒤
> 그 결과 파일을 **db-admin /import**에 업로드해 DB에 누적합니다.

라이브가 아니므로 **주 1회 (또는 캡처 직후)** 배치로 처리합니다. 시간이 자유롭고, 모델도 자유롭게 고를 수 있습니다.

### 전체 흐름

```
┌─────────────┐   crawl   ┌──────────────┐
│  마트 전단   │ ────────▶ │ raw_products │
└─────────────┘           └──────┬───────┘
                                  │
              ┌───────────────────┼────────────────────┐
              ▼                                        ▼
      ┌──────────────────┐                  ┌──────────────────────┐
      │ matching hit     │                  │ matching miss        │
      │ → 자동 분류 완료 │                  │ → crawler-admin       │
      └──────────────────┘                  │   export (raw-batch) │
                                            └──────────┬───────────┘
                                                        │ 폴더 다운로드
                                                        ▼
                                              ┌──────────────────┐
                                              │ 운영자 PC: 외부  │
                                              │ LLM에 system     │
                                              │ prompt + context │
                                              │ + raw 투입       │
                                              └──────────┬───────┘
                                                        │ 3종 파일 회수
                                                        ▼
                                              ┌──────────────────┐
                                              │ db-admin /import │
                                              │  preview→confirm │
                                              └──────────┬───────┘
                                                        ▼
                                              ┌──────────────────┐
                                              │ DB 누적 (matching│
                                              │ / category / kw  │
                                              │ / products)      │
                                              └──────────────────┘
```

### 매주 / 캡처 직후 운영자 작업 요약

1. crawler-admin에서 **export 폴더 다운로드** (raw-batch zip 1개)
2. 폴더 안 `context/` 와 `raw_products.jsonl`을 외부 LLM에 투입
3. LLM 출력 3종 파일 회수
4. db-admin `/import` 에 드래그드롭 → preview → confirm
5. `/matching` 페이지에서 hit율 모니터링

### 추천 모델

매주 1회 호출 정도라 **경량 모델**로도 충분합니다.

| 모델 | 강점 | 권장 용도 |
|---|---|---|
| **Claude Haiku 4.5** | 빠르고 한국어/JSON 안정적, 비용 저렴 | 기본 추천. 100~300건 배치 |
| **GPT-4.1** | 긴 컨텍스트, 스키마 준수 | matching이 적어 추론 비중이 클 때 |
| GPT-5 / Claude Opus | 품질 최상 | 첫 라운드(컨텍스트가 비어있을 때) 1회만 |
| Gemini 2.x | 무료 한도 활용 가능 | 보조용 (504 주의) |

---

## 2. Export 폴더 구조

crawler-admin이 만드는 export 폴더는 항상 다음 구조입니다.

```
artifacts/exports/raw-batch/exp-20260525HHMMSS-xxxxx/
├── raw_products.jsonl          ← LLM에 줄 원본 (필수)
├── raw_products.csv            ← 사람이 엑셀로 확인용
├── context/
│   ├── matching_entries.jsonl  ← 현재 매칭 테이블 전량 스냅샷
│   ├── categories.yaml         ← 카테고리 트리
│   └── keywords.yaml           ← 키워드 사전
└── manifest.json               ← export 메타 (id, 생성 시각, 건수)
```

### 2-1. `raw_products.jsonl`

한 줄당 한 상품. 크롤러가 캡처한 원본을 거의 그대로 담습니다.

| 필드 | 타입 | 예시 | 설명 |
|---|---|---|---|
| `raw_id` | string | `raw-20260525-emart-0001` | 고유 ID. products.jsonl에서 그대로 사용 |
| `mart` | string | `emart` | 마트 코드 (`emart`/`lotte`/`homeplus`...) |
| `raw_name` | string | `[행사] 농심 오징어 땅콩 85g` | 캡처된 상품명 원문 |
| `price` | int | `1980` | 정가(원) |
| `discount_price` | int\|null | `1480` | 할인가(원). 없으면 null |
| `captured_at` | string (ISO8601) | `2026-05-25T10:00:00+09:00` | 캡처 시각 |
| `image_url` | string\|null | `https://.../a.jpg` | (선택) 이미지 URL |
| `source_url` | string\|null | | (선택) 원문 URL |

### 2-2. `raw_products.csv`
위와 동일 데이터의 CSV 버전. 운영자 확인용.

### 2-3. `context/matching_entries.jsonl`

현재 DB의 매칭 테이블 **전량 스냅샷**. LLM이 "이미 등록된 키"를 재사용하도록 학습시키는 핵심 컨텍스트.

| 필드 | 타입 | 예시 |
|---|---|---|
| `match_key` | string | `농심\|오징어 땅콩\|85\|g` |
| `brand` | string | `농심` |
| `name_core` | string | `오징어 땅콩` |
| `pack_qty` | int | `85` |
| `pack_unit` | string | `g` |
| `category_id` | string | `food.snack.savory` |
| `keywords` | string[] | `["오징어땅콩","과자"]` |
| `aliases` | string[] | `["[행사] 오징어 땅콩"]` |

### 2-4. `context/categories.yaml`

```yaml
categories:
  - id: food
    label: 식품
    children:
      - id: food.snack
        label: 과자/스낵
        children:
          - id: food.snack.savory
            label: 짭짤한 스낵
          - id: food.snack.sweet
            label: 달콤한 스낵
```

### 2-5. `context/keywords.yaml`

```yaml
keywords:
  - keyword: 과자
    category_hint: food.snack
    synonyms: [스낵, snack]
  - keyword: 생수
    category_hint: drink.water
    synonyms: [물, mineral water]
```

### 2-6. `manifest.json`

```json
{
  "export_id": "exp-20260525153012-a1b2c",
  "created_at": "2026-05-25T15:30:12+09:00",
  "raw_count": 247,
  "matching_snapshot_count": 1583,
  "categories_count": 92,
  "keywords_count": 318
}
```

---

## 3. LLM에 줄 System Prompt 템플릿

**전체 본문은** [`docs/templates/external_llm_system_prompt.md`](./templates/external_llm_system_prompt.md) **에 별도 저장**되어 있습니다.
사용 시 그대로 복사해 ChatGPT/Claude의 system prompt(또는 첫 메시지)에 붙여넣고,
다음 자리표시자만 교체하세요:

| placeholder | 교체 내용 |
|---|---|
| `{{CONTEXT_MATCHING_ENTRIES}}` | `context/matching_entries.jsonl` 전문 |
| `{{CONTEXT_CATEGORIES}}` | `context/categories.yaml` 전문 |
| `{{CONTEXT_KEYWORDS}}` | `context/keywords.yaml` 전문 |
| `{{RAW_PRODUCTS}}` | `raw_products.jsonl` 전문 (또는 배치 분할분) |

### 핵심 규칙 요약 (LLM에게 강조)

- **기존 컨텍스트 최우선 재사용**: `[행사] 오징어 땅콩` 같은 표기는 별도 키를 만들지 말고
  기존 `농심|오징어 땅콩|85|g` 의 `aliases`에 추가.
- **신규 카테고리/키워드는 정말 없을 때만**: 기존에 적합한 게 있으면 신규 생성 금지.
- **confidence < 0.6 인 항목**은 `notes`에 사유 적기 (import 시 자동으로 `pending_human` 처리됨).
- **단위 정규화**:
  - 무게 `g`/`kg` → 가능한 `g`로 통일 (예: `1.5kg` → `1500g`)
  - 부피 `ml`/`L` → `ml`로 통일
  - 개수 `개`/`매`/`입`/`팩`
  - 묶음 상품은 **총량** 기준 + `notes`에 묶음 정보 기록

---

## 4. 출력 파일 스키마 (LLM이 생성해야 할)

### 4-1. `matching_updates.jsonl`

한 줄당 하나의 매칭 키 (신규 또는 기존 키에 alias 추가).

```json
{"match_key":"농심|오징어 땅콩|85|g","brand":"농심","name_core":"오징어 땅콩","pack_qty":85,"pack_unit":"g","category_id":"food.snack.savory","keywords":["오징어땅콩","과자","스낵"],"confidence":0.92,"source":"external-ai","aliases":["[행사] 오징어 땅콩"],"notes":""}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `match_key` | string | ✅ | `브랜드\|name_core\|pack_qty\|pack_unit` |
| `brand` | string | ✅ | 브랜드(제조사) |
| `name_core` | string | ✅ | 정규화된 핵심 상품명 |
| `pack_qty` | int | ✅ | 정수 용량/개수 |
| `pack_unit` | string | ✅ | `g`/`ml`/`개`/`매` 등 |
| `category_id` | string | ✅ | 카테고리 트리의 leaf id |
| `keywords` | string[] | ✅ | 2~5개 권장 |
| `confidence` | float | ✅ | 0.0 ~ 1.0 |
| `source` | string | ✅ | 항상 `"external-ai"` |
| `aliases` | string[] | ⭕ | 흡수할 raw_name 변형들 |
| `notes` | string | ⭕ | 사람 검수용 메모 |

### 4-2. `categories_keywords_updates.yaml`

**신규 제안만** 담습니다. 없으면 빈 리스트로.

```yaml
categories:
  - id: food.snack.savory_new
    parent_id: food.snack
    label: 신규 짭짤 스낵
    label_en: savory snack

keywords:
  - keyword: 신규키워드
    category_hint: food.snack.savory
    synonyms: [동의어1, 동의어2]
```

### 4-3. `products.jsonl`

raw_id → 최종 product 매핑. **raw 개수 = 이 파일 줄 수** 여야 함.

```json
{"raw_id":"raw-20260525-emart-0001","match_key":"농심|오징어 땅콩|85|g","mart":"emart","price":1980,"discount_price":1480,"unit_price":17411,"unit_price_basis":"100g","captured_at":"2026-05-25T10:00:00+09:00"}
```

| 필드 | 타입 | 설명 |
|---|---|---|
| `raw_id` | string | raw_products.jsonl 의 raw_id 그대로 |
| `match_key` | string | matching_updates 또는 기존 컨텍스트의 키 |
| `mart` | string | `emart`/`lotte`/... |
| `price` | int | 정가(원) |
| `discount_price` | int\|null | 할인가(원) 또는 null |
| `unit_price` | int | 100g/100ml/1개 기준 원 단위 정수 |
| `unit_price_basis` | string | `100g`/`100ml`/`1개`/`1매` |
| `captured_at` | string | ISO8601 |

---

## 5. Import 방법

1. db-admin 프론트에 로그인 → **`/import` 페이지** 진입.
2. 3종 파일(`matching_updates.jsonl`, `categories_keywords_updates.yaml`, `products.jsonl`)을
   **개별 드래그드롭** 하거나, 셋을 묶은 **zip을 통째로** 올립니다.
3. **Preview 화면**에서 다음을 확인:
   - 신규 매칭 키 N개 / 기존 키 alias 추가 M개
   - 신규 카테고리·키워드 제안 (사람 검수 대상으로 표시)
   - confidence 분포 히스토그램
   - 충돌(diff) 목록 — 기존 키와 category/keywords가 달라지는 항목
4. **Confirm** 클릭 → DB 반영.
5. 실패 row가 있으면 **`failures.csv` 다운로드** 버튼이 나타납니다.
   사유 컬럼을 보고 외부 LLM에 해당 row만 재요청하세요.

---

## 6. 실패 시 대응

| 증상 | 원인 | 대응 |
|---|---|---|
| Preview에서 "스키마 위반 N건" | LLM이 필드 누락/타입 오류 응답 | failures.csv 받아 해당 raw_id만 재요청 |
| confidence < 0.6 다수 | 컨텍스트 부족 | import는 진행됨 (status=pending_human). `/matching`에서 사람이 검수 |
| 신규 match_key 폭증 | LLM이 컨텍스트 무시 | system prompt에 "기존 컨텍스트 우선" 문구 강화, 모델을 한 단계 올림 |
| `products.jsonl` 줄 수 ≠ raw 개수 | LLM이 누락/중복 | 차집합 raw_id 재요청 |
| LLM 응답이 잘리거나 OOM | 컨텍스트 너무 큼 | raw_products를 100~300건 배치로 분할 |

---

## 7. 운영 체크리스트

매주 작업 시 아래를 그대로 따라가세요.

- [ ] crawler-admin에서 raw-batch export 폴더 다운로드
- [ ] export 폴더에 **6개 파일**(raw_products.jsonl/csv, context/3개, manifest.json) 모두 있는지 확인
- [ ] `manifest.json`의 `raw_count` 확인 (이번 주 처리량 파악)
- [ ] LLM 채팅창에 `docs/templates/external_llm_system_prompt.md` 복사
- [ ] 자리표시자 4개(`{{CONTEXT_MATCHING_ENTRIES}}`, `{{CONTEXT_CATEGORIES}}`, `{{CONTEXT_KEYWORDS}}`, `{{RAW_PRODUCTS}}`) 모두 교체
- [ ] 컨텍스트가 너무 크면 raw_products를 **100~300건씩 배치 분할**
- [ ] LLM 응답에서 3종 결과(matching_updates.jsonl / categories_keywords_updates.yaml / products.jsonl) 회수
- [ ] 결과를 **같은 export_id 폴더 또는 새 폴더**에 저장 (보관용)
- [ ] db-admin `/import` 에 업로드 → **preview** 확인 → **confirm**
- [ ] failures.csv가 있으면 재요청 → 재 import
- [ ] db-admin `/matching` 페이지에서 **hit율 그래프** 확인 (주차별 추세 상승하면 OK)

---

## 8. 자주 묻는 질문

**Q1. 첫 라운드라 matching_entries가 거의 비어있는데, 컨텍스트만 보고 분류가 될까요?**
A. `categories.yaml`과 `keywords.yaml`은 사전에 정의되어 있어 카테고리 분류는 가능합니다.
`matching_entries`는 누적되는 자산이므로, **첫 라운드는 LLM의 일반 지식에 의존**합니다.
초기에는 GPT-5/Claude Opus 같은 상위 모델 1회 사용을 권장하고, 누적 후엔 Haiku로 충분합니다.

**Q2. LLM이 새 카테고리를 마구 만들면 어떡하죠?**
A. 신규 제안은 `categories_keywords_updates.yaml`에 모이고 **즉시 DB에 반영되지 않습니다**.
db-admin Preview에서 **사람 검수 후 채택** 여부를 결정합니다.
빈도가 높으면 system prompt의 "기존 컨텍스트 우선" 규칙을 강조해 재요청하세요.

**Q3. `[행사]`, `[1+1]`, `★` 같은 프로모션 prefix가 매번 달라요. 매번 새 매칭이 만들어지나요?**
A. 아니요. system prompt가 이런 prefix를 **제거 후 핵심명 추출**하도록 지시하며,
원문 표기는 `matching_updates`의 `aliases` 필드에 흡수됩니다.
같은 상품은 매주 누적적으로 alias만 늘어나고 매칭 키는 1개로 유지됩니다.

**Q4. 라이브 AI는 영원히 안 쓰나요?**
A. 보류 상태입니다. 안정적인 무료/저가 라이브 모델이 나오면 다시 검토합니다.
현재 워크플로우는 라이브 전환에 대비해 **동일한 3종 파일 스키마**를 유지합니다.

**Q5. 한 번에 몇 건까지 LLM에 넣어도 되나요?**
A. 모델 컨텍스트 한도에 따라 다르지만 안전선은:
- Claude Haiku 4.5 / GPT-4.1: **raw 200~300건 + context 전체**
- 초과 시 raw를 100건씩 배치로 분할, context는 매 배치에 동일하게 포함

---

### 변경 이력
- 2026-05-25 RD7 최초 작성 — 외부 LLM 분류 워크플로우 도입.
