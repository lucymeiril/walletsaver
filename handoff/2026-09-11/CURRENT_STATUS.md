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
- **proposal 파일 존재만으로 완료로 보지 않는다. raw_record_id/source-key coverage를 확인한다.** pending 034에서 기존 proposal이 29건 중 19건만 덮던 실제 누락을 발견했다.

## 2. 완성까지 얼마나 남았나

현재 strict reverse audit의 안전한 상한:

- 미완 strict 범위: `pending 001~032`
- 원본 관측: **1,595 observations**
- pass41 전체 pending 3,916 대비 **약 40.7%**
- 관측 구간 기준 `033~451`은 약 59.3%를 strict/ordered 방식으로 지나왔지만, 이것을 최종 완료율로 부르지 않는다. 과거 proposal 중복/re-review와 taxonomy hold가 남아 있다.
- `001~032`에도 과거 proposal이 있으므로 실제 새 판단량은 **1,595보다 작을 가능성이 높다**. raw-key 전역 reconciliation 전에는 더 작은 수치를 최종 미완료량으로 확정하지 않는다.

분류 sweep 뒤 최종 DB 반영 전 남는 단계:
1. proposal 간 raw-record/source-key 중복 제거
2. first-vs-final proposal 충돌표 작성/결정 (`pending 313`의 `cup_ramen` vs `udon` 충돌 이미 발견)
3. 신규 taxonomy 후보/hold 정책 결정
4. 431 explicit review decisions와 최종 충돌 검사
5. Codex에서 새 pass DB import/rebuild + 관련 검사 + 멱등성 확인

## 3. strict reverse sweep 현재 누계

완료 범위: **pending 033~043**

- observations opened: **288**
- already-classified exclusions: **29**
- strict/new classification reviews: **259**
- distinct newly reviewed source listings: **247**
- existing-leaf proposals: **91 listings**
- taxonomy/product-form/promotion/manual-review holds: **156 listings**

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
- 034 `proposals/reconciliation-pending-034.json` — 29 pending / prior coverage 19 / uncovered 10 / final existing 24 / hold 5
- 033 `proposals/emart-hygiene-health-033.json` — 30 opened / 12 excluded / 18 new / existing 5 / hold 13

최신 체크포인트:
- `checkpoints/checkpoint-after-pending-033.md`
- `checkpoints/checkpoint-after-pending-034-reconciliation.md`
- `checkpoints/checkpoint-after-pending-035.md`
- `checkpoints/checkpoint-after-pending-036.md`
- `checkpoints/checkpoint-after-pending-037.md`
- `checkpoints/checkpoint-reverse-sweep-038-043.md`

## 4. 최근 중요한 발견

### pending 033
- 30 rows 중 12는 이미 classification-complete; 단위/수량 등의 이유로 pending에 남아 있어 신규 분류량에서 제외.
- 신규 18 중 existing 5: toothbrush 3, toothpaste 1, wet wipes 1.
- 일반 중형/대형 생리대 9개는 current feminine taxonomy가 liner/overnight/pants/tampon만 갖고 있어 `household.hygiene.feminine.day` 후보 hold.
- senior-care refill pad는 menstrual pad가 아니므로 `household.hygiene.incontinence.pad` 후보 hold.
- mouthwash, aromatic inhaler, hand sanitizer도 현행 leaf 미확인으로 hold.
- 18 raw ids collision screen에서 `review-decisions-input.json` hit 0.

### pending 034
- 기존 `grains-nuts-028-034.json`은 034 raw 29건 중 19건만 실제 커버.
- strict audit에서 누락 10건 보완. existing 5 + hold 5. 기존 19건 conflict 0.
- 따라서 저번호 과거 proposal 그룹은 **파일 존재가 아니라 raw coverage를 실측**한다.

## 5. 이미 확인된 reconciliation 사실

- pending045 proposal 누락을 발견해 22 observations / 11 pizza listings를 `food.meals.prepared.pizza` proposal로 보수.
- 044~109 proposal 파일 존재 감사에서는 045가 유일한 누락 파일. 단, 파일 존재는 raw coverage 증명이 아님.
- ordered 110~451: **1,163 inspected / 1,113 classification reviews / 50 exclusions**.
- 288~451: final281, exclusions15, classification-pending266, legacy overlap238, 과거 proposal 대비 true new increment **28 observations** (`288`, `292~304`), 해당 14 source keys explicit exact match 0.
- pending313 `농심 생생 우동 용기 276G`: older `cup_ramen` vs final `udon` conflict. 최종 승격 전 해결.

## 6. 현재 재개점 — pending 032

**다음 AI는 임의로 다른 그룹을 고르지 말고 여기서 이어간다.**

- group: `pending/032`
- PENDING_INDEX: **32 observations / 32 titles**
- 아직 strict accounting/classification 및 기존-proposal coverage 대조를 시작하지 않았다.

032 strict audit 절차:
1. `pending/032/` 디렉터리의 모든 파일 조각 확인.
2. already-classified vs classification-pending 분리.
3. 032를 포함한다고 주장하는 기존 proposal이 있으면 `raw_record_id` coverage 실측.
4. 431 `review-decisions-input.json` collision screen.
5. 누락만 supplement/reconciliation으로 기록하고 conflict는 명시.
6. 완료 즉시 이 파일의 누계/남은 상한을 갱신하고 재개점을 `031`로 넘긴다.

## 7. 문서 신뢰 우선순위

새 AI가 최초 사용자 프롬프트만 받은 경우:
1. `README.md` — 작업 계약과 이 파일 안내
2. **`CURRENT_STATUS.md` — 현재 상태/정확한 재개점 (최우선)**
3. `PROGRESS.md` — 역사 로그; 오래된 다음 재개점/누적치는 무시 가능
4. `PENDING_INDEX.md` — 원본 그룹 크기/진열 인덱스; 완료표가 아님
5. 최신 `checkpoints/*.md`, `proposals/*.json`

충돌 시 **CURRENT_STATUS의 재개점/strict accounting을 우선**하고, 최종 사실 판단은 `pending/`·`raw/` 원문으로 확인한다.
