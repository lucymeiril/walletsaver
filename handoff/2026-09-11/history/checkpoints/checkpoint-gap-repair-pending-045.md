# WalletSaver 분류 누락 보완 체크포인트 — pending 045

## 기준

- 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 pass: `pass41`
- 기준 DB 수치: 5,280 적재 / 3,916 pending
- 기존 explicit review decision: 431
- 이번 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.

## 발견한 누락

`checkpoint-after-pending-451-classification-complete.md`는 PENDING_INDEX 001~451의 classification-only proposal sweep가 끝났다고 기록했지만, proposal accounting reconciliation 과정에서 **pending 045가 proposal 기록 없이 빠져 있음을 확인했다.**

- pending 045: Homeplus `냉장/냉동/밀키트 > 피자/핫도그/치킨 > 피자/브리또 > 냉동피자/브리또`
- 관측: **22**
- 고유 판매페이지/제목: **11**
- 모든 행의 현재 상태: `unified_category_id=null`, `classification_confidence=0`, `category_not_resolved_to_leaf` 포함
- 따라서 이미 classification-resolved라서 건너뛴 묶음이 아니다.
- 11개 `source_record_key`를 기존 431개 `review-decisions-input.json`과 exact-key 대조했고 충돌은 **0건**이다.

즉, pending 045는 기존 explicit decision 때문에 생략된 것이 아니라 실제 proposal coverage gap이었다.

## 보완 판단

기존 taxonomy/catalog에 `food.meals.prepared.pizza` (`피자`) 리프가 존재하며, 감사된 기존 데이터에도 피자 상품 선례가 있다. 별도 frozen-pizza 리프는 확인되지 않았고 이번 11개 제목은 모두 상품형태를 `피자`로 직접 명시한다.

따라서 22관측 전부를 기존 리프 `food.meals.prepared.pizza`로 제안했다.

- 페페로니/치즈크러스트
- 코리안 BBQ
- 불고기
- 스윗 치즈
- 스위트포테이토&콘
- 토마토 치즈
- 콤비네이션
- 콰트로치즈
- 모짜렐라 치즈
- 머쉬룸
- 베이컨 치즈

위 표현은 토핑/맛/스타일 속성으로 보며 taxonomy 분기를 새로 만들지 않았다. 냉동 여부도 이번 데이터에서 별도 상품유형 리프를 만들 근거로 사용하지 않았다.

## 원본 식별자

| source_record_key | 제목 | raw_record_ids |
|---|---|---|
| `061178566` | 오뚜기 페페로니 디럭스 치즈크러스트 피자 510G | `ingestion:9:64`, `ingestion:59:2` |
| `069424257` | 풀무원 노엣지피자 코리안BBQ 322G | `ingestion:9:85`, `ingestion:59:54` |
| `126345736` | 오뚜기 불고기 피자 396G | `ingestion:10:16`, `ingestion:59:53` |
| `069318320` | 씨제이 고메 스윗 치즈피자 325G | `ingestion:10:17`, `ingestion:59:40` |
| `069424205` | 풀무원 노엣지피자 스위트포테이토&콘 365G | `ingestion:10:20`, `ingestion:59:42` |
| `069318337` | 씨제이 고메 토마토 치즈피자 345G | `ingestion:10:22`, `ingestion:59:44` |
| `126345667` | 오뚜기 콤비네이션 피자 415G | `ingestion:10:43`, `ingestion:59:33` |
| `059662721` | simplus 콰트로치즈 피자 340G | `ingestion:10:61`, `ingestion:59:98` |
| `059662715` | simplus 모짜렐라 치즈피자 355G | `ingestion:10:63`, `ingestion:59:97` |
| `059662738` | simplus 머쉬룸 피자 365G | `ingestion:10:65`, `ingestion:60:42` |
| `142796621` | 오뚜기 베이컨 치즈 피자 352G | `ingestion:11:37`, `ingestion:60:75` |

홈플러스 반복 수집은 동일 `source_record_key`의 두 관측을 한 결정의 `raw_record_ids`에 묶었으며 서로 다른 상품으로 쪼개지 않았다.

## 생성 파일

