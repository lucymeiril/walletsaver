# 재개 체크포인트 — 2026-09-08

## 최신 pass41 — 이마트 채소·친환경 진열 (2026-09-10)

- 최신 `.debug-artifacts/initial-catalog-20260910-pass41`. `initial_audited_emart_produce.py`에 정확한 제목38개 분류표. 채소/친환경·유기농/과일/쌀·잡곡 진열만 허용. 유기농 진열의 돼지고기/잼/주스 등도 실제 식품 형태로 구분. 새 리프 부추·데친나물. 범위중량/혼합쌈/형태불명 샐러드 미확정 유지.
- 전체 비교38관측/38제목 None→리프, 기존 분류 불변. 최종36관측 추가. 깻잎20장×2입/25g×2는 수량 충돌로 보류. 최종 상품군3,386 / variant3,416 / listing3,536 / offer5,280 / 규칙3,463 / 카테고리463 / 키워드377 / 경로매핑255. 보류3,916(리프미정3,694), active4,527 / pending753.
- 누적 결정 입력 기존 `reviewed-initial-decisions-20260908-remaining-exact.json`431개 유지, 원본 SHA c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 불변. 원본/운영 DB 수정·승인·공개 없음.
- 관련 produce/taxonomy433 passed(0.92초), 생성검증/멱등 import/독립 stage 검사. 전체 관리자·snapshot·runtime·API 반복 미실행. 감사 스크립트가 원래 homeplus만 허용해 첫 실행 실패; 기대 마트를 인수로 명시하도록 바꾸고 `py .debug-artifacts/audit_cold_pass36.py 40f8e85 40 41 emart`로 재검증. 다른 마트 변화/기존 분류 변경은 여전히 거부.
- 다음: 이마트 쌀/잡곡/견과 남은 정확 규격 상품 또는 생활용품·반려동물 묶음. 반복 수집관측과 실제 상품 수를 구별하며, DB 전체 완성/운영 적용/실재수집은 미완료.

## 최신 pass40 — 홈플러스 향신료·조미료·액상당류 (2026-09-10)

- 최신 `.debug-artifacts/initial-catalog-20260910-pass40`. `initial_audited_seasonings.py`에 제목 기반 제안. 홈플러스 지정 상위 경로+정확한 제목만 허용. 겨자/와사비/쿠민/파슬리/팔각/깨, 쇠고기·닭 조미료, 맛소금, 액상당류·맛술 구분. 페페론치노는 후추 경로와 기존 후보 충돌로 계속 보류. 혼다시/연두는 이번에 추정하지 않음.
- 전체 원본 비교71관측/36제목 None→리프, 기존 분류 불변. 최종71관측 추가, 이전 포함/431결정 보존. 상품군3,350 / variant3,380 / listing3,500 / offer5,244 / 규칙3,427 / 카테고리461 / 키워드375 / 경로매핑255. 보류3,952(리프미정3,731), active4,491 / pending753.
- 기존 결정 입력 `reviewed-initial-decisions-20260908-remaining-exact.json` 유지. 원본 SHA c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 불변. 운영 수정·승인·공개 없음.
- 관련 seasonings/taxonomy431 passed(0.96초), 생성 검증/멱등 import/독립 stage 검사. 초기 새 테스트가 모든 향신료를 후추 경로에 넣어11실패; 코드의 충돌 방어는 유지하고 테스트를 실제 원본 경로로 수정. 실제 후추 경로의 페페론치노는 음성 검사. 전체 관리자·API·snapshot·runtime 반복 미실행.
- 감사 `py .debug-artifacts/audit_cold_pass36.py 340c7e8 39 40`. 다음은 이마트 농산물 여러 묶음 또는 홈플러스 잔여 냉동식품/반찬. 큰 묶음 마무리에서 공통 통합 검사를 수행하되 매 분류 추가마다 전체 회귀는 반복하지 않는다. 초기 DB 완성/운영 적용/실재수집 검증은 미완료.

## 최신 pass39 — 홈플러스 소금·감미료·분말·제빵재료 (2026-09-10)

- 최신 `.debug-artifacts/initial-catalog-20260910-pass39`. 명시 제목35개 분류표 `services/initial_audited_baking.py` 추가. 홈플러스 지정 식품 경로 한정, 상품명 변경은 별도 검토. 소금 종류/설탕/알룰로스분말/스테비아계감미료와 재료별 가루·제빵 혼합물 구분. 감자맛 전분/뉴슈가/자일로스 혼합설탕 등 성분 불명은 이번에 미확정.
- 전체 원본 비교69관측/35제목 None→리프, 기존 분류 변경 없음. 최종69관측 추가 및 기존 포함/누적431결정 보존. 상품군3,314 / variant3,344 / listing3,464 / offer5,173 / 규칙3,391 / 카테고리440 / 키워드357 / 경로매핑247. 보류4,023(리프미정3,802), active4,420 / pending753.
- 기존 입력 결정 `reviewed-initial-decisions-20260908-remaining-exact.json` 그대로. 원본 SHA c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 불변. 운영 DB 수정·승인·공개 없음.
- 관련 baking/taxonomy430 passed(1.05초), 반복 import 멱등/생성 검증·독립 stage 검사. 과거 '알룰로스는 흰설탕 경로라 무조건 보류' 사례를 정확한 대체감미료 리프 양성 검사로 대체; 맥락/변경명 음성 검사 추가. 전체 관리자·snapshot·runtime·API 반복 미실행.
- 감사 명령 `py .debug-artifacts/audit_cold_pass36.py 6729128 38b 39`. pass38은 사용 금지, pass38b가 직전 유효본. 다음은 남은 조미료/향신료/액상당류 혹은 이마트 농산물 묶음. 초기 DB 전체 완료·운영 적용·재수집 확인은 아직 남아 있음.

## 최신 pass38b — 홈플러스 장류·소스·식용유 (2026-09-10)

