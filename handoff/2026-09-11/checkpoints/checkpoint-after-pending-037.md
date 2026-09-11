# Checkpoint after strict review of pending 037

상태: `proposal_only`. staging DB import/rebuild, taxonomy code edit, pytest, `verify_initial_stage.py`, 멱등 검사는 실행하지 않았다. pass41 baseline `5,280 loaded / 3,916 pending`은 변경되지 않았다.

## pending 037 결과

- source shelf: emart `생수/음료/주류`
- files read: `pending/037/001.json`, `pending/037/002.json`
- observations opened: **27**
- already classification-complete and excluded from new-classification count: **6**
- new classification reviews: **21 observations / 21 source listings**
- existing-leaf proposals: **9**
- holds/new-taxonomy/identity review: **12**
- proposal: `proposals/emart-beverages-037.json`

### existing leaf 9
- fruit drink 6: `오늘 사과해 100ml`, `루솔 모과품은 배도라지즙 100ml`, `처음먹는 배도라지`, `엘빈즈 ... 사과매실푸룬 100ml`, `고칼슘 오렌지 1.5L`, `따옴 오렌지 730ml` -> `food.drinks.juice.fruit_drink`
- non-alcoholic beer 2: Cloud non-alcoholic 350/500 -> `food.drinks.non_alcoholic.beer`
- bottled water 1: Jeju Samdasoo 500ml x40 -> `food.drinks.water_soda.water`

`fruit_drink` 항목은 제목만으로 100%/착즙 주스를 확정하지 않고 더 넓은 기존 leaf를 선택했다.

### hold 12
- `베베 끙아 씨`: 제목만으로 제품형태 확정 불가, 단위도 unresolved.
- 이유식/채소 퓨레 5건: current audited beverage classifier도 이유식/감자/고구마/단호박 퓨레를 음료에서 명시 제외한다. raw produce나 beverage로 강제하지 않고 baby-food/puree taxonomy 정책까지 보류.
- 오트몬드 프로틴 3건: 이전 proposal 정책과 동일하게 `food.drinks.other.protein` 신규 후보 hold. oat/almond/soy leaf로 원료를 추정해 강제하지 않음.
- 일반 비타500 1건: 이전 proposal과 동일하게 `food.drinks.water_soda.vitamin` 신규 후보 hold. `비타500 이온킥`의 sports, `비타500 스파클링`의 soda 선례를 일반 비타500에 확장하지 않음.
- 미에로 화이바 1건: `food.drinks.functional.fiber` 신규 후보 hold. 현재 pass41의 실존 leaf로 취급하지 않음.
- `1.8L*2입` 1건: 제목에 제품명이 없고 raw collection=`코카콜라`만 있어 cola/soda를 추정하지 않음.

### 이미 classification complete 6
- 처음 보리차 -> `food.drinks.tea.barley`
- 아이얌 프룬사과 주스 -> `food.drinks.juice.fruit`
- 아이얌 배도라지 주스 -> `food.drinks.juice.fruit`
- 아기 푸룬 주스 -> `food.drinks.juice.fruit`
- 햇살 담은 착즙 포도주스 100% -> `food.drinks.juice.fruit`
- 해태 갈아만든배 -> `food.drinks.juice.fruit_drink`

이 6건은 단위 등 다른 사유로 pending에 남아 있어 이번 신규 classification 작업량에서 제외했다.

## explicit decision collision screen

21개 신규 classification source_record_key를 세 묶음으로 repository search했다. 검색 결과는 pending/raw/unresolved에만 나타났고 `review-decisions-input.json`은 나타나지 않았다. proposal-stage screen이며 431 explicit decisions를 수정하지 않았다.

## 문서/회계 갱신

- canonical 현재 상태는 `handoff/2026-09-11/CURRENT_STATUS.md`.
- strict reverse sweep `037~043` 누계는 175 observations opened, 11 already-classified exclusions, **164 new classification reviews**, 152 distinct newly reviewed listings, 51 existing-leaf listings, 101 hold listings.
- strict audit 상한 재개 범위는 이제 `pending 001~036`, **1,708 observations**. pass41 pending 3,916 대비 약 **43.6%**다. 이 숫자는 남은 strict-audit 상한이지 최종 미완료 unique decision 수가 아니다.

## next resume point

**pending 036 — emart `베이커리/잼`, PENDING_INDEX 27 observations / 27 titles.**

디렉터리에는 `pending/036/001.json`, `pending/036/002.json` 두 파일이 있다. 둘 다 읽고 이미 classified인 행을 먼저 제외한 뒤 classification-pending만 proposal로 판단한다.
