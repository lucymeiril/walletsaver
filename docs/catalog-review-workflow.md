# 번호로 분류하기

저장소 루트에서 실행한다. 원본 DB를 열지 않고 인증본 JSON으로 검토 목록을 만든다.

1. `py tools/catalog_review.py prepare <새묶음명> --mart <마트> --shelf '<원본 경로>'`
2. 출력된 상품을 읽고 결정한다. 같은 정확 제목·마트·경로의 여러 관측은 한 번호로 묶인다.
3. `py tools/catalog_review.py decide <묶음명> --packet-sha <출력해시> --set 'food.meals.noodles.jjolmyeon=1,3' --hold '종류 확인 필요=2'`
4. 관련 묶음 검토 후 하네스 preflight와 새 run-id의 run을 실행한다.
5. `py tools/catalog_review.py checkpoint <인증run-id> --next '<다음 행동>'`

결정은 기존 리프 ID만 허용한다. 새 리프가 필요하면 기존 taxonomy에 먼저 추가한다. 모든 번호에 분류 또는 보류가 필요하며 중복·오래된 목록·원문 변경은 거부한다. 번호는 묶음 해시와 함께 사용한다.

`services/numbered_reviews/*.json`은 검토한 규칙과 보류 근거다. 상품명·원본 ID·원문 해시는 자동으로 복사된다. 공통 검사와 하네스 코드 해시에 포함되므로 새 선반마다 Python 파일·연결 함수·검사를 작성할 필요가 없다. 새 판단 유형은 별도 의미 검사를 추가한다.

보류는 자동 분류 규칙을 만들지 않으며 이후 후보 목록에서 제외한다. 재검토하려면 해당 결정 파일의 근거를 읽고 명시적으로 수정 후 다시 인증한다. 기존 431개 결정을 대체하지 않는다.

checkpoint는 인증서·현재 코드·사본 해시를 확인한 뒤 기존 문서 두 개를 백업하고 갱신한다. 두 파일은 각각 원자적으로 교체되지만 두 파일 전체가 단일 트랜잭션은 아니다. 중단으로 불일치하면 `.debug-artifacts/checkpoint-backups/<run-id>/`와 인증서를 이용해 복구한다.