- 최신 출력은 **`.debug-artifacts/initial-catalog-20260910-pass38b`**. pass38은 초기 태양초고추장→초고추장 오분류로 사용 금지(폴더 DO_NOT_USE.md). 전체 원본 비교 출력에서 발견해 `(?<!태양)초고추장`과 실제 제목 회귀 검사 추가 후 별도 폴더 재구축. 운영 적용/공개 없음.
- 지정 홈플러스 상세 경로에서 들기름/콩기름/옥수수/해바라기/아보카도 등과 굴/돈까스/스테이크/타르타르/드레싱/칠리/월남쌈/초고추장/비빔장 구분. 전체 변경104관측/56제목 None→리프; 기존 분류 변경 없음. 신규 최종99관측 적재, 기존 포함 및 누적431결정 보존. 명칭불명 스프레이·튀김유, 혼합 중량팩은 보류 유지.
- 누적 상품군3,279 / variant3,309 / listing3,429 / offer5,104 / 매칭규칙3,356 / 카테고리417 / 키워드334 / 경로매핑242. 보류4,092(리프미정3,871), active4,351 / promotion pending753. 같은 수집 기록 수와 상품 수는 다름.
- 입력 결정 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 유지, 원본 SHA c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 불변. 원본/운영 DB 수정 없음.
- 관련 pantry/taxonomy405 passed(0.87초). 생성기 검증·멱등 import·독립 stage 정합성 성공. 전체 관리자·snapshot·runtime·API 재실행 안 함(해당 공통 코드 변경 없음). 감사 `py .debug-artifacts/audit_cold_pass36.py 48ef3ab 37 38b`에서 이전 포함/431결정 보존 확인.
- 다음: 홈플러스 남은 소금·당류·분말·제빵재료를 여러 상세 경로로 묶어 검토. 찹쌀/귀리/메밀/전분은 재료 종류, 감미료는 설탕과 구별. 마트의 '슈가파우더' 안 베이킹소다/파우더/아몬드가루 및 '멸치다시다' 안 쇠고기 조미료 등 오염 경로 주의. 초기 DB 전체 완성/운영 승인/실재수집은 아직 미완료.

## 최신 pass37 — 홈플러스 요거트·치즈 (2026-09-10)

- 사용자 피드백: 분류 변경마다 관리자 전체 테스트를 반복하지 말 것. 이번은 관련 taxonomy/새 dairy-form 테스트만 408 passed(0.97초). 전체 관리자·snapshot·runtime·API 반복 검사는 미실행; 공통 로직 변경/큰 묶음 통합 시 수행한다. DB 생성 자체의 검증/멱등 import와 독립 stage 정합성 검사는 유지.
- 그릭/짜먹는/토핑요거트, 스트링/숙성/구이/과일/블루/포션치즈를 실제 제목과 홈플러스 지정 전체 경로로 판별. 새 분류 근거가 있을 때 기존 상품형태 veto가 이미 거부한 path/name 후보만 제외; 다른 유효한 충돌은 보류. 예전 무조건 그릭 보류 테스트 2사례는 새 양성 검사로 대체했고 다른 유효한 충돌 음성 검사 유지. 새 타마트 검사도 '분류 불가'가 아닌 '이번 전용 근거 미적용'을 검사하도록 수정(타마트에는 기존 이름 기반 분류가 가능).
- 최신 `.debug-artifacts/initial-catalog-20260910-pass37`. 누적 결정 입력 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431건 유지. 원본 SHA c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 불변. 원본/운영 DB 변경·승인·공개 없음.
- 전체 비교 66관측/34제목 None→리프, 기존 분류 변화 없음. 최종66관측 추가: 상품군3,226 / variant3,256 / listing3,376 / offer5,005 / 규칙3,303 / 카테고리402 / 키워드319 / 매핑239. 보류4,191(리프미정3,974), active4,260 / pending745. stage 무결성·분류 연결·보류가격 비비교 검사 성공.
- 영향/이전 포함/431결정 보존 감사: `py .debug-artifacts/audit_cold_pass36.py 5cdeabd 36 37` (이름은 이전 배치지만 revision/이전/다음 pass 인수 지원). 그릭/치즈를 동일 상품군으로 무작정 합치지 않으며 기존 보수적 매칭 유지.
- 다음: 홈플러스 양념/식용유 등 여러 상세 경로 또는 이마트 농산물. 비요뜨 쿠키앤크림은 기존 후보 충돌로 계속 보류, 휘핑크림의 동물성/식물성 및 형태불명 치즈는 추가 근거 필요. 전체 초기 DB/운영 적용은 아직 미완료.

## 최신 pass36 — 홈플러스 냉장 음료·디저트 (2026-09-10)

- pass35 `814ce3f`에서 재개. 냉장주스/신선음료/푸딩디저트류 상품명을 검토해 과채주스·과일음료·젤리·푸딩·귀리음료·식혜 구분. 제목 불명/혼합팩은 보류. 마트/전체 경로 제한을 유지하고 다른 후보 충돌은 덮어쓰지 않았다.
- 출력 `.debug-artifacts/initial-catalog-20260910-pass36`, 기존 누적 결정 입력 `reviewed-initial-decisions-20260908-remaining-exact.json` 431건 유지. 원본 SHA c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 불변. 원본/운영 DB 변경·승인·공개 없음.
- 전체 분류 비교 68관측/36제목 None→리프; 기존 분류 변경 없음. 최종 신규 적재64, 이전 포함/431결정 전량 보존. 누적 상품군3,192 / variant3,222 / listing3,342 / offer4,939 / 매칭규칙3,269 / 카테고리396 / 키워드313 / 경로매핑238. 보류4,257(리프 미정4,040), active4,194 / promotion pending745. 상품 수와 반복 관측 수를 혼동하지 않는다.
- 관리자1,160 passed(기존 경고460), 반복 import 멱등성·stage·snapshot·runtime 검사 성공. snapshot은 pending745 제외/4,194 유지, stage 불변. runtime 119가족,375hit/25miss,각 경로1,200변형 검사.
- 실제 API 4상품 카테고리/총량/단위가 및 DB 해시 불변 검사. 야채사랑365 190ml×4의 1+1은 7,590원/1,520ml/100ml당499원. 초기 검사식이 한 팩760ml만 예상해 실패했으나 원본 행사/API 확인 후 올바른 1+1 계약으로 검사식 수정(가격 코드는 변경 안 함). `.debug-artifacts/audit_cold_pass36.py`, `verify_cold_api_pass36.py`에 근거.
- 다음: 홈플러스 남은 요거트·치즈의 기존 후보 충돌(그릭/짜먹는 요구르트, 치즈 형태)을 검토하거나 이마트 농산물/양념 여러 묶음 진행. 전체 초기 DB 완성·운영 적용·실재수집 검증은 미완료. 하위 에이전트는 이번에 사용 안 함; 단순 명령 대신 큰 반복 묶음에서만 비용/검증 이득 판단.

