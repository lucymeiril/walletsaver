# Handover — G2 start

Gate G1 closed at 2026-05-26T11:24:09Z.

## Evidence locations
- Code diff: `devlog\round-R\g1-codediff.md`
- DB schema/counts: `devlog\round-R\g1-db-schema.md`
- Reproduction commands: `devlog\round-R\g1-repro.md`
- Screenshot placeholder: `devlog\round-R\g1-screenshots-pending.md`
- Source reports: `devlog\round-R\g1-*-report.md`, `devlog\round-R\cocodalin-seed-report.md`

## G2 slot dispatch plan
- `g2-aggregate`: consume post-seed `products.mart_native_category_path` for emart/homeplus/lottemart/costco, aggregate raw native paths, count products per path, and export a reviewable native-path inventory.
- `g2-mapping`: use authoritative mart proposal `emart` as unified tree v1 root, map other marts' native paths to that tree, and block persistence until matching tests pass.
- `g2-web`: wire db-admin mapping UI and web category drilldown to the persisted G2 mapping output; keep G1 pass-through fields visible for operator review.

## Key G2 inputs and gate condition
- Required DB input: all 4 marts' `mart_native_category_path` rows after `g1-seed` completes.
- Authoritative-mart decision: proposal is `emart` for unified tree v1 root.
- G3 readiness: category matching test must pass before category mappings are persisted.

## Open risks
- Live seed may have skipped one or more marts; `g1-seed-report.md` was missing and DB mart counts are pending.
- Lottemart EAN-13 extraction still has edge cases around hydrated state aliases and malformed URLs.
- Homeplus EXP vs HYPER deduplication must preserve storeType while avoiding duplicate product identity collisions.

## M8 light version (non-technical)
G1에서는 네 개 마트 상품을 같은 기준으로 비교하기 위한 기본 정보(마트별 상품코드, 원본 카테고리, 단위가격, 입점셀러 여부, 가격기록 저장소)를 코드와 화면에 연결했습니다. G2에서는 실제로 수집된 각 마트의 카테고리 경로를 한 개의 공통 카테고리 나무로 맞춰서, 사용자가 물가비교 화면에서 같은 종류의 상품을 자연스럽게 비교할 수 있게 만드는 작업을 시작합니다.
