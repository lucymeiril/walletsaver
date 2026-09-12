# Checkpoint after strict review of pending 033

상태: `proposal_only`. DB import/rebuild, taxonomy code edit, pytest, verify scripts는 실행하지 않았다. pass41 baseline `5,280 loaded / 3,916 pending`은 그대로다.

## pending 033 — Emart `제지/위생/건강`

- files read: `pending/033/001.json`, `pending/033/002.json`
- observations opened: **30**
- already classification-complete exclusions: **12**
- new classification reviews: **18 observations / 18 listings**
- existing-leaf proposals: **5**
- holds: **13**
- proposal: `proposals/emart-hygiene-health-033.json`

### existing leaf 5
- 조르단 어린이용 STEP-3 -> `beauty.personal.oral.toothbrush` (retailer category/detail used to disambiguate the short product title)
- 코디 맘껏양껏 110매(캡) -> `household.hygiene.paper.wipes` (retailer detail explicitly says cap-type wet wipes)
- 오랄비 크로스액션 플라그가드 -> `beauty.personal.oral.toothbrush`
- 페리오토탈7 오리지널 -> `beauty.personal.oral.toothpaste`
- 오랄비 어드벤티지 3입+크로스액션2입 -> `beauty.personal.oral.toothbrush`; mixed-package issue remains separate

### hold 13
- 손소독제 1: product form `hand_sanitizer`; current pass41 leaf not confirmed, manual hygiene-taxonomy hold.
- 리스테린 토탈케어 플러스 1: candidate `beauty.personal.oral.mouthwash`; current oral leaves confirm toothpaste/toothbrush/floss but no mouthwash leaf.
- 포이시안 야돔 1: nasal aromatic inhaler product-form hold.
- 일반 중형/대형 생리대 9: candidate `household.hygiene.feminine.day`. Current feminine leaves are liner/overnight/pants/tampon only; do not force regular pads into liner/overnight.
- 시니어돌봄 리필형패드 1: candidate `household.hygiene.incontinence.pad`; adult care/incontinence pad, not menstrual pad.

### already-classified 12
- toilet paper: 96:5, 96:18, 96:27, 96:77
- toothpaste: 96:13, 96:14, 96:33, 96:46
- floss: 96:43
- kitchen towels: 96:65, 96:66
- toothbrush: 96:76

These rows remain pending only for quantity/unit/promotion or other non-classification reasons and were excluded from new-classification accounting.

## explicit-decision collision screen

All 18 new-classification raw_record_ids were searched in three repository batches. Results surfaced raw/pending/unresolved/accounting material but not `review-decisions-input.json`. Proposal-stage screen only; the 431 explicit decisions were not modified.

## strict reverse 누계

pending `033~043`:
- observations opened: **288**
- already-classified exclusions: **29**
- strict/new classification reviews: **259**
- distinct newly reviewed listings: **247**
- existing leaf: **91**
- hold: **156**

남은 strict-audit 상한: `pending 001~032` **1,595 observations**, pass41 pending 3,916 대비 약 **40.7%**. 실제 새 판단량은 과거 proposal coverage 때문에 더 작을 수 있다.

## next resume point

**pending 032** (PENDING_INDEX 32 observations / 32 titles).

1. `pending/032/` 디렉터리의 모든 조각 확인.
2. already-classified와 classification-pending 분리.
3. 기존 proposal이 032를 포함한다고 주장하면 raw_record_id coverage 실측.
4. 누락만 supplement/reconciliation으로 기록하고 판단 conflict는 명시.
5. 완료 즉시 `CURRENT_STATUS.md`를 031로 갱신.