## 최신 pass35 — 이마트 정육·수산·델리 (2026-09-10)

- 3개 원본 경로 미분류 제목 전량 검토 후 원물/조리식품 구분 추가. 행사 모음 두 건이 초기 감사에서 단건 분류 후보에 포함된 것을 발견해 퍼센트 표기 제외와 회귀 테스트로 보강했다. 단위가 없어 적재되지는 않았지만 제안 자체도 남기지 않는다.
- 최신 `.debug-artifacts/initial-catalog-20260910-pass35`. 누적 결정 입력 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431건, 원본 운영 DB 변경 없음. 전체 원본 SHA 기존 c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 유지.
- 최종 전체 분류 비교 116관측/116제목 None→리프. 기존 분류 변경 없음. 109관측 신규 포함, 기존 포함/431결정 보존. 상품군3,158 / variant3,188 / listing3,308 / offer4,875 / 규칙3,235. 카테고리392 / 키워드310 / 매핑238. 보류4,321 / 미분류4,104. active4,132 / pending743.
- 관리자1,143 passed(기존 경고460), 멱등 적재·stage·snapshot·runtime 검증 성공. snapshot pending743 제외/4,132유지. 개별 API 추가 검사는 이번에 미실행. 운영 승인/공개 없음. `.debug-artifacts/audit_fresh_pass35.py`가 전체 영향과 이전 데이터 보존 검사.
- 다음은 남은 홈플러스 냉장음료·유제품 또는 이마트 농산물/양념 등 여러 묶음. 기존 원본의 1,000g 수량 누락, 메추리알 장조림의 띄어쓰기별 후보 충돌, 길이·범위 수량은 별도 단위/분류 일관성 검토 대상으로 남아 있다. 초기 DB 전체 완성·운영 적용은 아직 미완료.

## 최신 pass34 — 소스·유부초밥재료·젤리 (2026-09-10)

- 사용자에게 설명한 연결: 상품군→통합 리프, 공통 키워드→통합 카테고리, 별도 수동 결정의 상품 키워드/alias도 저장. 모든 상품에 개별 키워드를 수작업으로 채운 것은 아니다. 매칭 규칙→상품군/규격. 실제 재수집 누적은 운영 승인/매칭자료 반영 후 실수집으로 검증해야 하며 아직 자동 적용된 상태 아님.
- 홈플러스 관련 4개 상세 경로 제목 검토, 전체 비교 101관측/52제목 미분류→리프. 양념으로 이미 거부되는 재료명 후보만 소스 근거가 확실할 때 제외한다. 다른 유효한 분류 근거 충돌은 유지.
- 최신 출력 `.debug-artifacts/initial-catalog-20260910-pass34`, 입력 결정 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431개 유지. 95관측 신규 적재, 모든 기존 포함과 결정을 보존했다. 상품군 3,049 / variant 3,079 / listing 3,199 / offer 4,766 / 규칙 3,126. 카테고리 379 / 키워드 297 / 원본경로 매핑 238. 보류 4,430 / 미분류 4,217. active 4,023 / pending 743.
- 관리자 1,130 passed(기존 경고460). 멱등 import·stage·snapshot·runtime 검증 성공. snapshot pending743 제외/4,023 유지. `.debug-artifacts/verify_links_pass34.py`에서 실제 DB 조인으로 규칙3,126→상품군/규격, 상품군3,049→카테고리, 키워드297→카테고리 연결 확인. 신규 개별 상품 API 검사는 이번에 미실행. 운영 DB/승인/공개는 변경하지 않았다.
- `.debug-artifacts/audit_sauces_pass34.py`가 전체 분류 변화 검사. 다음은 홈플러스 남은 냉장음료/유제품 또는 이마트 정육·수산·반찬 묶음. 운영 반영 전 사본 전체 검수와 매칭자료 동기화/실재수집 검증이 아직 필요하다.

## 최신 pass33 — 홈플러스 상세 경로 4묶음 (2026-09-10)

- 소시지/닭가슴살·훈제오리/조림·볶음반찬/기타곡물스낵 제목 전량 검토 후 원본 경로+상품 형태 분류 추가. 전체 원본 비교 149관측/76제목 None→리프, 모두 홈플러스. 생선구이/조림/장아찌/무침 리프 보강. 메추리알 장조림은 기존 알류 이름 근거와 충돌해 계속 보류.
- 최신 출력 `.debug-artifacts/initial-catalog-20260910-pass33`. 누적 결정 입력은 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431개 그대로. 전체 원본 SHA 기존 c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0 유지.
- 최종 145관측 신규 적재, 기존 포함/누적 결정 전량 유지. 상품군 3,000 / variant 3,030 / listing 3,150 / offer 4,671 / 규칙 3,077. 카테고리 373 / 키워드 292 / 매핑 237. 보류 4,525 / 미분류 4,312. active 3,928 / 프로모션 pending 743(+4), 비활성 상품군 562.
- 관리자 1,122 passed(기존 경고 460). 반복 적재·독립 stage·snapshot·runtime 검증 성공. snapshot에서 pending743 제외/active3,928 유지. 운영 승인/공개/원본 수정 없음. 이번에는 개별 상품 API 추가 검사는 하지 않았다.
- `.debug-artifacts/audit_homeplus_pass33.py`가 전체 분류 변화와 이전 포함/431결정 보존을 검사한다. 다음은 홈플러스 즉석요리소스/냉장소스/유부초밥/젤리 등 상세 경로 여러 묶음 진행. 메추리알 장조림은 알류 이름 후보와 충돌하므로 후속 분류 우선순위 검토 대상으로 남긴다.

## 2026-09-10 재개 업데이트 — 최신 pass32 생활·위생·뷰티

