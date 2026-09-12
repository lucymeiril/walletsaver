# WalletSaver 작업 재개 — 현재 입구

1. [현재 상태](CURRENT_STATUS.md)를 읽는다.
2. [남은 작업](REMAINING.md)에서 묶음을 고르고 `remaining/<기존ID>/*.json` **전부**를 읽는다. 큰 압축파일이나 과거 체크포인트 전체를 다시 읽지 않는다.
3. [현재 카테고리](taxonomy.json)를 사용한다. 이것은 코드가 지원하는 전체 노드/리프 목록이다. **pass41 공개용 데이터에 없다고 코드에도 없는 것이 아니다.**
4. 기존 제안이 있으면 `proposal_references`를 확인해 보완한다. 옛 제안은 `../2026-09-11/proposals/`에 남아 있다. 코드에 반영된 것은 [accepted.json](accepted.json)으로 구별한다.
5. 새 판단은 `proposals/<batch>.json` 하나에, 진행 상태는 `CURRENT_STATUS.md` 하나에만 기록한다. 묶음마다 checkpoint/PROGRESS/누계 문서를 새로 만들지 않는다.

## 결과 형식과 근거

```json
{"status":"proposal_only","baseline_pass":"pass42","decisions":[{"raw_record_ids":["실제 ingestion:ID:index"],"source_name":"homeplus","source_record_key":"원본 키","source_title":"원문 그대로","decision":"existing_leaf","unified_category_id":"taxonomy.json의 리프","reason":"상품 형태를 확인한 근거","evidence_urls":[],"quantity_review":"unchanged","identity_merge":"not_requested"}],"executed_tests":[]}
```

- `decision`은 `existing_leaf`, `new_leaf_needed`, `hold`, `already_classified` 중 하나. 뒤의 세 경우 `unified_category_id`는 null이고, 새 리프 후보는 `suggested_new_leaf`에 적는다. 제목·판매페이지가 같은 반복관측은 모든 raw ID를 한 결정에 묶는다.
- **묶음번호+행 개수+규칙 요약만으로 완료 처리하지 않는다.** 원문 ID가 없으면 재적용/중복 검사할 수 없다. 검사/완료 숫자를 손으로 누적하지 않는다.
- 원본 제목을 줄여 쓰지 않는다. 다른 크기·포장형태 제품의 검색 결과로 확인했다고 하지 않는다. 외부 근거를 썼으면 해당 정확한 상품 URL과 확인 내용을 적는다.
- '카레'만으로 가루/고형/즉석을, '찌개용 채소'만으로 냉동을, '스팸'만으로 캔/파우치를 확정하지 않는다. 품목과 제조·포장형태를 분리해 생각한다.
- 기존 source/title 후보와 충돌하면 그 사실도 기록한다. 제안을 만들었다고 기존 단위/행사/이름변경 안전장치를 해제하지 않는다.
- 상품군→규격→판매페이지→시점별 offer 구분, 최대4단계 카테고리의 리프 하나만 귀속, 정확한 이름·규격·검증 alias 매칭은 그대로 유지한다. 1+1/2+1은 받는 총량과 총지출로 비교하되 불명확한 조건은 계산하지 않는다.
- DB/테스트를 실행할 도구가 없다면 제안만 저장한다. `executed_tests`는 빈 배열. 상품이름/수량/원본파일은 변경하지 않고 계정/키는 올리지 않는다. 직접 운영 승인·공개는 하지 않는다.

## 무엇이 실제로 반영됐나

[평가 보고서](EVALUATION.md), [승인·보류 ID](accepted.json), [형식 문제](flagged-proposals.json) 참고. **전체 제안에 합격 판정을 내린 것이 아니다.** 아직 검증되지 않은 분류 제안과 근거가 모자란 보류가 많이 남았다. 범위019~451을 읽었다는 옛 문서 수치를 완료율로 사용하지 않는다.

새 DB는 `archives/staging.sqlite.gz`, bundle은 `archives/catalog-bundle.json.gz`. 원본108수집/9,196관측과431결정은 `../2026-09-11/`의 동결 원본을 재사용한다. 계정DB/비밀키는 없다. 남은 목록에는 새로 적재된71관측을 제외했고, 분류 승인됐지만 다른 검사에 걸린6관측은 `accepted_but_blocked`로 표시했다.

실행 가능 환경에서는 저장소 루트에서 다음을 사용한다. Python/패키지 설치는 이전 [복원 안내](../2026-09-11/history/README-pass41.md)의 실행 절을 참고한다.

```powershell
py tools/restore_chat_handoff.py --out .debug-artifacts/source-for-next
py tools/prepare_initial_catalog.py --db .debug-artifacts/source-for-next/source-pending.sqlite --out .debug-artifacts/initial-catalog-NEXT --run-id initial-catalog-NEXT --review-decisions handoff/2026-09-11/review-decisions-input.json
py tools/verify_initial_stage.py initial-catalog-NEXT
py -m pytest packages/db-admin/backend/tests/test_initial_reviewed_chat.py packages/db-admin/backend/tests/test_initial_taxonomy.py -q --disable-warnings
```

NEXT는 새로운 이름으로 바꾼다. 현재 코드를 실행하므로 원본을 pass41 폴더에서 복원해도 승인된 새 분류가 적용된다. 관련 테스트만 실행하고 공통 매칭·가격 코드 수정 시 넓은 회귀 검사를 한다. `tools/audit_chat_proposals.py`는 구형 제안들의 구조 검사이지 자동 승인기가 아니다.
