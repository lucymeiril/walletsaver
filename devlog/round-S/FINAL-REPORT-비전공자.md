# WalletSavior Round S 최종 보고서 (비전공자용)

작성일: 2026-05-27 새벽
작성자: 메인 슬롯(직접 작성, 에이전트 위임 금지 — 사용자 메모리 준수)

---

## 0. 한 줄 요약

**당신이 콕 집어 지적한 6가지 문제를 hotfix 1건 + fleet 4슬롯으로 한 라운드 안에 박았습니다. 라이브 fetch는 여전히 sandbox 차단이라 사용자 PC 검증이 필요한 부분도 있지만, 30분 무한 retry → TypeError 크래시 같은 명백한 버그는 코드에서 다 사라졌습니다.**

---

## 1. 당신이 지적한 것 → 처리 매핑

| # | 당신 지적 | Round S 처리 |
|---|---|---|
| ① | `_retry_request` 가 rate-limit 무한 재시도 후 `exceptions must derive from BaseException` 크래시 | **메인 직접 hotfix** — 4사(emart/homeplus/lottemart/cocodalin)의 동일 버그를 즉시 수정. `last_resp` 저장 → retry 다 소진하면 마지막 응답 반환(downstream의 `status_code != 200` 분기로 안전 처리). 정말 응답조차 없으면 `last_exc or HTTPError`로 명시 raise. **이제 TypeError 절대 안 남.** |
| ② | 이마트 외부셀러(이마트몰 입점 일반 업자) 상품이 섞임. `shpp=ssgem`(주간배송) + `shpp=smon`(새벽배송) 2회 순회로 자사 상품만 골라야 함 | `_build_source_requests()` 가 카테고리당 ssgem/smon 두 URL 생성. 기존 `cdtl_ico_item` DOM 필터도 안전망으로 유지. |
| ③ | 홈플러스 기본 마트 카테고리는 `delivery=HYPER_DRCT` 필터, `/express` 경로는 필터 불필요 | HYPER 빌더는 `delivery=HYPER_DRCT` 강제, EXP 빌더는 무필터. 단위 테스트로 잠금. |
| ④ | 홈플러스 동적 스크롤 안 돌려서 첫 화면만 들어옴 | Playwright 렌더링에 `scroll=True, scroll_selector=".unitItemInner"` 명시. `browser_session.scroll_until_stable()` 활용. |
| ⑤ | 홈플러스 임시 `?gnbNo=...&promoNo=...` URL이 저장됨 → 다음 주에 죽는 링크 | `/p/{slug}` 영구 URL만 저장하도록 가드 + 회귀 단위 테스트 추가. 임시 promo URL이 들어오면 파서가 거부. |
| ⑥ | 롯데마트 UUID URL `/products/9f4a776d-...` 저장되는데 들어가지지도 않음. `/products/OS8801114111147/details` 가 정식 | 이미 G1에서 OS코드 빌더로 고쳤었음. Round S에서 **UUID-URL 입력 가드 + plugin URL 템플릿 강제** 추가하여 회귀 시 즉시 잡히도록 잠금. |
| ⑦ | 1+1 / 2+1 강조 라벨 (`mnemitem_tag_bogo` 등) 인식해야 함 | 4사 공통 `promo_label` / `promo_type` 필드 신설. `\d+\+\d+` 정규식. DiscountItem + DB Product 모델까지 매핑. 이마트/홈플러스 fixture 단위 테스트 추가. |
| ⑧ | 30분 넘게 걸리는 속도 | 이마트 Playwright/requests 양 경로 `asyncio.gather` + `Semaphore(3)` 동시성 도입. 카테고리 ssgem/smon 2회 순회 늘어났음에도 순차 대비 단축 기대 (실측은 사용자 PC 필요). |
| ⑨ | 0/0/0/0 진행률 무한 표시 | 백엔드 progress 콜백 + SSE 채널 보강, 이마트/롯데마트에 중간 publish 추가. 프론트 카운터 표시 개선. `g3_e2e_user_scenario.py`에 진행률 캡쳐 단계 추가. |
| ⑩ | 셸에서 실행 안 되고 crawler admin 버튼만 됨 | 진단 보고서 `s-orchestrator-ui-report.md`에 셸 실행 경로/필요 환경변수/포트 매트릭스 정리. 사용자 PC 검증 체크리스트 첨부. |

---

## 2. 회귀 검증 (실제 실행 결과)

| 영역 | 명령 | 결과 |
|---|---|---|
| crawler-admin 마트 종합 | `py -3 -m pytest packages\crawler-admin\backend\tests\test_mart_crawlers.py test_homeplus_crawler_g1.py test_homeplus_crawler.py -q` | **95 passed, 3 skipped, 회귀 0건** |
| shared 종합 | `cd packages\shared; py -3 -m pytest -q` | **623 passed** |
| (sub-agent 보고) emart 단독 | `py -m pytest ... -q` | 90 passed, 3 skipped |
| (sub-agent 보고) lottemart probe | `py -m pytest ...` | 46 passed |
| (sub-agent 보고) orchestrator | `py -m pytest test_pipeline.py test_crawler_api.py` | 49 passed |

라운드 시작 직전 발생하던 `TypeError: exceptions must derive from BaseException` 은 코드 경로에서 완전히 제거됨. retry 다 소진해도 절대 None을 raise 하지 않음.

---

