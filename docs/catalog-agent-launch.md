# 짧은 위탁 호출

프로필: `.codex/agents/catalog_classifier.toml` (Sol low). 예외 검토 프로필은 독립 의견이 필요할 때만 호출한다. 매 묶음마다 두 명을 쓰지 않는다. 반영·해시·번호검증·문서 갱신은 기존 스크립트가 담당한다.

분류 작업 JSON: `{"packets":[{"name":"묶음명","path":"입력 JSON 경로","sha256":"입력 해시","output":".debug-artifacts/review-proposals/묶음명.json","leaves":{"리프ID":"이름"}}],"constraints":[]}`.
입력은 현재 prepare 결과, 리프는 현재 taxonomy에서 추출한다. 동일 작업 JSON에 관련 선반 여러 개를 넣는다. 원문을 다시 작성하지 않는다.

호출문: `catalog_classifier로 <작업 JSON 경로> 처리.`
이 세션의 spawn 도구에는 custom-role 선택 인자가 없다. 자동 로딩을 확인하지 못했으면 `model=gpt-5.6-sol`, `reasoning_effort=low`, `fork_turns=none`을 명시하고 `Read .codex/agents/catalog_classifier.toml and follow developer_instructions. Job: <경로>`로 호출한다. 프로필을 작성했다고 현재 실행 도구에 등록됐다고 주장하지 않는다. 기존 에이전트에는 첫 프로필 로드 후 job 경로만 전달하되 지침 변경 시 다시 읽게 한다.

부모: proposal dry-run 요약 검토 → 같은 해시로 --apply → 여러 묶음을 모아 하네스 1회 → checkpoint. 실패 시 실패 단계만 읽는다. 제안 설명·번호 명령·원본 JSON을 다시 쓰지 않는다.

출력 예산: 진행 알림은 의미 있는 변화만 1~2문장, 최종은 추가 상품/관측·미해결·검증/원본보존·커밋/다음 작업 최대 5줄. 오류 설명에 필요한 경우는 예외. 매번 평가 문서를 덧붙이지 않고 새 오류 유형이 생겼을 때만 지침을 갱신한다.

파일 지침도 읽으면 입력 토큰이 든다. 짧은 호출은 반복 출력과 이력 전달을 줄이는 장치이지 무료 입력이나 절감률 보장이 아니다. 프로젝트 프로필 형식은 [공식 문서](https://learn.chatgpt.com/docs/agent-configuration/subagents) 기준이며 실제 로딩/권한은 클라이언트에서 별도 확인한다.
