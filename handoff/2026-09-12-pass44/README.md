# 초기 분류 작업 — pass44

## 재개와 저장

1. 원격 최신 [고정 입구](../README.md)와 [현재 상태](CURRENT_STATUS.md)를 읽는다. `REMAINING.md`는 미적재 목록이지 미검토 목록이 아니다. `remaining/<ID>/*.json` 전부, `proposal_references`, 현재/이전 proposals를 확인해 중복 작업을 피한다.
2. 시작 전에 현재 상태에 작업 ID·기준 commit·범위·결과 파일·상태를 **한 줄**로 예약한다. 겹치는 예약은 피한다. 묶음 완료마다 JSON을 먼저 저장하고 같은 줄의 다음 시작점을 갱신한다. 새 체크포인트나 장문 진행 보고서를 만들지 않는다.
3. 공유 파일을 쓰기 직전에 최신 원격 내용을 다시 읽고 다른 기록을 보존한다. 동일 원본 ID의 판단이 다르면 덮어쓰지 말고 충돌 보류한다. 안전한 병합이 불가능하면 중단 사유를 보고한다. 가능하면 결과+상태를 한 commit으로 저장하며 강제 push는 하지 않는다.

## 결과 형식 — 바꾸지 말 것

작업당 `proposals/<작업ID>.json` 하나, **최상위 decisions 배열**만 사용한다. groups/items/group_reviews로 중첩하거나 raw_record_ids를 생략하지 않는다. 원본 ID마다 상품명·판매키·마트가 모두 원본과 일치해야 한다. 관측이 여러 개면 각각 대조한다. 누락 필드는 추측하지 않는다.

```json
{"status":"proposal_only","baseline_pass":"pass44","baseline_commit":"실제 SHA","decisions":[{"raw_record_ids":["실제 ID"],"source_name":"homeplus","source_record_key":"원본 키","source_title":"원문 그대로","decision":"existing_leaf","review_lane":"clear_existing","unified_category_id":"실제 리프","reason":"짧은 제품형태 근거","evidence_urls":[],"quantity_review":"unchanged","identity_merge":"not_requested"}],"executed_tests":[]}
```

- `decision`: existing_leaf / new_leaf_needed / hold / already_classified. 뒤의 세 경우 리프는 null, 새 후보는 suggested_new_leaf. `review_lane`: clear_existing / needs_review. 신규 리프·상품 병합·용량/할인·충돌은 needs_review.
- 중복 제안 대신 기존 파일 보완+수정 이유를 남긴다. 제안에는 상품별 근거를, 상태에는 파일 링크와 다음 지점만 쓴다. **누적 건수·완료율은 손으로 더하지 않는다.** 계산 도구가 없으면 범위·파일만 보고한다. ‘제안 완료’와 ‘DB 반영 완료’를 구분한다.

## 분류 기준과 범위

- [taxonomy.json](taxonomy.json)은 전체 코드 카테고리, [accepted.json](accepted.json)은 반영 근거다. 리프 하나, 최대4단계. 상품군→규격→판매페이지→시점별 가격은 구분한다. 이름·규격이 다른 상품을 임의로 합치지 않는다.
- 진열명만으로 제품형태를 확정하지 않는다. ‘가장 비슷한 리프’로 밀어 넣지 않는다. 생크림/휘핑크림, 찐만두/일반만두, 주방 살균세정제/기름때세정제, 포장 과일/잘라낸 과일처럼 형태가 불명확하면 근거를 찾거나 보류한다. 실제 기존 검사 충돌도 보존한다.
- 분류 작업은 원본 수량·가격·행사와 기존431결정을 바꾸지 않는다. 1+1/2+1은 받는 총량·총지출에 반영하되 모호한 조건은 추측하지 않는다. 실행하지 않은 검사/DB 반영을 완료로 쓰지 않는다. 운영 승인·공개·비밀키 업로드 금지.
- 제안 작성자는 REMAINING/accepted/archives와 DB 실적을 갱신하지 않는다. 통합 담당자가 여러 묶음을 모아 검증·백업·목록 갱신한다. 단순 기존 분류는 표본 검토할 수 있지만 작성자의 자가 승인으로 반영하지 않는다.

원본/431결정은 `../2026-09-11/`의 동결 자료, 최신 검토 DB는 이 폴더 archives. 이전 제안은 `../2026-09-11/proposals/`와 `../2026-09-12-pass43/proposals/`에 보존되어 있다. 새 제안은 이 폴더 proposals에 저장한다.