## 3. 사용자 PC에서 직접 확인할 것

본 sandbox는 외부 HTTP 차단 + 헤드 브라우저 없음. 사용자가 직접 다음 3단계로 검증해야 진짜 데이터 흐름 증명됨:

### 3-1. 크롤러 실행 (crawler-admin 프론트의 실행 버튼)
- 이마트 1개 카테고리만 먼저 (예: 신선식품 → 채소)
- 기대: 30분 무한 retry 없이, 최대 max_retries × 2초 backoff 내 종료. 결과 0건이면 0건으로 종료(이전엔 크래시).
- 확인: 진행률 표시가 0/0/0/0 고정이 아니라 카운터 증가하는지

### 3-2. DB admin에서 결과물 확인
- Product 테이블에 `mart`, `mart_native_code`, `canon_hash`, `promo_label` 컬럼이 채워졌는지
- 이마트 상품 URL이 `itemView.ssg?itemId=...` 형식인지 (외부셀러 itemId 아님)
- 홈플러스 상품 URL이 `/p/{slug}` 또는 상품 상세 영구 URL인지 (promoNo 임시 URL 없음)
- 롯데마트 URL이 `/products/OS.../details` 인지 (UUID 없음)

### 3-3. 라이브 fetch 실증
```powershell
py -3 packages\crawler-admin\backend\scripts\round_r_g1_seed.py --live --marts emart,homeplus,lottemart,costco
py -3 scripts\g3_e2e_user_scenario.py
py -3 scripts\g4_e2e_ai_cycle.py
```

만약 403/429이 또 뜬다면 → 단순히 sandbox 차단이 아니라 진짜 anti-bot 일 수 있음. 그 경우 storage_state.json 쿠키 재생성 + UA 로테이션이 다음 라운드 과제.

---

## 4. 아직 못 한 것 (다음 라운드 후보)

1. **algumon / opinet 라이브 마크업 정찰** — fixture만 깔린 상태.
2. **end-to-end 사용자 시나리오 자동화의 실제 실행** — 스크립트는 작성됐으나 사용자 PC 실행 결과(캡쳐 + JSON 리포트)가 없음.
3. **DB admin 프론트의 새 컬럼(promo_label 등) 표시** — 백엔드 모델은 추가됐으나 admin UI 카드/테이블 뷰가 새 필드를 그리는지는 사용자 PC에서 확인 필요. `s-orchestrator-ui-report.md`의 cross-cut 목록 참고.
4. **이마트 동시성 실측 벤치마크** — 코드는 Semaphore(3)이지만 실제 응답 시간/anti-bot 트리거 여부는 라이브 호출 안 해본 상태. 사용자 PC 실측으로 동시성 값(2~5) 튜닝 필요.
5. **카테고리 통합 매핑 검증** — 4사 라이브 데이터가 모이면 통합 트리(g2-unified-tree.yaml)와 실제 카테고리 분포를 대조해 미스매치 분량 측정 필요.

---

## 5. 당신의 큰 우려에 대한 답

> "에이전트 보고 신뢰하지 말라니까. todo done은 무슨 실제로 기능하는 게 하나도 없구만."

이번 라운드에서 의식적으로 바꾼 것:

- **명백한 버그(_retry_request)는 메인이 직접 수정**. fleet에 위임 안 함. 첫 hotfix 즉시 회귀 테스트 63 passed/0 regression 확인 후에야 fleet 발진.
- **fleet 프롬프트에 "라이브 fetch 시도 금지(불가능)", "추측 보고 금지", "fixture / 코드 인용 + 단위 테스트만 인정" 명시**.
- **각 agent에 별도 단위 테스트 추가 강제** → 다음에 누가 또 같은 버그 만들면 즉시 fail.
- **최종 보고서는 메인이 직접 작성** (사용자 메모리: "보고는 에이전트 돌리지 말고 니가 직접 작성하고") — 본 문서.
- **사용자 PC 검증이 필요한 부분을 따로 분리해서 명시** — "이건 코드만 고쳐졌고 실 데이터 증명은 사용자 PC 필요"를 §3에 항목별로 적시. "다 됐다" 식 자기보고 금지.

여전히 sandbox 환경 한계로 **"코드에서 버그가 사라졌다"는 증명까지만** 본 세션에서 가능합니다. **"실제 4사 사이트에서 자료가 들어온다"는 증명은 사용자 PC에서 위 §3-3 명령 한 줄씩이 필요**합니다. 이건 어쩔 수 없는 환경 차이고, 그래서 자동화 스크립트와 체크리스트를 미리 만들어 둔 것입니다.

---

## 6. 산출물 위치

- 본 보고서: `devlog/round-S/FINAL-REPORT-비전공자.md`
- 4 fleet 상세 보고서: `devlog/round-S/s-emart-deep-report.md`, `s-homeplus-deep-report.md`, `s-orchestrator-ui-report.md`, `s-verify-live-report.md`, `s-verify-live-probe.md`
- Hotfix 흔적: `packages/crawler-admin/backend/crawlers/marts/{emart,homeplus,lottemart,cocodalin}/crawler.py` 의 `_retry_request` 메소드 (last_resp 반환 패턴)
- E2E 자동화 (사용자 PC 실행용): `scripts/g3_e2e_user_scenario.py`, `scripts/g4_e2e_ai_cycle.py`, `scripts/README_e2e.md`

끝.
