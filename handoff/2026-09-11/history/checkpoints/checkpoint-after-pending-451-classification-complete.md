# WalletSaver 분류 체크포인트 — pending 451까지 classification sweep 완료

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.
- pass41 실제 기준선(5,280 적재 / 3,916 pending)은 변경하지 않았다.

## 이번 최종 순차 sweep

- 시작: pending 288
- 종료: pending 451
- `PENDING_INDEX.md`의 마지막 그룹은 451이며 `pending/452/001.json`은 존재하지 않는다.
- 이번 sweep에서 읽은 관측: **281**
- 현재 pending snapshot에서 classification 자체가 이미 resolved라 제외한 관측: **15**
- classification 미해결 상태로 다시 검토한 관측: **266**
- 따라서 PENDING_INDEX 기준으로 **분류 검토 순차 sweep은 끝까지 완료**했다.

## 매우 중요한 회계 정정

이번 sweep 중 기존 `proposals/`와 `PROGRESS.md`를 다시 대조하면서, pending 288~451의 상당수 그룹이 이번 ordered sweep 이전에 이미 `proposal_only` 파일로 검토되어 있었다는 사실을 확인했다.

예를 들어 다음과 같은 선행 proposal들이 존재한다.

- `fruit-small-142-143-198-199-200-260-284-289-290-291-406-407.json`
- `grains-nuts-small-139-282-344-400-405-443-446.json`
- `homeplus-small-306-310.json`
- `homeplus-noodles-canned-311-316.json`
- `homeplus-canned-sides-spreads-317-322.json`
- `beverages-small-219-327.json`
- `homeplus-household-328-333.json`
- `homeplus-cleaning-seafood-334-339.json`
- `homeplus-seafood-340-343.json`
- `small-food-344-354-404-449-450.json`
- `homeplus-baby-skincare-347-348.json`
- `homeplus-meat-355-360.json`
- `homeplus-kitchen-tools-361-366.json`
- `homeplus-kitchen-produce-367-372.json`
- `vegetables-small-244-382.json`
- `vegetable-new-leaf-candidates-249-418.json`
- `homeplus-produce-374-382.json`
- `homeplus-produce-tea-honey-385-390.json`
- `organic-vegetables-385-422.json`
- `lottemart-small-391-396.json`
- `lottemart-small-397-403.json`
- `homeplus-small-406-412.json`
- `homeplus-small-413-420.json`
- `mixed-small-421-428.json`
- `lottemart-small-429-436.json`
- `lottemart-small-437-442.json`
- `lottemart-small-447-448-451.json`

이 파일들은 applied explicit decision이 아니라 proposal-only 선례지만, 이미 사람이 검토한 관측이므로 이번 sweep의 266건을 전부 `새로운 unique review`로 다시 더하면 이중 집계가 된다.

따라서 다음 숫자는 이번 체크포인트에서 **의도적으로 확정하지 않는다**.

- pending 288~451의 `unique_new_classification_reviews`
- 이전 checkpoint의 2,165에 이번 266을 더한 누적값
- unique-review 기준 최종 완료 퍼센트

이전 `checkpoint-after-pending-287.md`의 `2,165 / 3,916`은 당시 작성된 **historical accounting**으로 보존하되, legacy proposal overlap dedupe 전에는 전체 unique coverage를 나타내는 최종 수치로 사용하지 않는다.

## classification 이미 resolved라 이번 sweep 진척에서 제외한 15관측

- pending 289: 배 2관측 — `food.produce.fruit.pear`, `count_range_unresolved`만 남음
- pending 308: 맛살 2관측 — `food.seafood.processed.surimi`
- pending 354: 파스타소스 2관측 — `food.seasonings.sauces.pasta`, `source_title_changed`만 남음
- pending 382: 양파 2관측 — `food.produce.vegetables.onion`, `source_specification_changed`만 남음
- pending 389: 커피믹스 2관측 — `food.drinks.coffee.mix`, `mixed_package_unresolved`만 남음
- pending 399: 고등어 2관측 — 기존 고등어 분류 resolved
- pending 432: 배 1관측 — 기존 배 분류 resolved, count-range 사유만 남음
- pending 433: 사과 1관측 — 기존 사과 분류 resolved
- pending 451: 양배추 1관측 — 기존 양배추 분류 resolved

## 최종 sweep proposal

