# 분류·매칭 재개 — 2026-09-03

강제 중단에 대비한 작은 작업 단위 기록이다. 운영 DB 승인 기록이 아니다.

## 기준

- 원본 `.walletsavior/admin.sqlite`는 읽기 전용으로만 사용한다. 수집·마이그레이션·운영 import·승인·공개는 실행하지 않는다.
- 시작 시 git clean, HEAD `53642d9`, 기존 8개 커밋 원격 push 완료.
- 검증 완료 기준은 `.debug-artifacts/initial-catalog-20260903-pass4/`.
- 누적 검토 결정은 `.debug-artifacts/reviewed-initial-decisions-20260903-produce.json`의 71 listing, 12 상품군 병합이다.
- 원본 선택 행 SHA-256: `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0`.

## 진행 중

1. root: 기존 과일·채소 조사에서 남은 작은 품목군의 모든 원본 관측을 재확인하고, 근거가 충분한 listing에만 리프 결정을 추가한다.
2. `matching_review_batch`: 기존 119개 마트 간 후보 중 미검토 최대 10군의 독립 조사. 결과는 제안만이며 root가 원본을 재검토하기 전 반영하지 않는다.
3. 누적 결정을 보존한 새 폴더로 workspace 생성 → 두 번 import 멱등성 → 독립 SQL/evidence 검증 후 이 문서에 최신 경로·해시·건수를 갱신한다.

생성 JSON/SQLite/HTML과 실제 크롤링 데이터는 Git 제외다. 재개 시 파일 존재만으로 완료로 간주하지 않고 검증 결과를 확인한다.

## 저장 완료: 과일·채소 32 listing 검토

- `.debug-artifacts/review_produce_batch2.py`에 개별 ID와 이유를 저장했다. 같은 listing의 모든 관측(베스트/유기농 포함)을 대조했다.
- 새 누적 문서: `.debug-artifacts/reviewed-initial-decisions-20260903-produce-batch2.json`, 103 listing 결정(기존 71개 유지).
- 누적 문서 SHA-256: `32b4dfeeec86d35815de400687f5ed22ff662fe26f32305873634db158b516b2`.
- 아보카도·망고·대추·대파·배추·건채소·건버섯·냉동채소의 8개 검토 전용 리프를 추가했다. 부모 포함 4단계, 키워드 충돌 없음. 기존 건과일·양배추·콩나물/숙주 리프도 개별 지정했다.
- 넓은 제목 자동분류 규칙은 추가하지 않는다. 혼합 과일 선물·불명확 망고청크·행사 카드·동물용 간식은 대상에서 제외했다.
- taxonomy/workspace 집중 테스트: 180 passed. 새 fixture의 배추김치는 기존 김치 분류가 정당하여, 코드를 바꾸지 않고 기대값을 해당 기존 계약으로 고쳤다.
- 실제 최소구매 제목 누락과 다중곱 `400g x 3 x 2`의 부분 규격 해석 문제가 발견되어 별도 좁은 guard 수정 중이다. 리프 결정은 가격/규격 승인과 다르며 이 수정 검증 전 새 stage를 기준으로 쓰지 않는다.

## 저장 완료: 9개 추가 상품군 병합 결정

- 별도 agent의 10군/21 listing/27관측 제안을 root가 읽고 실제 read-only 원본에서 ID·전체 관측 해시·제목·브랜드·규격·경로를 다시 대조했다.
- 9군/19 listing을 채택했다: 비비고 갈비탕·도가니곰탕·두부듬뿍된장찌개·사골곰탕·저나트륨사골곰탕, 소와나무 체다치즈, 백설 포도씨유, 스타벅스 셀렉트 카페라떼, 해찬들 고기전용쌈장.
- 일반/저나트륨 사골곰탕은 별도 상품군. 체다치즈는 3사 동일 270g 단품이며 포장/맛을 확장하지 않는다. 범용 브랜드 alias나 이름 유사도 자동 병합 규칙을 만들지 않았다.
- 맥콜 제로는 롯데의 콜라 분류가 합당하지 않아 보류. 찌개는 기존 `soup_stew` 의미를 유지하되 표시명을 `국·탕·찌개`로 바로잡았다(원본 매핑 규칙 확장 없음).
- 최신 누적 122 listing 결정: `.debug-artifacts/reviewed-initial-decisions-20260903-batch2.json`.
- SHA-256: `db6926e36cb942dfb0159f59008b3c734b8d318f4e7c95dac35477d144b7a7f4`.
- root 검증/작성 스크립트: `.debug-artifacts/accept_matching_batch2.py`. 생성 대상은 `initial-catalog-20260903-pass5`이며 검증 완료 여부는 아래 최신 결과를 확인한다.

## pass5 검증 완료 및 2026-09-05 재개

- 최신 검증본은 `.debug-artifacts/initial-catalog-20260903-pass5/`. 원본 선택 행 해시 불변, 전체 9,196관측 accounting/FK/integrity/2회 import 멱등성 통과.
- 상품군/variant 2,243, listing 2,265, offer 3,572, matching rule 2,204. 카테고리 242(부모 포함), 키워드 174, 경로 매핑 222.
- 비교 가능한 offer 2,873, 프로모션 검수 699, 미분류·규격 보류 5,624(리프 미지정 5,521). 수동 병합은 정확히 21군이며 검토 문서와 DB의 listing 구성 일치를 검증했다.
- 새로 33관측을 적재하고, 기존 다중곱 부분 해석 13관측을 보류하여 순증 20관측이다. 전체 자동분류 판정 9,196개는 이전 코드와 동일하므로 이 변화는 개별 검토 결정과 규격 guard에서 발생했다.
- 최소구매 제목은 bundle 조건과 DB 원문 evidence에 보존된다. DB에는 별도의 `promotion_conditions` 열이 없으며 원문/검수 이유를 저장한다. 목이버섯은 pending이고 단위가격은 null. 다진마늘 반복곱·콩나물 혼합중량은 listing/offer가 생성되지 않았다.
- 검증용 snapshot: pending 699개 제외, 비교 가능 2,873개/비활성 상품군 612개 유지, FK 0, stage 해시 불변. 게시하지 않았다.
- 2026-09-03 DB 관리자 전체 574 passed (기존 경고 460). 2026-09-05 저장된 실제 원본으로 runtime/enrichment와 export를 추가 확인: 21군/61관측 중 원본 hit 57, 미활성 가족 등의 miss 4; 이름변경/신규 ID/규격변경 183건이 각 경로에서 전부 miss. stage 해시 불변.
- 독립 검증 파일: `batch2-independent-check.json`, `reviewed-runtime-check.json`; 스크립트 `.debug-artifacts/verify_initial_stage.py`, `verify_classification_batch2.py`, `verify_reviewed_runtime.py`.
- seed의 다중곱 검수는 완료. 공유 parser/runtime 자체의 다중곱 해석은 후속 계약 정리 대상이다. 이번 stage에는 해당 규격의 matching rule이 없다.
- 재생성 시 누적 문서 `reviewed-initial-decisions-20260903-batch2.json`을 사용하고 기존 폴더는 덮어쓰지 않는다.
