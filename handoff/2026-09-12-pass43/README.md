# 최신 작업 입구 — pass43

1. [현재 상태](CURRENT_STATUS.md)와 [남은 목록](REMAINING.md)을 읽는다. 현재 미해결은 3,746관측이다.
2. 분류 원칙과 제안 형식은 [기존 안내](../2026-09-12/README.md)의 ‘결과 형식과 근거’를 그대로 따른다. 그 문서의 pass42 숫자와 잔여 경로는 과거 기준이다.
3. 작업 대상은 이 폴더의 `remaining/<ID>/*.json`, 카테고리는 [taxonomy.json](taxonomy.json), 반영 여부는 [accepted.json](accepted.json)이다. 원본 제안은 `../2026-09-11/proposals/`에 있으며 `proposal_references`로 연결된다.
4. 새 제안은 `proposals/<batch>.json` 하나에 기록한다. 상태는 이 폴더의 CURRENT_STATUS.md 하나만 갱신한다. 과거 파일은 이력이며 누계를 합산하지 않는다.

원본은 `../2026-09-11/archives/source-pending.sqlite.gz`, 431개 수동 결정은 `../2026-09-11/review-decisions-input.json` 그대로다. 최신 검토 DB와 bundle은 이 폴더의 archives에 있다. 운영 승인·공개는 하지 않았다.

실행 가능한 환경에서 원본을 이전 복원 도구로 새 폴더에 복원한 뒤, 현재 코드로 `prepare_initial_catalog.py --db <복원한 원본> --out <새 작업 폴더> --run-id <새 이름> --review-decisions handoff/2026-09-11/review-decisions-input.json`을 실행한다. 관련 테스트만 우선 실행한다.