- 최신 `.debug-artifacts/initial-catalog-20260910-pass32`, 누적 결정 입력 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431개 유지. 아래 과거 시작점보다 이 절을 우선한다.
- 이마트 `청소/생활용품` 73 / `제지/위생/건강` 69 / `헤어/바디/뷰티` 49의 미분류 제목 191개 전량 검토. `initial_audited_household.py`에 145개 명시 제목 분류표 추가. 액상세제/캡슐세제/건조기시트, 일반샴푸/염색제, 화장지/생리용품 구분. 혼합 선물세트·형태 불명·의료성 품목은 보류.
- 전체 9,196관측 비교에서 대상 145건만 미분류→리프. 최종 coverage +143, 검토 DB 포함 +134. 원본 listing/누적 결정 검증 후의 최종 수와 단건 분류 제안 수는 다르다. 기존 포함 전량과 431개 결정을 보존했다.
- 상품군 2,926 / variant 2,956 / listing 3,076 / offer 4,526 / 매칭 규칙 3,003. 카테고리 369 / 키워드 288 / 경로 매핑 237. 보류 4,670관측, 미분류 4,457. active 3,787 / promotion pending 739. 운영 승인이 아닌 별도 검토 DB 초안이다.
- 관리자 전체 1,113 passed(기존 경고 460), 집중 검사 544 passed. 멱등 import/stage/snapshot/runtime 검증 성공. 실제 API 치약420g/액체세제2000ml/캡슐100개/염색제10팩 리프·총량·해당 단위가격 검사 성공. API 전후 DB 해시 불변. snapshot 보류739제거/3,787유지, 운영 공개 없음.
- bundle SHA-256 `bbad60acb7db6d3d393cf1a3bebbc3c7745d03c0bcbbaca2faf23664d8cd9695`. 원본 SHA 기존 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 유지. 운영 DB 변경·수집·승인 없음.
- 독립 감사 `.debug-artifacts/audit_household_pass32.py`, `.debug-artifacts/verify_household_pass32.py`. 다음은 홈플러스 미분류 상세 경로를 여러 묶음으로 검토하거나 이마트 정육/수산/김치·반찬 묶음 진행. 휴지 길이×롤 수와 붙은 치약 규격 필드 충돌은 여전히 보류 사례가 있어 후속 단위 검토 대상으로 남긴다. 전체 DB 완성/운영 적용은 아직 남음.

## 2026-09-10 재개 업데이트 — 최신 pass31 (이마트 식품 3묶음)

- 최신 `.debug-artifacts/initial-catalog-20260910-pass31`. 기존 누적 결정 입력 `reviewed-initial-decisions-20260908-remaining-exact.json` 431개 유지. 아래 과거 시작점보다 이 절을 우선한다.
- 이마트 미분류 `밀키트/간편식` 146 / `면류/통조림` 117 / `베이커리/잼` 64 = 327관측을 제목별로 묶어 전량 검토. `initial_audited_food.py`에 148개 정확한 제목의 리프 결정을 분리 저장했다. 11개 베이커리 리프 추가(식빵/모닝롤/베이글/하드롤·바게트/페이스트리/생지/케이크/머핀/스콘/휘낭시에/과일잼). 원본 경로 이름을 통합 계층으로 복사하지 않았다.
- 9,196관측 전체 분류기 비교: 이번 3묶음에서만 245관측 None→리프, 기존 분류 변경 없음. 최종 workspace 분류 coverage는 4,361→4,596(+235), 검토 DB 포함은 4,176→4,392(+216). 분류기 단건 제안과 원본 listing 전량/이름 변경 검증을 거친 최종 집계를 혼동하지 않는다.
- 상품군 2,792 / variant 2,822 / listing 2,942 / offer 4,392 / 매칭 규칙 2,869. 카테고리 337 / 키워드 260 / 경로 매핑 237. 보류 4,804관측, 미분류 4,600. active 3,653 / promotion pending 739. 운영 승인/공개와 별개인 초안이다.
- 관리자 전체 960 passed(기존 경고 460), 집중 taxonomy/새 감사표 549 passed. 이전 포함 전량/431결정 보존. 멱등 import·stage·snapshot·runtime 검증 통과. 실제 API 콘치즈피자300g/링귀니500g/식빵380g/딸기잼800g의 리프·총량·단위가 확인. API 전후 DB 해시 불변.
- 최초 API 표본의 우주인피자는 이전 수집에서 `[쓱클럽 10%쿠폰]`으로 제목이 달랐기 때문에 source_title_changed로 적재되지 않음을 확인했다. 보류 계약을 유지하고 별도의 콘치즈 피자로 양성 API 검사. 컵/봉지 형태 불명 라면, 닭한마리 칼국수 기존 충돌, 행사 모음, 혼합 치아바타, 샌드위치용 샐러드 등은 무리하게 분류하지 않았다.
- bundle SHA-256 `f0a9b60abf1047e47fa33e6b8be2def73a6f47052b91849bb3212afe72c62745`. 원본 SHA 기존 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 유지. snapshot 보류 739제거/3,653유지, 운영 공개 없음.
- 독립 감사 `.debug-artifacts/audit_emart_food_pass31.py`, `.debug-artifacts/verify_emart_food_pass31.py`. 다음도 여러 카테고리 동시 검토 후 검증 1회: 이마트 청소/생활73·제지/위생69·헤어/바디49 또는 홈플러스 잔여 상세 경로 묶음. 코스트코 반복 소량 처리로 돌아가지 않는다. 아직 초기 DB 전체 완성/운영 적용/웹 인수검증은 남아 있다.

## 2026-09-10 재개 업데이트 — 최신 pass30 (공통 규격 수정)

