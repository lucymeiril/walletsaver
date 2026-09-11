# WalletSaver 초기 DB 분류 — 현재 상태 (CANONICAL)

> **현재 작업 상황과 재개점은 이 파일을 단일 기준으로 본다.**
> `PROGRESS.md`와 `checkpoints/`는 역사 로그라 오래된 누적치/재개점이 섞일 수 있다. 새 AI는 `README.md` 다음에 이 파일을 읽는다.

마지막 갱신: 2026-09-12
브랜치: `cleanup/remove-legacy-ai-admin-coupling`
현재 모드: **GitHub read/write, proposal_only**
동결 DB 기준선: **pass41 — 5,280 loaded / 3,916 pending**
Chat 단계에서는 DB import/rebuild/test를 실행하지 않는다. 이 수치는 proposal을 추가해도 변하지 않는다.

## 1. 작업 계약 요약

- pending 원문을 직접 읽고 통합 taxonomy 분류 제안/hold를 만든다.
- broad 마트 shelf보다 **title/product form**, 필요하면 세부 URL/category path를 우선한다.
- 이미 `review_status=classified`인데 단위/수량/행사 문제로 pending에 남은 행은 신규 classification 작업량에서 제외한다.
- 반복 수집은 listing 하나의 판단으로 보되 모든 `raw_record_ids`를 보존한다.
- pass41 snapshot에 없는 leaf는 legacy 코드에 있다는 이유만으로 existing leaf로 쓰지 않는다.
- deal/promotion collection은 단일 상품으로 분류하지 않는다.
- Chat에서는 `proposal_only`; 나중에 Codex에서 전역 reconciliation 후 DB에 한 번에 반영한다.
- **proposal 파일이 존재한다는 사실만으로 그룹 완료로 보지 않는다. raw_record_id/source-key coverage를 확인한다.** pending 034에서 기존 proposal이 29건 중 19건만 덮고 있던 실제 누락을 발견했다.

## 2. 완성까지 얼마나 남았나

현재 **strict reverse audit의 안전한 상한**:

- 아직 이 방식으로 끝까지 재검증하지 않은 범위: `pending 001~033`
- 해당 원본 관측: **1,625 observations**
- pass41 전체 pending 3,916 대비 **약 41.5%**
- 관측 구간으로는 `034~451`이 약 58.5%를 지난 셈이지만, 이것을 “58.5% 최종 완료”라고 부르면 안 된다. 과거 proposal 중복/re-review와 taxonomy hold가 남아 있다.
- `001~033`에도 과거 proposal이 있는 그룹이 있으므로 실제 새 판단량은 **1,625보다 작을 가능성이 높다**. raw-key 전역 reconciliation 전에는 더 작은 수치를 최종 미완료량으로 확정하지 않는다.

분류 sweep 뒤 최종 DB 반영 전에도 남는 단계:
1. proposal 간 raw-record/source-key 중복 제거
2. first-vs-final proposal 충돌표 작성/결정 (`pending 313`의 `cup_ramen` vs `udon` 충돌 이미 발견)
3. 신규 taxonomy 후보/hold 정책 결정
4. 431 explicit review decisions와 최종 충돌 검사
5. Codex에서 새 pass DB import/rebuild + 관련 검사 + 멱등성 확인

## 3. strict reverse sweep 현재 누계

완료 범위: **pending 034~043**

- observations opened: **258**
- already-classified exclusions: **17**
- strict classification reviews: **241**
- distinct newly reviewed source listings: **229**
- existing-leaf proposals: **86 listings**
- taxonomy/product-form/promotion/manual-review holds: **143 listings**

그룹별 최신 proposal/reconciliation:
- 043 `proposals/lottemart-vegetables-043.json` — 23 obs / existing 21 / hold 2
- 042 `proposals/homeplus-tableware-042.json` — 24 obs / 12 listings / hold 12
- 041 `proposals/costco-fish-shelf-041.json` — 24 / existing 13 / hold 11
- 040 `proposals/costco-vegetable-shelf-040.json` — 25 opened / 5 excluded / 20 new / existing 8 / hold 12
- 039 `proposals/emart-sports-travel-auto-039.json` — 26 / hold 26
- 038 `proposals/emart-stationery-038.json` — 26 / hold 26
- 037 `proposals/emart-beverages-037.json` — 27 opened / 6 excluded / 21 new / existing 9 / hold 12
- 036 `proposals/emart-bakery-jam-036.json` — 27 opened / 4 excluded / 23 new / existing 2 / hold 21
- 035 `proposals/costco-milk-shelf-035.json` — 27 opened / 2 excluded / 25 new / existing 9 / hold 16
- 034 `proposals/reconciliation-pending-034.json` — 29 pending / prior proposal coverage 19 / previously uncovered 10 / final existing 24 / hold 5

