# 분류 검토 체크포인트 — 286 / 3,916

- 기준선: pass41 보류 3,916관측.
- 현재까지 중복 `raw_record_id`를 제외하고 실제로 열어 검토한 보류 관측: **286건 (7.3%)**.
- 아직 열어 검토하지 않은 보류 관측: **3,630건 (92.7%)**.
- 이 수치는 사람/모델의 **분류 검토 진척도**이며 DB 적재 수치가 아니다. staging DB를 다시 만들거나 proposal을 import하지 않았으므로 pass41의 실제 DB 기준선은 5,280 적재 / 3,916 보류 그대로다.

## 이번 체크포인트 직전 완료한 배치

1. `proposals/soy-muk-sprouts-212-214-305.json`
   - 신규 검토 14관측.
   - 기존 리프 제안 6관측: 숙주 4 → `food.produce.vegetables.sprouts`, 순두부 2 → `food.plant.soy.silken`.
   - 신규 taxonomy 후보 8관측: 콩물/콩국물 4, 청포묵/도토리묵 4.
   - 7개 `source_record_key`를 기존 `review-decisions-input.json`과 대조했으며 일치 0건.

2. `proposals/homeplus-small-211-217.json`
   - 신규 검토 16관측.
   - 기존 리프 제안 12관측: 백김치 4, 스위트콘 통조림 4, 즉석카레/짜장 4.
   - 신규 taxonomy 후보 4관측: 실곤약 2, 일반 곤약 2.
   - 스위트콘의 `promotion_unresolved`와 티아시아 키마커리의 기존 1+1 구조는 분류와 분리해 변경하지 않았다.
   - 10개 `source_record_key`를 기존 `review-decisions-input.json`과 대조했으며 일치 0건.

## 누적 계산

이전 proposal/검토 기록의 중복 raw 관측을 제거한 누적 256건 + 이번 14건 + 이번 16건 = **286건**.

따라서 `3,916 - 286 = 3,630`건이 아직 미검토다.

## 실행하지 않은 것

- staging SQLite 재구축/DB import 미실행
- `verify_initial_stage.py` 미실행
- pytest 미실행
- 멱등 import 검사 미실행
- `initial_taxonomy.py` 미수정
- 기존 431개 명시 review decision 미수정

## 다음 재개점

소형 Homeplus 인접 묶음 `pending/306`~`pending/310`부터 이어서 검토한다. 각 proposal을 닫을 때마다 `baseline_pending=3916`, `cumulative_reviewed`, `remaining_unreviewed`를 함께 기록한다. 최종 승격 전에는 모든 proposal을 `raw_record_id` 기준으로 합치고 기존 431개 명시 결정과 다시 충돌 검사한다.