- 이 절이 아래 과거 시작점보다 우선한다. 사용자 피드백: 매번 소량 분류 후 전체 검사/마무리하는 속도로는 완료가 너무 느림. 다음에는 여러 카테고리 묶음을 함께 검토하고 전체 검증은 묶음 끝에 실행할 것. 완료 시점/남은 호출 수를 근거 없이 약속하지 않는다.
- 최신 `.debug-artifacts/initial-catalog-20260910-pass30`, 결정 입력 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431개 그대로. 원본 운영 DB 변경 없음.
- 공통 파서: `1,050g`을 50g으로 자르는 오류 수정. 한 중량 뒤 연속 곱셈 `350g×5×2pk`, `5g×30ct×2` 전체 곱셈 처리. seed는 모든 곱셈 기호가 단일 해석에 포함된 경우만 허용, 구조화 수량/총량/명시 bundle_count 충돌은 계속 보류. 새 연속 묶음 중 500개 초과는 도매 규격 검토 대상으로 보류(품질 경계이며 산술 오류라는 뜻 아님). 기존 단일 1000개 종이컵에는 이 경계를 적용하지 않는다.
- 원본 9,196관측 대조: 93관측의 규격/진단 변경, 58개 단위 문제 해소, 분류까지 있는 34개 신규 적재. 대량 연속묶음 6개 검토 유지. 천 단위 숫자로 잘못 수집된 기존 구조화 필드는 덮어쓰지 않으므로 아직 보류다.
- 코스트코 수집기 자체의 마지막 숫자 추출기를 공통 파서로 교체하고 bundle_count/display_unit을 수집 결과 변환까지 보존. 라이브 수집은 하지 않음.
- 누적 상품군 2,663 / variant 2,693 / listing 2,813 / offer 4,176 / 규칙 2,740. 카테고리 323 / 키워드 248 / 경로 매핑 237. 보류 5,020 / 미분류 4,835. active 3,437 / promotion pending 739. active가 반드시 단위가격 비교 가능하다는 뜻은 아님.
- 관리자 802 passed(기존 경고 460), shared 161 passed, Costco crawler 14 passed. 이전 연속 곱셈 무조건 보류 테스트 13개는 파서 기능 부족 계약이므로 전체 곱셈 일치/충돌별 계약으로 교체. 부분 해석/소수 개수/혼합 상품/잘못 수집된 중량/도매 규모 거부 대체 테스트 추가.
- 멱등 적재, stage/snapshot/runtime 검증 성공. 이전 포함 행/431결정 보존, 실제 API 잡채 350g×10=3500g, 순대 500g×6=3000g, 볶음밥 300g×14=4200g 및 단위가격 확인. API 검사 전후 DB 파일 해시 동일. snapshot은 보류 739개 제거/3,437개 유지, 운영 게시 없음.
- bundle SHA-256 `86b945449175706fc1e71b30bb608f677aac9fbb98d0a8b5244c749ca2661201`. 원본 SHA 기존 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 유지. 독립 감사 `.debug-artifacts/audit_units_pass30.py`, `.debug-artifacts/verify_units_pass30.py`.
- 다음: 분류 대기 4,835관측을 마트별 원본 경로로 묶어 처리량 큰 여러 카테고리 전량 검토. 기존 쉼표 수량 오류는 원본 제목·URL·표시 단위가격을 확인해 명시 검토 결정으로 정정 가능(무조건 제목 우선 자동 덮어쓰기 금지). 혼합세트/범위 중량은 계속 별도 검토. 초기 DB 전체 완성·운영 적용은 아직 남아 있다.

## 2026-09-10 재개 업데이트 — 최신 pass29

- 아래 모든 pass28/pass27 시작점보다 이 절을 우선한다. 최신 출력 `.debug-artifacts/initial-catalog-20260910-pass29`, 누적 결정 입력 `reviewed-initial-decisions-20260908-remaining-exact.json` 431건 유지.
- 코스트코 `고기` 미분류 74개 제목 전량 검토. 22개 정확한 제목에 음식 형태별 리프 부여, 15관측 추가 적재, 7개 규격 문제 보류. 그릴/숯/사료/혼합세트는 고기로 넣지 않았다. 새 리프: 조리잡채·양념육·훈제오리·순대(순대는 규격 보류라 출력에는 아직 없음).
- 누적 상품군 2,629 / variant 2,659 / listing 2,779 / offer 4,142 / 매칭 규칙 2,706. 카테고리 320 / 키워드 245 / 경로 매핑 237. 보류 5,054관측, 리프 미지정 4,835. active 3,403 / 프로모션 pending 739. active와 단위가격 비교 가능 여부는 다르다.
- 관리자 전체 796 passed, 기존 경고 460. 전체 원본 비교에서 위 22건 외 분류 변경 없음. 기존 포함 행과 431개 결정 보존. 두 번 적재 멱등성, 독립 stage/snapshot/runtime 검증 통과. snapshot은 보류 739개 제거/3,403개 유지, 운영 공개 아님.
- 원본 해시 기존 `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0` 유지. bundle SHA-256 `9e152e6c4a6c9dea7042a31b056ad22e8c8c901c8cac817837422ed06a077a6f`. 운영 DB 변경·승인·공개 교체 없음.
- 독립 감사 스크립트 `.debug-artifacts/audit_meat_pass29.py`. 다음은 규격 보류 원인 조사 권장: `2,500g`, `1,060g`, `1,050g`, `1,150g`가 multiple_package_quantities로 보류되는 것이 천 단위 쉼표 파싱 문제인지 원본 필드 충돌인지 확인. `350g x 5 x 2pk`, `500gx3x2`, `300g x 7 x 2봉(4200g)`도 연속 묶음 처리 검토. 테스트를 완화하지 말고 전체 9,196관측 영향과 실제 총량을 대조한다. 이후 이마트 간편식 등 다음 카테고리 묶음으로 진행.

## 2026-09-10 재개 업데이트 — 최신 pass28

