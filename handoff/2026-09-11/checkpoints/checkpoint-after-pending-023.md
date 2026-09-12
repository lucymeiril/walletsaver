# Checkpoint after pending 023

Date: 2026-09-12
Mode: GitHub read/write, proposal_only
Baseline: pass41 — 5,280 loaded / 3,916 pending

## Pending 023 strict review

- Group: `pending/023`
- Shelf: Costco `휴지`
- Files: `001.json`, `002.json`
- Observations opened: **39**
- Already-classified exclusions: **9**
- New classification reviews: **30**
- Distinct new source listings: **30**
- Existing-leaf proposals: **13**
- Holds: **17**
- Proposal: `proposals/costco-tissue-shelf-023.json`

### Already classified exclusions

Nine observations already have classification complete and remain pending only for bundle/unit reconciliation:

- `49:17`, `49:18` -> `household.hygiene.paper.facial`
- `49:23`, `49:24`, `49:33`, `49:39` -> `household.hygiene.paper.wipes`
- `49:38`, `49:46`, `49:47` -> `household.hygiene.paper.kitchen`

## Existing-leaf proposals

13 new listings fit confirmed current paper leaves:

- 6 explicit bath/toilet-roll products -> `household.hygiene.paper.toilet`
- 4 dry facial/portable tissue products -> `household.hygiene.paper.facial`
- 3 explicit wet/toilet wipes -> `household.hygiene.paper.wipes`

## Shelf pollution and holds

The broad Costco `휴지` shelf is materially polluted. Seventeen listings were held instead of forced into paper leaves:

- dry cotton tissue / compressed coin tissue: 5 listings including one opaque Merssue set
- body cooling/deodorant sheet: 1
- table napkin: 1; candidate `household.hygiene.paper.napkin`
- household/glass cleaning wipes: 3
- household trash bins / trash-bin+refill sets: 5
- garden hose reel: 1
- one additional dry-tissue mixed package is included in the dry-tissue count above

Official Costco URL taxonomy was decisive for polluted rows: cleaning wipes are under Cleaning Products/Cleaning Chemicals, trash bins under Household Storage, cooling sheet under Hand/Foot Care/Deodorant, and the hose reel under Patio/Lawn/Garden Hose Accessories.

## Coverage / collision checks

- No older proposal actually covering pending023 was confirmed by group-marker search.
- All **30 new source_record_keys** were searched in five batches.
- `review-decisions-input.json` hits: **0**.
- Existing 431 explicit decisions were not changed.

## Not executed

- No DB import/rebuild.
- No taxonomy code modification.
- No repository tests.
- No idempotence run.

Next canonical resume point: inspect `pending/022` then update `CURRENT_STATUS.md`.
