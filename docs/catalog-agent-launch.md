# 분류와 실행 위탁

현재 효율 시험: 고정 `catalog_classifier` (Sol low) → `catalog_duo_reviewer` (Sol medium). 이전 Luna high 시험과 구분한다. `fork_turns=none`, 호출문은 job/report 경로만 사용한다. 지침 변경 직후에는 프로필 재읽기도 명시한다. 등록된 역할은 실제 도구에서 확인한다.

분류 job은 40–100개 후보와 관련 리프 목록 하나를 공유한다. 관련 job을 합쳐 150–300개 검토 후 인증 1회가 목표이며 크기를 강제하지 않는다.

1. `catalog_review.py shelves/prepare`로 새 후보를 만든다. prepare 출력은 로그로 보낸다.
2. `catalog_job.py <name> --packet <name> --leaf-prefix <prefix>`로 문맥을 공유한다. 반복 가능한 `--leaf`로 필요한 예외 리프를 보충한다.
3. 분류자는 번호별 배정/보류만, 검수자는 변경점과 입력 해시만 쓴다. 제목과 구체적 경로를 함께 판단한다.
4. `py tools/catalog_batch.py inspect --job <job> --save <new-manifest>`로 전체 형식·해시·적용 가능성을 확인한다. manifest는 의미 검토나 승인서가 아니다.
5. 부모 의미 검토 후 `py tools/catalog_batch.py apply --job <job> --manifest <manifest>`로 규칙을 생성한다. 원본 제안을 보존한다. 사전 검증은 전체에 적용하지만 다중 파일 쓰기는 원자적이지 않다. 중단 시 생성 파일을 확인한다.
6. 관련 묶음의 새 리프·충돌 해결 후 preflight → 새 run-id 인증 → checkpoint. 보류만 늘린 묶음마다 인증하지 않는다.

실행 위탁은 worker에 정확한 명령·작업 디렉터리·로그 위치·쓰기 허용 파일을 지정한다. 성공은 요약 수치와 로그 경로, 실패는 단계·짧은 원인만 반환한다. 판단 변경, 테스트 삭제, 승인·공개·Git·원본 DB 작업 권한은 없다.

보류는 `new leaf: 구체적 형태`, `evidence: 필요한 정보`, `quantity: 이유`, `non-product: 이유`로 구분한다. 없는 리프가 반복되면 부모가 트리를 보완한다. 보류를 완료 실적으로 세지 않는다.

측정은 호출 수, 출력 크기, 검토/확정 제목 수, 실제 상품/관측 증가로 한다. 이를 토큰·할당량 절감률로 환산하지 않는다. 전체 이력이나 taxonomy를 반복 전달하지 않는다.
