# 초기 분류 작업 — pass45

1. 매 세션 원격 최신 [고정 입구](../README.md)와 [현재 상태](CURRENT_STATUS.md)를 읽는다. 기존 진행 중 예약은 완료로 추측하지 않는다. 쓰기 직전 다시 읽고 다른 작업을 보존한다. 충돌 시 덮어쓰기/강제 push 대신 보류한다.
2. 대상은 `remaining/<ID>/*.json` 전부. **이미 적재된 ID의 과거 형식 정리는 별도 요청이 없으면 하지 않는다.** remaining은 미적재이지 미검토가 아니다. proposal_references와 이전 proposals를 재사용한다. 원본 ID·판매키·마트·제목을 각각 정확히 대조한다.
3. CURRENT_STATUS에는 `작업ID / 기준SHA / 범위 / 진행 중·제안 완료·보류 / 결과파일 / 다음 지점` 한 줄만 기록한다. 결과 JSON을 먼저 저장하고 다음 지점을 갱신한다. 상품별 설명은 JSON에만 쓴다. 별도 진행문서·장문 요약 금지.
4. 진척도는 고정된 원본 집합의 **고유 ID**로 계산한다. 계산 도구가 없으면 이번 파일/범위만 보고하고 전체 비율은 미산출로 표시한다. `existing_leaf`라고 DB-ready가 아니다. 단위·행사·분류충돌 검사까지 실행하지 않았다면 ‘기존 리프 제안’이라 부르고, 실제 적재 수는 통합 담당자의 검증 수치만 사용한다.

## 제출 형식

작업당 `proposals/<작업ID>.json` 하나, 최상위 decisions 배열. groups/items로 중첩하거나 필수 필드를 생략하지 않는다. 기존 제안을 보완하면 변경 사유를 남긴다. 대체 표시에는 정확한 대체 파일과 대상 raw_record_ids를 남겨 연결이 끊기지 않게 한다.

```json
{"status":"proposal_only","baseline_pass":"pass45","baseline_commit":"실제 SHA","decisions":[{"raw_record_ids":["실제 ID"],"source_name":"homeplus","source_record_key":"원본 키","source_title":"원문 그대로","decision":"existing_leaf","review_lane":"clear_existing","unified_category_id":"실제 리프","reason":"짧은 제품형태 근거","evidence_urls":[],"quantity_review":"unchanged","identity_merge":"not_requested"}],"executed_tests":[]}
```

decision은 existing_leaf / new_leaf_needed / hold / already_classified. 뒤 세 경우 리프는 null, 새 후보는 suggested_new_leaf. 신규리프·상품합치기·용량/할인·충돌은 needs_review, 명확한 기존분류만 clear_existing. 기존 안전검사는 그대로 보존한다.

## 기준

- taxonomy.json은 전체 코드 분류, accepted.json은 통합 검토 근거이며 미적재 승인근거도 포함한다. 실제 반영 여부는 remaining과 최신 실적을 확인한다. 최대4단계 리프 하나, 상품군→규격→판매페이지→시점별 가격을 구분한다. 제목/규격이 다른 상품을 임의 병합하지 않는다.
- 진열명이나 ‘가장 비슷한 분류’로 형태를 확정하지 않는다. 메밀국수≠냉면, 일반만두≠찐만두. 어종·가공형태·주스/과즙음료 등 모호하면 정확한 상품 근거를 찾거나 보류한다.
- 원본 가격·수량·행사/기존431결정은 변경하지 않는다. 1+1/2+1의 받는 총량·총지출은 반영하되 모호한 조건은 추측하지 않는다. 수행하지 않은 검사·DB 반영을 완료로 보고하지 않는다. 운영 승인/공개·비밀키 업로드 금지.
- 제안 작성자는 REMAINING/accepted/archives를 고치지 않는다. 통합 담당자가 여러 묶음을 모아 검사·백업·갱신한다. 명확한 기존분류의 의미검증은 표본일 수 있으나 작성자 자가승인으로 반영되지 않는다.

원본/431결정은 `../2026-09-11/`, 이전 제안은 그 폴더와 `../2026-09-12-pass43/proposals/`, `../2026-09-12-pass44/proposals/`에 있다. 이번 archives가 최신 사본이며 운영 DB가 아니다.