- 아래 pass27 이력보다 이 절을 우선한다. 최신 폴더는 `.debug-artifacts/initial-catalog-20260910-pass28`이며 누적 수동 결정 입력은 기존 `reviewed-initial-decisions-20260908-remaining-exact.json` 431건 그대로다.
- 코스트코 과일 미분류 69개 판매 페이지를 읽고 23관측에 리프를 추가했다. 16관측이 새 검토 DB에 포함되고 7관측은 수량 충돌로 보류됐다. 원본 9,196관측 전체 비교에서 다른 분류 변경은 없었다.
- 상품군 2,614 / variant 2,644 / listing 2,764 / offer 4,127 / 매칭 규칙 2,691. 카테고리 317 / 키워드 242 / 경로 매핑 237. 보류 5,069관측, 리프 미지정 4,857관측. active offer 3,388, pending 739. active라고 모두 단위가격 비교 가능한 것은 아니다.
- 관리자 전체 782 passed(기존 경고 460), 멱등성·snapshot·runtime 검증 통과. 실제 API 4상품에서 중량 확인: 라임·자몽은 단위가격 계산, 용과·망고의 checkout_discount는 비교가격/단위가격 없음이 현재 계약이다.
- bundle SHA-256 `df3eb1e50e9b615b7c894d62ca2379e58b6a457b8f773fd42d8bb43f3efa6ef1`. 원본 변경/운영 승인/공개 교체 없음.
- 다음 작업: 과일의 나머지 혼합세트·가공음료 또는 코스트코 고기 진열 전량 검토. `6kg 미만` 수박, `4입(각 2입)` 멜론 등 부정확한 규격은 이번에 포함하지 않았으며 수량 처리 자체의 보강은 남아 있다. 그린키위 한 제목은 기존 충돌 검사가 막아 계속 보류한다.
- 독립 검사: `.debug-artifacts/audit_fruit_pass28.py`, `.debug-artifacts/verify_fruit_pass28.py`. 기존 출력 폴더를 덮어쓰지 않는다.

할당량 중단 후 재개한 작업 기록이다. 최신은 pass27이며 상세 근거는 `CLASSIFICATION_BATCH_20260908.md` 마지막 절을 우선한다. 다음 작업은 이 문서와 `git status`를 함께 확인한다. 아래 초기 카탈로그는 **별도 검증 DB의 초안이며 운영 승인본이 아니다**. pass4 등 과거 수치는 이력으로 보존한다.

## 보존 상태

- 최신 후속 변경: 이마트 카테고리 요청 간격을 고정 360초에서 매 요청 시도마다 360~420초 무작위로 변경했다. 마지막 요청 시각 저장은 유지하며 재시작 후에도 최소 360초를 지킨다. 이미 경과한 시간은 차감한다. 관련 검사 44 passed / 1 skipped, 실제 사이트 수집은 하지 않았다.
- 사용자에게 설명한 완료 경계: 원본 백업과 별도 검토용 DB 구축은 했지만, 운영 관리자 DB의 초기 매칭·카테고리·키워드·상품 테이블을 모두 완성하여 적용한 것은 아니다. 최신 pass27도 검토용 초안이다. 남은 상품 분류를 완료한 뒤 기존 승인 절차로 운영 적용해야 한다.

- 브랜치: `cleanup/remove-legacy-ai-admin-coupling`.
- `b6ef0cc`: 이마트 360초 영속 대기 제한, 검토 목록의 50개 배치 잘림 수정.
- `a247fee`: 원본 행 accounting/offer 근거 보존, 키워드 UnifiedCategory FK, 테스트 DB 격리.
- `19b0aed`: 초기 카탈로그 seed/계층 분류/검토 workspace/CLI와 회귀 테스트.
- `eb1c5be`: 매칭 ID의 3개 형식 동기화 및 인증 테스트 계약 격리.
- `75f4bd0`: 원본 listing/이름/규격 재검증, export miss 보존, 복합포장·수량구간 검수.
- `62e8e2e`: 스냅샷의 검토 대기 offer/주간 링크 제외 및 로컬·원격 검증기 거부.
- 사용자가 push를 승인했고 완료한 체크포인트는 원격에 반영한다. 과거 고정 커밋 수나 해시에 의존하지 말고 재개 시 `git status`와 로컬/원격 HEAD를 다시 확인한다.
- 실제 원본: `.walletsavior/admin.sqlite`. 이 작업에서 운영 DB 마이그레이션·분류 적재·수집 승인·공개 snapshot 승인은 하지 않았다.
- 기존 백업: `.walletsavior/backups/pre-initial-catalog-20260903-044952/admin.sqlite` (17,711,104 bytes).
- 원본은 108개 pending ingestion, 9,196개 관측이다. Emart 1,802 / Homeplus 5,227 / Lotte 829 / Costco 1,338. 고유 listing은 6,543개다.
- 선택 원본 행의 SHA-256: `c4431eea85f0c1c2f54c202030daed8f8904d8c7b832491a126b8541590845e0`. 이는 SQLite 파일 자체 해시가 아니라 `read_pending_source`의 명시적 컬럼/정렬/직렬화 해시다.
- Homeplus 두 수집의 겹친 2,492개 listing은 삭제하지 않았다. 가격 변경 51개, 이름 변경 4개를 포함한다. 반복 관측은 시점별 offer로 보존해야 한다.
- `packages/db-admin/backend/walletguardian.db`는 예전 개발용 사본이다. 초기 DB 원본으로 사용하지 않는다. 예전 인증 테스트가 이 설정 DB를 사용하던 문제를 임시 DB fixture로 고쳤다.

## 완료한 코드와 검증

