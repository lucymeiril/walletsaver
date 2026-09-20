# 짧은 위탁 호출

현재 운영(2026-09-21): 새 미처리 묶음으로 Luna high → Sol medium을 사용한다. 동일 묶음 반복 벤치마크는 하지 않는다. 지침 수정은 새 작업에서 적용하고 검증된 결과를 적재한다. high도 지나치게 느리면 다음 새 묶음에서 medium을 시험한다. 기존 max 실험은 과거 기록이며 현재 기본값이 아니다.

프로필: `.codex/agents/catalog_classifier.toml` (Sol low). 예외 검토 프로필은 독립 의견이 필요할 때만 호출한다. 매 묶음마다 두 명을 쓰지 않는다. 반영·해시·번호검증·문서 갱신은 기존 스크립트가 담당한다.

분류 작업 JSON: `{"leaves":{"리프ID":"이름"},"packets":[{"name":"묶음명","path":"입력 JSON 경로","sha256":"입력 해시","output":".debug-artifacts/review-proposals/묶음명.json"}],"constraints":[]}`. 여러 packet이 같은 리프 목록을 한 번만 공유한다.
입력은 현재 prepare 결과, 리프는 현재 taxonomy에서 추출한다. 동일 작업 JSON에 관련 선반 여러 개를 넣는다. 원문을 다시 작성하지 않는다.

호출문: `catalog_classifier로 <작업 JSON 경로> 처리.`
작업 파일 생성: `py tools/catalog_job.py <작업명> --packet <묶음명> --leaf-prefix <리프접두사> --leaf <정확리프ID>` (세 옵션은 반복 가능, 리프 옵션은 둘 중 하나 이상). 기존 packet/현재 taxonomy에서 해시와 리프를 복사하며 오래된 packet·중복·출력 덮어쓰기는 거부한다. 오염 선반에서 제목상 예상되는 다른 분류는 정확 리프만 추가해 전체 taxonomy 전송을 피한다.
2026-09-21 비교 시험: 분류 호출은 `gpt-5.6-luna/max`, 검수 호출은 `gpt-5.6-sol/medium`, 둘 다 `fork_turns=none`. 검수는 `.codex/agents/catalog_duo_reviewer.toml`을 읽고 같은 job의 모든 배정/보류를 확인하여 별도 report만 쓴다. 상위 에이전트는 보고서 입력 해시를 확인한 뒤 반영한다. 이 조합이 검증되기 전 기본 프로필을 교체하거나 전량 무감독 처리하지 않는다.
이 세션의 spawn 도구에는 custom-role 선택 인자가 없다. 자동 로딩을 확인하지 못했으면 `model=gpt-5.6-sol`, `reasoning_effort=low`, `fork_turns=none`을 명시하고 `Read .codex/agents/catalog_classifier.toml and follow developer_instructions. Job: <경로>`로 호출한다. 프로필을 작성했다고 현재 실행 도구에 등록됐다고 주장하지 않는다. 기존 에이전트에는 첫 프로필 로드 후 job 경로만 전달하되 지침 변경 시 다시 읽게 한다.

부모: proposal dry-run 요약 검토 → 같은 해시로 --apply → 여러 묶음을 모아 하네스 1회 → checkpoint. 실패 시 실패 단계만 읽는다. 제안 설명·번호 명령·원본 JSON을 다시 쓰지 않는다.

출력 예산: 진행 알림은 의미 있는 변화만 1~2문장, 최종은 추가 상품/관측·미해결·검증/원본보존·커밋/다음 작업 최대 5줄. 오류 설명에 필요한 경우는 예외. 매번 평가 문서를 덧붙이지 않고 새 오류 유형이 생겼을 때만 지침을 갱신한다.

파일 지침도 읽으면 입력 토큰이 든다. 짧은 호출은 반복 출력과 이력 전달을 줄이는 장치이지 무료 입력이나 절감률 보장이 아니다. 프로젝트 프로필 형식은 [공식 문서](https://learn.chatgpt.com/docs/agent-configuration/subagents) 기준이며 실제 로딩/권한은 클라이언트에서 별도 확인한다.
