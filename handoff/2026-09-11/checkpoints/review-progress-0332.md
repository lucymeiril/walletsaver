# 분류 검토 체크포인트 — 332 / 3,916

- 기준선: pass41 보류 3,916관측.
- 중복 `raw_record_id`를 제외하고 실제로 열어 검토한 보류 관측: **332건 (8.5%)**.
- 아직 열어 검토하지 않은 보류 관측: **3,584건 (91.5%)**.
- 이 수치는 분류 검토 진척도이며 DB 적재 수치가 아니다. staging DB 재구축/제안 import를 하지 않았으므로 pass41 실제 DB 기준선은 5,280 적재 / 3,916 보류 그대로다.

## 286 체크포인트 이후 완료한 proposal

1. `proposals/homeplus-small-306-310.json`
   - 10관측 검토.
   - 기존 리프 제안: 찌개용 일반두부, 쌈무, 맥스봉 핫바.
   - 이미 분류되고 규격만 pending: 크라비아 160G+80G.
   - 정책 보류: 흑마늘 오리바베큐를 훈제오리에 강제하지 않음.

2. `proposals/homeplus-noodles-canned-311-316.json`
   - 12관측 검토.
   - 기존 리프: 메밀면, 농심 생생우동 용기(기존 코스트코 동일 제품의 cup_ramen 선례), 후르츠칵테일, 오이피클.
   - 신규 taxonomy 후보: 즉석 떡국, 키드니빈 통조림.

3. `proposals/homeplus-canned-sides-spreads-317-322.json`
   - 12관측 검토.
   - 기존 리프: 쇠고기장조림, 꽁치통조림.
   - 신규 taxonomy 후보: 번데기통조림, 고등어통조림, 마가린.
   - 형태 보류: 샘표 매콤한맛 깻잎은 pickled/seasoned 경계라 강제하지 않음.

4. `proposals/homeplus-household-328-333.json`
   - 12관측 검토.
   - 기존 리프: 냉장고 탈취제 2관측, 울세제 2관측.
   - 신규 taxonomy 후보: 모기기피 미스트, 분무기, 세탁볼, 막대걸레 8관측.
   - 막대걸레 `unit_unresolved`와 울세제 1+1 구조는 변경하지 않음.

## 누적 계산

이전 체크포인트 286건 + 306~310 10건 + 311~316 12건 + 317~322 12건 + 328~333 12건 = **332건**.

`pending/323`~`327`은 이미 이전 `beverages-small-219-327.json`에서 검토·집계됐으므로 다시 세지 않았다.

따라서 `3,916 - 332 = 3,584`건이 아직 미검토다.

## 기존 결정 보호

각 새 배치의 `source_record_key`를 `review-decisions-input.json`과 대조했으며 이번 체크포인트 범위에서 발견된 키 충돌은 0건이다. 기존 431개 명시 decision 파일은 수정하지 않았다.

## 실행하지 않은 것

- staging SQLite 재구축/DB import 미실행
- `verify_initial_stage.py` 미실행
- pytest 미실행
- 멱등 import 검사 미실행
- `initial_taxonomy.py` 미수정
- 기존 431개 명시 review decision 미수정

## 다음 재개점

`pending/334`부터 아직 미검토인 소형 Homeplus 묶음을 이어간다. 각 proposal 저장 시 `baseline_pending_observations=3916`, `cumulative_reviewed_unique_observations`, `remaining_unreviewed_observations`를 함께 기록한다. 최종 승격 전에는 모든 proposal을 raw id 기준으로 병합·중복 제거하고 431개 명시 결정과 전체 충돌 검사를 다시 수행한다.
