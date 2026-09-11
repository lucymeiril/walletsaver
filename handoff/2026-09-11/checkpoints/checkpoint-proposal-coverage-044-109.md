# WalletSaver proposal coverage checkpoint — pending 044~109

## 기준

- 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 pass: `pass41`
- 이 체크포인트는 proposal 파일 존재/범위 감사 기록이다.
- DB import/rebuild, explicit review decision 승격, taxonomy 변경은 하지 않았다.

## 파일 커버리지 감사 결과

`handoff/2026-09-11/proposals/`의 전용 proposal 파일을 pending group 번호 기준으로 대조했다.

- pending 044: `emart-household-044.json`
- pending 045: 기존에는 전용 proposal이 없었음 → 이번 세션에서 `homeplus-frozen-pizza-045.json`으로 보완
- pending 046~109: 각 group마다 해당 번호를 명시한 전용 proposal 파일이 존재함

따라서 **044~109 구간에서 전용 proposal 파일 자체가 빠져 있던 번호는 045 하나였고, 이 gap은 이번 세션에서 proposal_only로 보완했다.**

이 결론은 파일 존재 수준의 coverage audit이다. 각 파일이 해당 pending의 모든 raw observation을 빠짐없이 담았는지, 다른 proposal과 raw_record_id/source_record_key가 중복되는지, 최초/최종 leaf 판단이 충돌하는지까지 증명하는 것은 아니다.

## pending 045 보완 요약

- 관측: 22
- 고유 판매페이지: 11
- 기존 431 explicit review decision과 source_record_key exact collision: 0
- 제안 리프: `food.meals.prepared.pizza`
- 새 taxonomy 없음
- 파일: `handoff/2026-09-11/proposals/homeplus-frozen-pizza-045.json`
- 상세 근거: `handoff/2026-09-11/checkpoints/checkpoint-gap-repair-pending-045.md`

## 001~043 재감사 필요성

PENDING_INDEX 기준 pending 001~043은 총 **1,883관측**이다.

현재 proposal 디렉터리에서 이 저번호 범위를 직접 명시하는 초기 proposal은 `grains-nuts-028-034.json`이 확인된다. 이 파일은 028/034의 62관측을 읽은 작업에서 30개 mapping decision만 저장했고 나머지는 hold로 남긴 역사적 형식이라, 단순히 `decisions.length`를 review coverage로 사용할 수 없다.

따라서 001~043은 과거 누적값이나 파일명만으로 '완료' 처리하지 않는다. raw_record_id/source_record_key와 431 explicit review decision을 실제로 대조해야 한다.

## pending 043 착수 메모

다음 저번호 재검토 후보로 pending 043 (`lottemart | 채소 | 23관측`) 원본을 열기 시작했다.

첫 관측들만 보아도 제목이 다음처럼 서로 다른 상품형태를 명시한다.

- `풀무원 특등급 무농약 국산 콩나물 (340G)`
- `풀무원 국산 숙주나물 (260G)`
- `국내산 킹단호박 (개)`

원본 raw payload에는 첫 두 상품에 각각 더 상세한 retailer category path (`콩나물`, `숙주나물`)도 존재한다. 따라서 broad shelf `채소`를 하나의 통합 leaf로 일괄 적용하지 않고 title/product-form first 원칙으로 개별 검토해야 한다.

pending 043은 이번 체크포인트에서는 아직 proposal decision을 만들지 않았다.

## 회계상 유지할 안전한 사실

- pass41 DB 기준 5,280 loaded / 3,916 pending은 그대로다.
- 110~451 ordered ranges에서는 1,163관측 중 classification review 1,113 / already-classified-or-nonclassification-only 50으로 범위 회계가 가능하다.
- 288~451 final sweep의 266 classification review 가운데 legacy proposal에 없던 실제 증분은 28관측이다.
- pending 313의 최초/final proposal leaf 충돌은 reconciliation hold다.
- 초기 historical cumulative counters는 시기에 따라 '열어 본 관측'과 'classification-only 신규 검토' 정의가 섞여 있으므로 최종 unique classification-reviewed total로 사용하지 않는다.

## 다음 재개점

1. pending 043의 23관측을 title-first로 끝까지 읽고 source_record_key/raw_record_id를 수집한다.
2. 431 explicit review decision과 exact-key 충돌을 확인한다.
3. 기존 taxonomy leaf로 안전하게 제안 가능한 행만 proposal_only로 기록하고, 혼합/불명확 행은 hold한다.
4. 이후 pending 042 → 041 방향 또는 001부터의 raw-key coverage audit을 이어가며 001~043의 실제 미검토량을 확정한다.
5. 전역 dedupe/first-vs-final conflict table을 마친 후에만 001~451 전체 최종 unique-reviewed total을 게시한다.
