# 최신 작업 입구 — pass43

> 현재 지침·미적재 목록은 [고정 입구](../README.md)를 따른다. 아래는 pass43 이력이며 현재 지침에 중복해서 적용하지 않는다.

## 매 세션의 작업 순서

1. 원격 최신 [고정 시작점](../README.md)과 [현재 상태](CURRENT_STATUS.md)를 읽는다. 기준 commit SHA를 기록하고 ‘제안 작업 인계’에서 진행 중 범위·결과 파일을 확인한다.
2. [남은 목록](REMAINING.md)에서 범위를 고른다. 해당 `remaining/<ID>/*.json` 전부와 `proposal_references`, 현재 `proposals/` 및 인계에 적힌 결과 파일을 대조한다. remaining은 **미적재 목록이지 미검토 목록이 아니다.** 이미 제안된 원본 ID는 새로 분류하지 말고 필요한 근거만 보완한다.
3. 시작 전에 CURRENT_STATUS.md의 ‘제안 작업 인계’에 작업 ID(날짜+짧은 고유 이름), 기준 SHA, 대상 묶음/원본 ID 범위, `진행 중`, 결과 경로를 저장한다. 다른 작업과 겹치면 다른 범위를 고른다. 오래된 진행 중 표시도 완료로 추정하지 말고 실제 파일을 확인한다.
4. 한 묶음을 마칠 때마다 결과 JSON을 먼저 저장하고, 인계의 처리 범위·다음 시작점·보류를 갱신한다. 중단되어도 저장된 결과부터 재개한다. 결과 저장 실패 시 완료로 표시하지 않는다. 가능하면 결과와 상태를 한 commit으로 저장한다.
5. **공유 문서를 쓰기 직전에 원격 최신 내용을 다시 읽는다.** 기준 이후 변경이 있으면 다른 기록을 보존해 병합한다. 같은 원본 ID의 판단이 다르면 양쪽 근거를 남기고 충돌 보류한다. 최신 내용 확인/안전한 병합이 불가능하면 덮어쓰지 말고 중단 사유를 보고한다. 강제 push 금지. 이 절차는 동시 작업 잠금을 보장하지 않는다.

## 제출과 분류 원칙

- 현재 카테고리는 [taxonomy.json](taxonomy.json), 실제 반영 여부는 [accepted.json](accepted.json)이다. 원본 제안은 `../2026-09-11/proposals/`에도 있다. 사용 중인 카테고리만 담긴 옛 snapshot을 전체 카테고리로 오해하지 않는다.
- 작업당 `proposals/<작업ID>.json` 하나. 원본 ID·정확한 제목·기존 리프·짧은 근거를 필수로 적는다. 명확한 기존 분류와 신규 리프/충돌/용량/할인 문제는 `review_lane`으로 분리한다. 기존 제안 보완은 원본 파일과 수정 이유를 남기고, 중복 결정은 만들지 않는다.
- 상품군→규격→판매페이지→시점별 가격은 구분한다. 카테고리는 최대4단계의 리프 하나만 지정한다. 진열명만으로 제품형태를 확정하거나 이름·규격이 다른 상품을 합치지 않는다. 1+1/2+1은 받는 총량과 총지출에 반영하지만 불명확한 조건은 추측하지 않는다. 분류만 하는 작업에서는 원본 수량·가격·행사와 기존431결정을 바꾸지 않는다.
- 제안은 `proposal_only`다. 실제 실행하지 않은 DB 반영·검사는 완료로 적지 않는다. 운영 승인/공개·계정/비밀키 업로드 금지. 새 카테고리·상품 합치기·용량/할인·충돌은 전량 검토 대상이며, 명확한 분류도 작성자의 자가 승인으로 반영되지 않는다.
- 별도 PROGRESS/체크포인트/장문 보고서는 만들지 않는다. 인계에는 파일 링크·처리 범위·다음 시작점만 남긴다. DB 적재 누계와 REMAINING/accepted/archives는 **실제 통합 검증 후 담당자만 갱신**하고 제안 수를 빼지 않는다.

```json
{"status":"proposal_only","baseline_pass":"pass43","baseline_commit":"실제 SHA","decisions":[{"raw_record_ids":["실제 ID"],"source_name":"homeplus","source_record_key":"원본 키","source_title":"원문 그대로","decision":"existing_leaf","review_lane":"clear_existing","unified_category_id":"실제 리프","reason":"짧은 제품형태 근거","evidence_urls":[],"quantity_review":"unchanged","identity_merge":"not_requested"}],"executed_tests":[]}
```

`decision`: existing_leaf / new_leaf_needed / hold / already_classified. 뒤의 세 경우 리프는 null, 새 후보는 suggested_new_leaf에 기록한다. `review_lane`: clear_existing / needs_review. 외부 근거는 정확한 상품 URL과 확인 내용을 적는다.

원본은 `../2026-09-11/archives/source-pending.sqlite.gz`, 431개 수동 결정은 `../2026-09-11/review-decisions-input.json` 그대로다. 최신 검토 DB와 bundle은 이 폴더의 archives에 있다. 운영 승인·공개는 하지 않았다.

실행 가능한 환경에서 원본을 이전 복원 도구로 새 폴더에 복원한 뒤, 현재 코드로 `prepare_initial_catalog.py --db <복원한 원본> --out <새 작업 폴더> --run-id <새 이름> --review-decisions handoff/2026-09-11/review-decisions-input.json`을 실행한다. 관련 테스트만 우선 실행한다.
