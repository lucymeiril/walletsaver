# WalletSaver 분류 체크포인트 — pending 061 완료 후

## 현재 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 데이터/분류 pass: `pass41`
- 기준 pending 관측 수: 3,916
- 기존 explicit review decision 수: 431
- 현재 작업은 GitHub read/write 기반 `proposal_only` 검토이며 DB/운영 반영이 아니다.

## 최신 유효 진행 회계

브랜치에 뒤늦게 추가된 `checkpoint-after-pending-054.md`의 `next: 055`는 커밋 계보상 이미 pending 055~057 proposal이 존재한 뒤 기록된 낡은 재개점이다. 최신 유효 회계는 다음과 같다.

- pending 054 완료: 675 / 3,916
- pending 055 proposal: 675 -> 692
- pending 056 proposal: 692 -> 708
- pending 057 proposal: 708 -> 724
- pending 058 proposal: 724 -> 740
- pending 059 proposal: 740 -> 756
- pending 060 proposal: 756 -> 772
- pending 061 proposal: 772 -> 788

## 이번 세션에서 이어서 완료한 proposal_only

### pending 058

- 파일: `handoff/2026-09-11/proposals/homeplus-noodles-058.json`
- 16관측 / 8상품
- 쫄면 5상품 / 10관측 -> 기존 `food.meals.noodles.jjolmyeon`
- 냉면·동치미 육수 3상품 / 6관측 -> 기존 `food.seasonings.sauces.broth`
- 신규 taxonomy 후보 없음

### pending 059

- 파일: `handoff/2026-09-11/proposals/homeplus-curry-jjajang-059.json`
- 16관측 / 8상품
- 카레 분말·조리용 카레 믹스 7상품 / 14관측 -> 기존 `food.seasonings.powders.curry`
- `오뚜기 짜장 분말100G` 1상품 / 2관측 -> 신규 후보 `food.seasonings.powders.black_bean`
- 분말 상품을 기존 `food.seasonings.sauces.black_bean`으로 강제하지 않음

### pending 060

- 파일: `handoff/2026-09-11/proposals/homeplus-kitchen-cleaning-060.json`
- 16관측 / 8상품
- 현재 pass41 주방용품 taxonomy에 수세미·행주·스펀지 거치대 대응 leaf가 없어 전부 신규 후보로 보류
- 수세미 6상품 / 12관측 -> `household.kitchen.cleaning.scrubber`
- 부직포행주 1상품 / 2관측 -> `household.kitchen.cleaning.dishcloth`
- ScrubDaddy 스펀지캐디 1상품 / 2관측 -> `household.kitchen.cleaning.sponge_holder`
- root 포함 최대 4레벨 제약을 지키기 위해 `household > kitchen > cleaning > leaf` 구조로 제안

### pending 061

- 파일: `handoff/2026-09-11/proposals/homeplus-liquid-tea-061.json`
- 16관측 / 8상품
- `자임 꿀유자차 1KG` 2관측 -> 기존 `food.drinks.tea.citron`
- `꽃샘 피어나다 히비스커스&자몽 350G` 2관측 -> 기존 `food.drinks.tea.herbal`
- 생강계 2상품 / 4관측 -> 신규 후보 `food.drinks.tea.ginger`
- 꿀레몬차 1상품 / 2관측 -> 신규 후보 `food.drinks.tea.lemon`
- 꿀한라봉차 1상품 / 2관측 -> 신규 후보 `food.drinks.tea.hallabong`
- 음용 애사비 2상품 / 4관측 -> 신규 후보 `food.drinks.vinegar.apple_cider`
- 음용 애사비는 조리용 `food.seasonings.baking.vinegar`로 강제하지 않음

## 누적 진행률

- 세션 시작 전 최신 유효 누적: 724 / 3,916
- 이번 세션 추가 검토: 64
- 현재 누적 검토: 788 / 3,916 (약 20.1%)
- 남은 미검토: 3,128 / 3,916 (약 79.9%)

이 수치는 `proposal_only` 검토 진행량 회계다. pass41 DB의 실제 5,280 적재 / 3,916 보류 기준선은 그대로 유지한다.

## 보존한 원칙

- 실제 상품명을 원본 진열 경로보다 우선한다.
- 기존 leaf가 제품형태와 명확히 맞을 때만 기존 taxonomy에 제안한다.
- 분말/액상, 면/육수, 주방도구/청소도구처럼 제품형태가 다르면 비슷한 이름의 기존 leaf에 강제하지 않는다.
- 수량, 행사조건, 원본 관측, 상품 병합은 classification-only 검토에서 수정하지 않는다.
- promotion 관련 unresolved 사유는 분류 제안만으로 해소된 것으로 세지 않는다.
- 기존 431개 explicit review decision을 덮어쓰지 않는다.

## 실제로 실행하지 않은 검증/반영

이번 작업에서는 다음 항목을 실행하지 않았으며 완료로 간주하지 않는다.

- staging SQLite import 또는 재구축
- proposal을 explicit review decision으로 승격/적용
- catalog rebuild
- taxonomy 코드 수정
- `verify_initial_stage.py`
- pytest / 전체 회귀 테스트
- 멱등 import 검사
- 새 pass DB 생성 및 데이터 무결성 검증

따라서 이번 결과는 분류 제안이며 운영/DB 반영 상태가 아니다.

## 다음 재개점

- 다음 대상: `handoff/2026-09-11/pending/062/001.json`
- PENDING_INDEX 순서를 그대로 이어 검토한다.
- 재개 시 먼저 실제 제목/판매페이지 키/raw record ID를 확인한다.
- 기존 proposal 중복과 431개 explicit review decision 충돌을 다시 검사한다.
- 분류가 이미 resolved이고 행사/수량 등 다른 pending 사유만 남은 관측은 classification-only 해소로 세지 않는다.
- 새 taxonomy leaf가 필요하면 기존 leaf에 억지로 넣지 말고 신규 후보로 보존한다.
