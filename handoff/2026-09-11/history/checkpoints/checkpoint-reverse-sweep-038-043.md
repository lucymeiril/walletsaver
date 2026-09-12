# Reverse sweep consolidated checkpoint: pending 038~043

상태: `proposal_only`. staging DB import/rebuild, taxonomy code edit, repo tests는 실행하지 않았다. pass41 baseline `5,280 loaded / 3,916 pending`은 변경하지 않았다.

## 이번 연속 sweep의 엄격 회계

- pending groups completed: `038, 039, 040, 041, 042, 043`
- observations opened: **148**
- observations already classification-complete and excluded from new-classification count: **5** (all in pending 040)
- new classification-review observations: **143**
- distinct newly reviewed source listings: **131**
  - 042는 12개 판매페이지가 2회씩 관측되어 24 observations / 12 listings
  - 나머지 새 분류 대상은 이 구간에서 listing당 1 observation
- source listings proposed to confirmed existing leaves: **42**
- source listings held for new taxonomy/product-form/manual review: **89**
- 위 숫자는 과거 cumulative reviewed 값에 자동 가산하지 않는다. 과거 누적은 duplicate/re-review/already-classified observation을 섞어 기록한 시기가 있어 전역 reconciliation이 별도 필요하다.

## 그룹별 결과

### 043 — 롯데마트 채소
- proposal: `proposals/lottemart-vegetables-043.json`
- commit: `1f96ee450b2c277ea05b5d0a594920a2b9591193`
- 23 observations / 23 listings
- existing leaf: 21 listings
- hold: 2 listings (`lettuce`, `broccoli` new-leaf candidates)

### 042 — 홈플러스 일회용/다회용 공기 shelf
- proposal: `proposals/homeplus-tableware-042.json`
- commit: `7b39bd0041c0d47bf14e5e594003f9d6c9031039`
- 24 observations / 12 listings
- same source listing observed twice
- existing leaf: 0
- hold: 12 listings (tableware/storage product-form candidates)
- group spans `pending/042/001.json` + `002.json`

### 041 — 코스트코 생선 shelf
- proposal: `proposals/costco-fish-shelf-041.json`
- commit: `68c2d46be9a01d2600a7f8a6685cad608223ce30`
- 24 observations / 24 listings
- existing leaf: 13
- hold: 11
- heavily polluted shelf: title/product form was used over broad `생선` shelf

### 040 — 코스트코 채소 shelf
- proposal: `proposals/costco-vegetable-shelf-040.json`
- commit: `5ec5493ebbd3d97c5d2c8fe17afe813c949aff77`
- 25 observations opened
- 5 observations already classification-complete; excluded from new-classification count
- new classification reviews: 20 observations / 20 listings
- existing leaf: 8
- hold: 12
- group spans `pending/040/001.json` + `002.json`

### 039 — 이마트 스포츠/여행/자동차
- proposal: `proposals/emart-sports-travel-auto-039.json`
- commit: `9cc9705cfd8e6dd57ab46467f2d9749283b71180`
- 26 observations / 26 listings
- existing leaf: 0
- hold: 26
  - 18 automotive wiper listings grouped under one product-form candidate while retaining every raw id/key
  - remaining listings split into travel/service, fitness, cycling, golf, outdoor-light candidates
  - 2 fuel/hazard listings kept as manual-safety-review holds rather than automatic detailed taxonomy mappings
- group spans `pending/039/001.json` + `002.json`

### 038 — 이마트 문구/취미/도서
- proposal: `proposals/emart-stationery-038.json`
- commit: `a0f1c40c111c0f3f3ae541f0958b4fb6133ee3e6`
- 26 observations / 26 listings
- existing leaf: 0
- hold: 26 product-form taxonomy candidates
- grouped by notebook, packing tape, copy paper, writing tools, colored pencils, storage/file, memo board/bookend, etc.
- ambiguous `플립3 0.5mm` was product-form verified before being recorded as a multicolor ballpoint candidate
- group spans `pending/038/001.json` + `002.json`

## explicit review-decision conflict screen

For each group 038~043, newly classified source_record_keys were searched in batches across the repository. The searches did not surface `handoff/2026-09-11/review-decisions-input.json` for those keys. This is a proposal-stage conflict screen only and does not mutate the 431 explicit decisions.

## operational rules confirmed

1. Always list the pending group directory before reading; never assume only `001.json` exists.
2. Broad mart shelves are evidence, not the answer. Title/product form wins on conflict.
3. Exclude `review_status=classified` rows from new classification-review accounting even if they remain pending for quantity/unit/promotion issues.
4. Repeated observations of the same source listing are one listing decision with all raw_record_ids preserved.
5. Do not treat legacy taxonomy code as proof that a leaf exists in the pass41 handoff snapshot.
6. Keep taxonomy/product-form uncertainty as hold rather than forcing a broad/wrong existing leaf.

## next resume point

Continue reverse sweep at **pending 037**. First list `handoff/2026-09-11/pending/037/` to determine all file parts, then inspect every observation and separate already-classified rows before proposing classification changes.