- 이마트: 요청 전 시각 기록, 재시작/동시 인스턴스/별도 이벤트 루프에서 360초 제한 유지. 403/429/취소/네트워크 실패도 동일 제한. 단일 프로세스의 스레드 간 잠금이며 분산 프로세스 잠금은 아니다. 라이브 수집은 하지 않았다.
- 크롤러 프런트: 18 tests passed, production build 성공(기존 chunk size 경고). 최신 백엔드 전체 결과는 아래 검증 기록을 따른다.
- 데이터 검토: API 500개 단위로 모든 배치를 가져온다. 501개 fixture에서 마지막 51페이지 접근 확인.
- 키워드 통합 카테고리 FK와 `capstone_keyword_ssot_v1` 마이그레이션 추가. 실제 운영 DB의 **별도 복사본**에서 upgrade → downgrade → upgrade, 전체 테이블 건수·원본 해시 보존, integrity/FK 검증 통과.
- 인증 테스트는 실제 사용자를 임시 DB에 생성한 `/me` 200과 없는 사용자 404를 별개 검증한다. 이전 조건부/vacuous assertion을 제거했다.
- importer: malformed rows, 중복 source key/variant/match key, 잘못된 variant 부모, 단위 미해석, 원본 accounting 누락 검증 보강. 별도 bundle 재수집도 offer의 이전 raw evidence를 합쳐 보존한다. timezone-aware 시각은 UTC 변환 후 저장한다.
- `initial_catalog_seed.py`: 순수 결정적 bundle 생성, 원본 행 전량 accounting, 보수적 규격/브랜드/그룹/키 충돌 검증. 명시적으로 검토한 그룹만 cross-mart 병합한다.
- `initial_taxonomy.py`: 새 4단계 리프 분류기. 원본 경로도 오염될 수 있어 이름과 충돌하면 보류. 유제품 관련 원본 268 listing 전량 검토 및 형태/속성/비식품 오분류 방지 보강. 상세 범위는 `INITIAL_TAXONOMY_AUDIT.md` 참조. 155 tests passed.
- `initial_catalog_workspace.py` + `tools/prepare_initial_catalog.py`: 원본 DB read-only → 전량 HTML/JSON 보고서 → 새로운 별도 DB 적재 2회 → 중복/무결성 검사. 운영 적용/승인 옵션은 없다.
- 명시 검토 문서는 `reviewed_draft`/검토자/원본 snapshot hash/각 listing의 모든 raw ID+hash를 요구한다. 상품군·리프·규격 결정은 반영할 수 있지만 가격·프로모션·공개 승인 상태는 주입할 수 없다.
- 실제 브라우저에서 대기 108개, 마지막 11페이지 `101–108` 표시를 확인했다. 실제 프런트 → 실제 crawler API → 실제 DB API 경로이며 운영 DB 복사본을 사용했다. 서버 lifespan/startup은 꺼서 스케줄·수집·seed를 실행하지 않았다. 이것은 Windows 전체 시스템 실행 인수 테스트를 대신하지 않는다. 테스트 서버 8001/8002/5174는 종료했고 승인·삭제 버튼은 누르지 않았다.
- 매칭 동기화 YAML/JSONL/CSV에 `public_product_id`/`public_variant_id` 보존. 구버전 파일의 누락 열은 기존 ID 유지, 명시 null만 초기화한다. 실제 FK 대상과 3개 형식 왕복 검증.
- 매칭 import API의 401은 환경 의존 fixture 문제였다. moderator 인증 계약을 유지하고 임시 DB+명시 인증으로 갱신했다. 무인증/잘못된 키 401, viewer/service 403, 인증 실패 시 DB 미접근도 검증했다.

## 생성된 로컬 증거 (모두 Git 제외)

- 과거 `.debug-artifacts/initial-catalog-20260903-pass4/`: `source-ingestions.json`, `catalog-bundle.json`, `classification-decisions.json`, `reviewed-decisions.json`, `product-group-candidates.json`, `review.html`, `staging.sqlite`, `summary.json`, `public-snapshot-rehearsal.sqlite`.
- pass4: 상품군 2,236 / variant 2,236 / listing 2,248 / offer 3,552 / 매칭 규칙 2,185. 카테고리 233(부모 포함), 키워드 166, 원본 경로 매핑 222. 9,196관측 중 3,552개 stage, 5,644개 보류이며 전량 accounting/evidence가 일치한다. stage는 공개 승인이라는 뜻이 아니다.
- stage의 2,854개 관측은 가격 비교 가능 형태이고, 698개는 조건 확인 전 pending_review다. 620개 상품군은 비교 가능한 active offer가 없어 비활성이다. pending offer에 단위가격이 없고 내부 카테고리 귀속/잘못된 variant 부모/레거시 상품·카테고리 적재가 0임을 별도 read-only SQL로 확인했다.
- 원본 mart별 stage 관측: Costco 119 / Emart 165 / Homeplus 2,708 / Lotte 560. 미분류·규격 불확실 관측도 삭제하지 않고 보류 목록에 포함했다. 매칭 키 충돌 29그룹은 자동 규칙 생성에서 제외했다.
- 동일 bundle 두 번 적재 후 모든 테이블 건수 불변, FK 0, integrity ok. `.debug-artifacts/verify_initial_stage.py initial-catalog-20260903-pass4`가 독립 SQL/evidence 검사다. `--snapshot`은 기존 파일을 덮어쓰지 않고 검증용 파일만 만든다.
- `public-snapshot-rehearsal.sqlite`는 운영 게시본이 아니다. root 독립 검증: 보류 698→0, 비교 가능한 2,854 offer 유지, 비활성 상품군 620 유지, FK 0, stage DB 파일 해시 불변.
- pass1/pass2/pass3는 이전 증거로 보존했고 더 이상 최신 분류 결과가 아니다. 기존 출력 폴더는 덮어쓰지 않는다.
- `.debug-artifacts/initial-taxonomy-review.json`: 리프별 전체 상품명/원본 경로, 보류 목록. 첫 제안 2,279 listing의 이름을 리프별로 검토했다. 이후 오염 방지 규칙 적용 결과 taxonomy-only 2,139 listing / 159 leaves. 모든 미분류 상품을 수동 분류한 것은 아니다.
- `.debug-artifacts/lotte-promotion-audit.json`: 829개 관측의 57개 문구 분석. 78개 일반표시가 후보, 나머지 751개 조건 확인 전 추가 혜택가 계산 금지. 숫자 파싱 성공과 혜택가 확정을 혼동하지 않는다.
- `.debug-artifacts/reviewed-product-group-proposals.json`: 가공식품 13군 / 26 listing / 39 원본 관측 제안. 그중 12군/24 listing을 독립 검토해 `.debug-artifacts/reviewed-initial-decisions-20260903.json`에 기록하고 pass3/pass4에 반영했다. 제목·규격을 확인한 명시적 병합이며 운영 승인과 다르다. 고기엔참소스는 적합 리프/출처 검토가 더 필요해 보류했다.
- 12군 검토 문서 SHA-256: `be289d0c6beca0e6411dd62e8e431d1de4a5ab3db764f9ac17bb2d8caa2ed939`. 전체 119개 cross-mart 자동 후보가 모두 병합된 것은 아니며 명시 검토 12군만 병합했다.
- 후속 과일/채소/두부 조사: `.debug-artifacts/produce-taxonomy-review.json`은 267 listing/273관측 전량을 보존한다. root가 그중 토마토14/사과7/두부8/순두부2/냉동과일16의 실제 원본과 전체 경로를 재대조했다. 원본 상품군 병합이나 규격 추정 없이 리프만 개별 결정했다.
- 누적 71 listing 검토 문서: `.debug-artifacts/reviewed-initial-decisions-20260903-produce.json`, SHA-256 `36f42528b04ae4ed7c7c771b9cfd8302781a0e382a81567850d439f1eb36d8f1`. 기존 24 listing/12군 결정을 포함한다. 단위 경계 수정 후 이 문서로 pass4를 생성했다. 리프 분류가 정해져도 규격 검증을 통과하지 못하면 offer는 생성하지 않는다.
- `.debug-artifacts/keyword-migration-rehearsal-20260903.json` 및 `.sqlite`: 운영 DB 복사본 마이그레이션/롤백 검증 증거.