최신 체크포인트:
- `checkpoints/checkpoint-after-pending-034-reconciliation.md`
- `checkpoints/checkpoint-after-pending-035.md`
- `checkpoints/checkpoint-after-pending-036.md`
- `checkpoints/checkpoint-after-pending-037.md`
- `checkpoints/checkpoint-reverse-sweep-038-043.md`

## 4. pending 034에서 확인된 문서/회계 문제

- 기존 `proposals/grains-nuts-028-034.json`은 `reviewed_pending_groups=[034,028]`이라고 적었지만 034 raw 29건 중 실제 결정은 19건뿐이었다.
- strict audit에서 빠진 10건을 찾아 `proposals/reconciliation-pending-034.json`으로 보완했다.
- 누락 10건: existing 5(강냉이, 현미, 혼합견과, 땅콩, 상세구성 확인한 혼합곡) + hold 5(피칸, 치아씨드, 호박씨, 미숫가루 2건).
- 기존 19건은 현재 정책과 충돌 없이 재검증했다.
- 이 사례 때문에 앞으로 저번호 과거 proposal 그룹은 **파일 존재가 아니라 raw coverage를 실측**한다.

## 5. 이미 확인된 중요 reconciliation 사실

- `pending 045` proposal 누락을 발견해 22 observations / 11 pizza listings를 `food.meals.prepared.pizza` proposal로 보수했다.
- `044~109` proposal 파일 존재 감사에서는 045가 유일한 누락 파일이었다. 단, 파일 존재는 raw-key 전량 coverage 증명이 아니다.
- ordered range `110~451`: **1,163 inspected / 1,113 classification reviews / 50 exclusions**. 이 수치는 범위 coverage이지 과거 proposal 대비 새 increment가 아니다.
- `288~451` reconciliation: final sweep 281, exclusions 15, classification-pending 266, legacy overlap 238, 과거 proposal 대비 진짜 신규 increment **28 observations** (`288`, `292~304`). 해당 14 source keys는 431 explicit decision exact match 0.
- `pending 313` 제품 `농심 생생 우동 용기 276G`: 이전 proposal `cup_ramen`, final sweep `udon`으로 충돌. 최종 승격 전에 해결 필요.

## 6. 현재 재개점 — pending 033

**다음 AI는 임의로 다른 그룹을 고르지 말고 여기서 이어간다.**

- group: `pending/033`
- PENDING_INDEX: **30 observations / 30 titles**
- 아직 strict accounting/classification 및 기존-proposal coverage 대조를 시작하지 않았다.

033 strict audit 절차:
1. `pending/033/` 디렉터리의 모든 파일 조각 확인.
2. 전체 observations에서 already-classified vs classification-pending 분리.
3. 033을 포함한다고 주장하는 기존 proposal이 있으면 `raw_record_id` coverage를 먼저 계산.
4. 431 `review-decisions-input.json` collision screen.
5. 누락만 supplement/reconciliation으로 기록하고 판단 충돌은 명시.
6. 완료 즉시 이 파일의 strict 누계/남은 상한을 갱신하고 재개점을 `032`로 넘긴다.

## 7. 문서 신뢰 우선순위

새 AI가 최초 사용자 프롬프트만 받은 경우:

1. `README.md` — 작업 계약과 이 파일 안내
2. **`CURRENT_STATUS.md` — 현재 상태/정확한 재개점 (최우선)**
3. `PROGRESS.md` — append-only 역사 로그; 오래된 다음 재개점/누적치는 무시 가능
4. `PENDING_INDEX.md` — 원본 그룹 크기/진열 인덱스; 완료표가 아님
5. 필요한 최신 `checkpoints/*.md`, `proposals/*.json`

문서가 충돌하면 **CURRENT_STATUS의 재개점/strict accounting을 우선**하고, 최종 사실 판단은 `pending/`·`raw/` 원문으로 확인한다.