- `handoff/2026-09-11/proposals/bulk-pending-288-451-final-sweep.json`
- 288~451의 순차 검토 완료 사실과 281/15/266 회계를 기록했다.
- `unique_new_classification_reviews`는 legacy proposal dedupe가 필요하므로 `null`로 남겼다.
- 선행 proposal이 있는 그룹은 기존 보수적 판단을 재사용했고, 새 sweep에서 임의로 뒤집지 않았다.

## 대표적인 title-first 판단

- pending 295: 돈까스 진열이지만 실제 제목은 치킨까스
- pending 296: 산적 진열이지만 실제 제목은 너비아니
- pending 302: 피자 진열이지만 실제 제목은 피아디나; 기존 pizza veto 보존
- pending 305: 부침두부 진열이지만 실제 제목은 순두부
- pending 306: 순두부 진열이지만 실제 제목은 찌개용두부
- pending 324: 감귤주스 진열이지만 실제 제목은 매실 음료; 선행 보류 판단 보존
- pending 337: 먹태 진열이지만 실제 제목은 명엽채
- pending 343: 낙지/문어 혼합 진열은 실제 문어/낙지 상품형태로 분리
- pending 349: 후추 진열이지만 실제 제목은 페페로치노홀
- pending 413: 액체세제 진열이지만 실제 제목은 캡슐세제
- pending 423~424: 중화면/짜장면 진열이지만 실제 제목은 짬뽕
- pending 431: 우동사리 진열이지만 실제 제목은 라멘
- pending 436: 총각김치 진열이지만 실제 제목은 석박지
- pending 437: 샌드위치 진열이지만 실제 제목은 핫도그
- pending 438: 라면 진열이지만 실제 제목은 잡채
- pending 443: 건과일 진열이지만 실제 제목은 고구마말랭이
- pending 444: 과일칩 진열이지만 실제 제목은 부각

## 보존 원칙

- 431개 explicit review decision은 수정하지 않았다.
- raw/invalid 관측을 수정하지 않았다.
- 수량, 행사조건, 가격, 상품 병합, count-range, mixed-package, unit, title/specification-change 문제를 classification-only 검토로 해소했다고 간주하지 않았다.
- 신규 taxonomy 후보는 proposal-only hold이며 `initial_taxonomy.py`에 추가하지 않았다.
- 선행 proposal과 현재 판단이 겹칠 때는 raw/title 근거 없이 선행 판단을 조용히 교체하지 않았다.

## 실제로 실행하지 않은 것

이번 작업에서는 다음을 실행하지 않았다.

- staging SQLite import 또는 재구축
- proposal을 explicit review decision으로 승격/적용
- catalog rebuild
- taxonomy 코드 수정
- `verify_initial_stage.py`
- pytest / 전체 회귀 테스트
- 멱등 import 검사
- 새 pass DB 생성 및 데이터 무결성 검증

따라서 결과는 계속 `proposal_only`이며 pass41의 5,280 적재 / 3,916 pending 기준선은 그대로다.

## 현재 단계의 완료 의미

- **PENDING_INDEX 001~451에 대한 classification review 순차 sweep은 끝까지 도달했다.**
- 이것은 3,916 pending이 DB에서 사라졌다는 뜻이 아니다.
- 기존 leaf에 제안할 수 있는 항목, 신규 taxonomy가 필요한 hold, 이미 classification이 끝나고 다른 사유만 남은 항목을 전부 한 번씩 순차적으로 검토했다는 뜻이다.
- 일부 관측은 ordered sweep 이전의 legacy proposal에서도 이미 검토되었으므로 unique review 총량은 별도 dedupe가 필요하다.

## 다음 작업

새 pending classification 그룹은 없다. 다음 단계는 **proposal accounting reconciliation**이다.

1. 모든 `proposal_only` 파일에서 `raw_record_id` / `source_record_key`를 수집한다.
2. 동일 관측의 중복 리뷰를 제거하고 최초/최종 제안을 비교한다.
3. explicit 431개 decision과도 다시 충돌 검사한다.
4. unique reviewed / held / already-classified-only / non-classification-only 수치를 확정한다.
5. 실행 가능한 환경에서 승인된 항목만 explicit decision으로 승격하고 새 pass를 rebuild한다.

그 전까지는 이전 bulk 체크포인트의 누적 퍼센트를 최종 unique coverage로 사용하지 않는다.
