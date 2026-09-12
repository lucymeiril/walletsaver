# 재개점 — pass44

- 매번 원격 최신 [고정 입구](../handoff/README.md)와 지정된 CURRENT_STATUS.md를 먼저 확인한다.
- 최신 사본 `.debug-artifacts/initial-catalog-20260912-pass44`: 5,695적재/3,501미해결. 이번128판매상품/245관측 추가. 원본/431결정 보존, 관련636검사·DB·매칭회귀 통과. 운영 승인/공개 없음.
- 외부 `afcc97a`까지 감사. 28파일, ID연결634관측; ID없는40관측 제외. 제목/판매키 불일치6결정이 있는172-176묶음 제외. 현재 안내의 external-review.json 참조.
- 원문/ID/리프/중복은 프로그램 전량검사, 명확한 기존 분류는 묶음별 표본검사하고 오류 시 확대한다. 신규 리프·상품 병합·수량/행사·충돌은 전량검토. 표본검사를 전량 의미검증으로 보고하지 않는다.
- 결정은 중간 저장하고 여러 묶음을 모아 DB 구축·통합검사·백업한다. 작은 묶음마다 전체 자료를 재생성하지 않는다. 공통 로직 변경 때 넓은 회귀검사.
- 도구: audit_pass43_proposals.py → integrate_reviewed_chat_pass44.py(승격 선택 목록 고정, 재실행/일괄승인 금지) → prepare_initial_catalog.py → verify_initial_stage.py / verify_reviewed_runtime.py. refresh_chat_queue.py는 이전/신규 경로를 인자로 받으며 신규 제안 링크도 남긴다.
