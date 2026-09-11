# Checkpoint after strict reconciliation of pending 034

상태: `proposal_only`. DB import/rebuild, taxonomy code edit, pytest, verify scripts는 실행하지 않았다. pass41 baseline `5,280 loaded / 3,916 pending`은 그대로다.

## 핵심 발견

기존 `proposals/grains-nuts-028-034.json`이 pending 034를 포함한다고 적혀 있었지만, 실제 raw coverage는 **29 observations 중 19**뿐이었다. 즉 기존 문서만 보면 034가 처리된 것처럼 보이지만 **10 observations가 proposal에서 빠져 있었다.**

이 때문에 034부터는 단순 proposal-file 존재가 아니라 `raw_record_id`/source coverage를 기준으로 완료 여부를 판단한다.

## strict accounting

- files read: `pending/034/001.json`, `pending/034/002.json`
- observations opened: **29**
- already classification-complete exclusions: **0**
- strict classification reviews: **29**
- earlier proposal coverage: **19**
- previously uncovered rows: **10**
- final existing-leaf decisions: **24**
- final holds: **5**
- reconciliation proposal: `proposals/reconciliation-pending-034.json`

기존 19개 034 proposal은 모두 현재 title-first/pass41 정책과 호환되어 conflict 0으로 재검증했다.

## previously uncovered 10

### existing leaf 5
- `ingestion:80:28` 부드러운 추억의 강냉이 300g -> `food.snacks.savory.corn`
- `ingestion:80:32` 저당곡물 돼지감자 현미 2kg -> `food.grains.rice.brown`; retailer product detail에서 품목/원산지가 현미임을 확인
- `ingestion:80:34` 브라질넛/사차인치 슈퍼믹스 -> `food.grains.nuts.mixed`; bundle_multiplier issue는 별도
- `ingestion:80:36` 와사비맛 땅콩 -> `food.grains.nuts.peanut`
- `ingestion:80:41` 씻거나 불릴필요 없는 맛있는 우리 엄마 밥상 2kg -> `food.grains.rice.mixed`; retailer 상세 구성은 완두콩/귀리/현미/찰보리/찰현미/찹쌀 혼합

### hold/new-taxonomy 5
- `ingestion:80:25` 피칸 -> candidate `food.grains.nuts.pecan`
- `ingestion:80:30` 치아씨드 -> candidate `food.grains.seeds.chia`
- `ingestion:80:33` 발아 미숫가루 -> candidate `food.grains.powder.misutgaru`
- `ingestion:80:38` 호박씨 -> candidate `food.grains.seeds.pumpkin`
- `ingestion:80:40` 단백질 블랙미숫가루 -> same misutgaru/grain-powder candidate; ready-to-drink protein drink로 분류하지 않음

## explicit-decision collision screen

pending 034의 29 raw_record_id 전체를 네 묶음으로 repository search했다. `review-decisions-input.json` hit 0; raw/pending/unresolved/accounting 파일만 확인됐다. proposal-stage screen이며 431 explicit decisions를 수정하지 않았다.

## strict reverse 누계

pending `034~043`:
- observations opened: **258**
- already-classified exclusions: **17**
- new/strict classification reviews: **241**
- distinct newly reviewed listings: **229**
- existing leaf: **86**
- hold: **143**

남은 strict-audit 상한: `pending 001~033` **1,625 observations**, pass41 pending 3,916 대비 약 **41.5%**. 과거 proposal coverage를 실측하면서 실제 신규 판단량은 이 상한보다 작아질 수 있다.

## next resume point

**pending 033** (PENDING_INDEX 30 observations / 30 titles).

1. `pending/033/` 디렉터리의 모든 파일 조각부터 확인.
2. already-classified와 classification-pending 분리.
3. 033을 포함한다고 주장하는 기존 proposal이 있으면 raw_record_id coverage를 먼저 계산.
4. 누락만 supplement/reconciliation으로 기록하고 판단 충돌은 명시.
5. 완료 즉시 `CURRENT_STATUS.md`를 032로 갱신.
