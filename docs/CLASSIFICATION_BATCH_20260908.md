# 분류 재개 — 2026-09-08

## 곡물 개별 검토 저장 완료

- 시작점은 pass7 / 누적 199개 listing 결정 / 30개 수동 병합군이다. 원본은 `.walletsavior/admin.sqlite`이며 선택 행 해시 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 불변을 확인했다. 원본에는 쓰지 않았다.
- 곡물 제목 검색은 가공식품까지 139개를 찾으므로 그대로 분류하지 않았다. 곡물 판매 문맥의 26 listing 전체 관측과 별도 이맛쌀 20kg 1건을 읽고, 그중 21 listing/27관측을 개별 채택했다.
- 백미 7, 현미 4, 귀리 2, 찹쌀 1, 흑미 2, 병아리콩 2, 기장 1, 보리 2 listing이다. 홈플러스 7개 중 6개는 두 번 수집되었으며 27관측에 모두 보존한다.
- 찹쌀·흑미·보리·기장·병아리콩을 `식품 → 곡물·견과 → 쌀·잡곡 → 각 곡물`의 독립 리프로 추가했다. 키워드도 함께 생성한다. 새 자동 분류 규칙은 없으며 정확한 원본 ID와 모든 관측의 hash를 지정한 결정만 채택했다.
- 귀리쌀/기장쌀/보리쌀은 백미가 아니다. 찰현미는 현미다. 가루·떡·과자·차·보리새우는 이번 곡물 결정에서 제외한다. 서로 다른 판매 페이지의 상품군 병합이나 원본의 의심 브랜드(단일/귀리 등) 교정은 하지 않았다.
- 제외: 이마트 쿠폰 다운로드 문구 4개(`1000693432739`, `1000646184325`, `1000633806247`, `1000821271764`)는 가격 조건 추가 확인 필요. `1000827413348` 숙성 잡곡은 혼합 구성, `1000827413366` 돼지감자 현미는 가공/혼합 구분이 불명확해 보류. 할인혜택·건강효과를 추정하지 않는다.
- 누적 결정 `.debug-artifacts/reviewed-initial-decisions-20260908-grains.json`: 220 listing/기존 30군. SHA-256 `f585dec1517c535121dde80a84e1627e180896161a99683a36d400fcd97c44c4`.
- 전체 채택 근거 `.debug-artifacts/grain-review-20260908-evidence.json`, 작성 `.debug-artifacts/review_grains_20260908.py`, 좁은 범위 조사 `.debug-artifacts/inspect_grains_20260908.py`. 산출물은 Git 제외다.
- 분류 집중 검사 184 passed. 새 출력 `.debug-artifacts/initial-catalog-20260908-pass8/`를 검증할 예정이며 아래 완료 기록이 없으면 pass7이 마지막 검증본이다.

## pass8 검증 완료

- 상품군 2,304 / variant 2,308 / listing 2,339 / offer 3,654 / matching rule 2,283. 카테고리 252(부모 포함), 키워드 184, 원본 경로 매핑 228.
- 새 21 listing/27관측의 실제 DB 리프·독립 상품군·원본 payload/hash 전량 대조. 이전 199개 결정과 포함 관측 손실 0. 분류 코드 변경 전후 전체 9,196관측의 자동 판단이 완전히 같음을 독립 비교했다.
- 전량 accounting 9,196 = 포함 3,654 + 보류 5,542(리프 미지정 5,434). FK/integrity 및 두 번 import 멱등성 통과.
- 기존 30군 runtime/export: 92관측 88 hit/4 miss, 이름/규격/신규 ID 변경 276건은 각 경로에서 전부 miss. 검증용 snapshot pending 699개 제외, active 상태 2,955개/비활성 상품군 600개 유지. 운영 게시 없음.
- DB 관리자 전체 585 passed / 기존 경고 460개, 45.19초. 집중 검사 184개와 중복이므로 합산하지 않는다.
- bundle SHA-256 `5f2342e7e89db53e664ce0b3ae84e043cc86dbbe26ee50e57e543203b59873db`. 독립 근거는 pass8의 `grain-independent-check.json`, `reviewed-runtime-check.json`, `public-snapshot-rehearsal.sqlite`.
