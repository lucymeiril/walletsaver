# 분류 검토 체크포인트 — 402 / 3,916

- 기준선: pass41 보류 3,916관측.
- 중복 `raw_record_id`를 제외하고 실제로 열어 검토한 보류 관측: **402건 (10.3%)**.
- 아직 열어 검토하지 않은 보류 관측: **3,514건 (89.7%)**.
- 이 수치는 분류 검토 진척도이며 staging DB 적재 수치가 아니다. proposal은 자동 import 입력이 아니므로 pass41 DB 기준선은 **5,280 적재 / 3,916 보류** 그대로다.

## 380 체크포인트 이후 신규 검토

1. `proposals/homeplus-kitchen-produce-367-372.json`
   - 12관측을 읽었으나 `pending/370` 미나리 2관측은 선행 `vegetable-new-leaf-candidates-249-418.json`에 이미 포함되어 신규 진척에서 제외했다.
   - 신규 고유 관측 +10 → 누적 390.
   - 기존 리프: 건대추, 부추, 통배추.
   - 신규 taxonomy 후보: 주방 필러, 아욱/근대. 미나리는 기존 water_parsley 후보 결정을 재확인만 했다.

2. `proposals/homeplus-produce-374-382.json`
   - 선행 vegetable proposal에 포함되지 않은 12관측을 신규 검토했다.
   - 기존 리프 제안: 맛타리버섯, 모둠버섯 2상품, 다진마늘, 깐마늘 — 총 8관측.
   - 신규 taxonomy 후보: 미니 로메인 2관측 → 기존 선행 정책과 맞춰 `food.produce.vegetables.lettuce` 후보.
   - 비분류 pending: 양파 중(망) 2관측은 이미 `food.produce.vegetables.onion`으로 분류되어 있고 `source_specification_changed`만 남아 있어 별도 표시했다.
   - 신규 고유 관측 +12 → 누적 402.

## 중복 방지 및 안전장치

- `pending/370`, `373`, `378`, `379`, `381`, `383`, `384`는 선행 `proposals/vegetable-new-leaf-candidates-249-418.json`에서 이미 검토된 raw 관측이므로 이번 누적에 다시 더하지 않았다.
- 신규 proposal의 판매페이지 키를 기존 `review-decisions-input.json` 431개 명시 결정과 대조했으며 확인한 키 충돌은 0건이다.
- 기존 명시 결정, pass41 catalog/DB, `initial_taxonomy.py`는 수정하지 않았다.
- staging SQLite 재구축/DB import, pytest, `verify_initial_stage.py`, 멱등 import 검사는 실행하지 않았다.

## 다음 재개점

`pending/385`부터 실제 미검토 소형 묶음을 이어간다. 각 배치에서 선행 proposal/raw id 중복을 먼저 확인하고, 완료 시 `cumulative_reviewed_unique_observations`와 `remaining_unreviewed_observations`를 갱신한다.