- `handoff/2026-09-11/proposals/homeplus-frozen-pizza-045.json`
- 이 체크포인트

둘 다 `proposal_only` 기록이며 현재 importer가 자동 적용하는 explicit review input이 아니다.

## 회계 정정

이번 발견 때문에 과거의 “001~451 classification sweep complete” 문구는 **당시 문서 상태 기준으로는 엄밀히 틀렸다.** pending 045를 이번 proposal로 보완했으므로 이 특정 gap은 닫혔지만, 전역 accounting reconciliation이 끝날 때까지 다른 저번호 coverage gap이 없다고 단정하지 않는다.

또한 044 이전/초기 proposal 시기의 `cumulative_reviewed_unique_observations`는 시기에 따라 “열어 본 고유 관측”과 “새 classification 검토 관측” 정의가 섞여 있다. 예를 들어 pending 044는 22관측 중 1관측이 이미 classification-resolved였지만 당시 누적값에는 22가 모두 더해졌다. 반면 후속 체크포인트들은 이미 classification-resolved인 행을 classification-only 신규 진척에서 제외하기 시작했다.

따라서 다음 숫자는 그대로 최종 unique classification-reviewed total로 사용하지 않는다.

- 과거 checkpoint의 1,318 / 2,165 누적값
- 배치별 `cumulative_reviewed_unique_observations`의 단순 합 또는 차이

## 현재 안전하게 확정 가능한 후속 회계

- pending 110~150 ordered bulk: classification review 280 / already-classified-only 17
- pending 151~208 ordered bulk: classification review 292 / already-classified-only 16
- pending 209~287 ordered bulk: classification review 275 / already-classified-only 2
- pending 288~451 ordered final sweep: classification review 266 / already-classified-only 15
- 따라서 서로 겹치지 않는 ordered range **110~451 내부**에서는 1,163관측 중 classification review 1,113 / already-classified-only 50으로 범위 회계를 잡을 수 있다.
- 288~451 final sweep의 266 classification review 중 ordered sweep 이전 proposal과 겹치지 않는 실제 증분은 별도 reconciliation에서 확정한 **28관측**이다.

이 수치는 DB 적재 증가가 아니다. 또한 110~451의 1,113 전체를 431 explicit decision과 전량 exact-key 대조한 최종 결과라는 뜻도 아니다. 이번 세션에서 전량 exact-key로 확인한 것은 288~451의 unique-new 28관측과 pending 045의 22관측이다.

## 기존 proposal 판단 충돌

proposal accounting 중 pending 313 `농심 생생 우동 용기 276G`에 대해 최초 proposal과 final sweep의 leaf가 다름을 확인했다.

- 최초: `food.meals.noodles.cup_ramen`
- final sweep: `food.meals.noodles.udon`

자동으로 최신 판단을 승격하지 않고 reconciliation hold로 유지한다.

## 실행하지 않은 것

- staging SQLite import/rebuild
- proposal -> explicit review decision 승격
- catalog rebuild
- taxonomy 코드 수정
- `verify_initial_stage.py`
- pytest / 회귀 테스트
- 멱등 import 검사
- 새 pass DB 생성

따라서 pass41의 5,280 적재 / 3,916 pending은 그대로다.

## 다음 재개점

1. PENDING_INDEX `001~043` 및 `046~109`에서 proposal/explicit-decision coverage가 실제로 빠진 그룹이 더 없는지 audit한다. 특히 초기 누적 숫자를 coverage 증거로 사용하지 말고 raw_record_id/source_record_key 기준으로 확인한다.
2. `001~109`의 proposal 관측을 raw_record_id 기준으로 전역 dedupe하여 `classification-reviewed`, `held`, `already-classified-only`, `non-classification-only`를 분리한다.
3. 같은 observation이 여러 proposal에 있을 때 최초/최종 leaf 또는 hold 판단을 비교해 conflict table을 만든다. pending 313은 이미 첫 충돌로 기록되어 있다.
4. 그 후에만 001~451 전체의 최종 unique-reviewed total을 게시한다.
5. 실행 가능한 환경에서는 승인된 항목만 explicit review decision으로 승격하고 새 pass를 재구축한 뒤 관련 검증을 실제 실행한다.