## 다음 시작점

2026-09-09 최신은 **pass27/코스트코 치즈 진열 전량 감사와 붙은 묶음 표기 수정/누적 431개 수동 결정 유지**다. 상품군 2,598 / variant 2,628 / listing 2,748 / offer 4,111, 보류 5,085관측이다. 최신 결과는 `docs/CLASSIFICATION_BATCH_20260908.md` 마지막 절을 우선한다. 위 pass4 건수는 이전 기록이다. 조사·제안 파일을 승인본으로 취급하지 않는다.

1. 최신 전체 테스트 결과와 `git status`를 확인한다. 아래 완료한 단위/스냅샷 수정을 다시 시작하지 않는다.
2. 현재 pass27이 최신이다. 분류 코드/검토 문서 변경 후에는 새 출력 폴더에 workspace를 재생성한다. 누적 431개 결정을 유지하려면 아래 `--review-decisions`를 반드시 사용한다.
3. 5,085개 보류 중 4,880개가 리프 assignment 미지정이다. 같은 방식으로 다음 원본 카테고리의 이름과 오염 예외를 한 번에 검토한다. 코스트코 치즈 진열의 애견용·도구·선물세트·형태 불명 치즈는 억지로 흡수하지 않았다.
4. `가지 3입(봉)`과 `팽이버섯 3입(봉)`은 홈플러스가 1봉, 다른 마트가 3입으로 읽혀 단위가 충돌하므로 보류했다. 4~7입 복숭아도 확정 수량처럼 비교하지 않는다. 후속 단위 파서 묶음에서 고친 뒤 다시 검토한다.
5. 이마트/코스트코의 대부분은 넓은 원본 카테고리와 부족한 제목 근거로 미분류다. 누락을 감추기 위해 `기타`/부모 노드에 밀어넣지 말고 실제 상품 검토로 보완한다.
6. 코스트코 1,338개에는 상품별 시각이 없다. ingestion UTC 수신시각을 쓰되 `timestamp_source=ingestion_received_at`, `observed_time_precision=batch`로 표시한다. 실제 개별 수집시각처럼 표현하지 않는다.
7. 1+1/2+1/10+1처럼 구매·증정 수량이 명시된 655개는 실지출과 실수령량으로 단위가격을 계산한다. 숫자 조건이 없거나 미해석인 프로모션은 가격 원문을 보존하되 공개 비교에서 제외한다.
8. 검토 완료 이후에만 운영 DB 백업 → 마이그레이션/초기 적재 → 두 단계 승인 → snapshot 진행. 현재 542개 레거시 category/4,813개 결과의 최종 재사용 또는 폐기는 아직 실행하지 않았다.

재생성 명령 (저장소 루트, 출력 폴더는 새 이름):

```powershell
& 'C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe' tools/prepare_initial_catalog.py --out .debug-artifacts/initial-catalog-NEXT --run-id initial-catalog-NEXT --review-decisions .debug-artifacts/reviewed-initial-decisions-20260908-remaining-exact.json
```

이 환경의 `py` launcher가 실패했으므로 검증된 Python313 경로를 사용했다. JSON/HTML/SQLite 및 크롤링 산출물은 Git에 넣지 않는다.

## 최신 검증 기록

- DB 관리자 전체: **774 passed**, 460 existing warnings, 44.30s (2026-09-09).
- 크롤러 전체: **283 passed**, 1 live deselected, 32.86s (2026-09-05).
- 공개 API 전체: **74 passed**, 25 existing warnings, 11.34s (2026-09-09). 실행에 비운영 `JWT_SECRET_KEY`를 지정했다.
- 공통 계산 전체: **159 passed**, 0 warnings, 0.57s (2026-09-09).
- 집중 테스트는 전체 테스트와 중복이므로 합산하지 않는다. 프런트는 변경하지 않았고, 공통 가격 계산 패키지는 증정행사 계산을 추가해 전체 검사했다.

## 이번 재개에서 마무리한 경계 수정

- 실제 4사 각 원본의 builder → import → runtime/export hit 및 이름 변경·규격 변경·신규 source listing miss 확인. `T` 티백 개수를 ton으로 취급하던 runtime 단위 처리, `ea`/`개입` 동치 14건, 복합포장/수량구간 검수 보강을 완료했다. 초기 단위 검사를 통과한 실제 8,304관측에서 builder/runtime 판정 차이는 0건이다.
- `7~10입`을 10입으로 확정하지 않는다. 총중량 `1.5kg(5~6입)`은 중량 기준을 유지한다. 김부각 `(5개입)×5`, 종이타월 `160매×12롤`, 용기+분말 혼합패키지의 단일 수량 추정도 금지한다.
- 공개 API는 이미 pending 가격을 제외한다. 양반 김밥김 비교에서 이마트 3984원만 표시되고 롯데 pending 2990원은 제외, pending-only 상품은 detail/compare/history/trust 모두 404를 실제 router에서 확인했다.
- 기존 snapshot serializer가 pending offer와 주간 링크를 복사하던 문제를 수정했다. pending_review offer와 그 링크만 제외하며 로컬/원격 validator도 섞인 파일을 거부한다. inactive 상품이나 다른 과거 상태는 그대로 보존한다. 운영 snapshot은 생성/교체하지 않았다.
- 남은 호환 경계: shared `build_match_key(...,14,"T")` 직접 compound 입력은 여전히 ton으로 해석한다. 이번 실제 T 원본 20행에는 `pack_qty/pack_unit`이 없고 `||14t` 등 저장 키를 사용해 이 변환이 일어나지 않았다. shared 매칭 키 호환 정책은 이번에 변경하지 않았으며 후속 compound 입력 계약 정리가 필요하다.
