# Handover — G0 정찰 (진입 시점)

> 이 파일은 세션 compaction 대비. 누가 이 라운드를 다시 잡든 이 파일만 보면 복원 가능해야 한다.

## 현재 위치
- 라운드 R, 게이트 **G0 정찰** 진입.
- 데드라인 D-2 (이틀 뒤 서비스 발표).

## 작업 분업 결정 (중요)
- **Playwright MCP는 이 세션에만 묶임** → 서브에이전트에 분배 불가.
- 결정: G0 정찰은 **내(메인)가 직접 4사 순차 실행**. G1부터는 4 에이전트 병렬.
- 캡쳐는 `devlog/round-R/captures/G0-<mart>-<topic>.png` 규약으로 저장.

## G0 정찰 체크리스트 (마트별 공통)
1. 자체상품 vs 외부셀러 식별 DOM/마커
2. `__NEXT_DATA__` 또는 SSR 상태/XHR 페이로드 실제 구조
3. 사이트가 노출하는 **단위 환산가** 셀렉터
4. 마트 네이티브 카테고리 트리 (엔드포인트/페이지)
5. 영구 식별자 (mart_native_code) 노출 위치 — URL이 아닌 안정 식별자
6. 캐노니컬 URL (실제 클릭 가능한 안정 URL) 형태

## 마트별 추가 항목
- 이마트: `cdtl_ico_item` 마커, 새벽배송/주간배송/트레이더스 자체상품 하위 라벨
- 홈플러스: `delivery=HYPER_DRCT` vs `/express`, 동적 스크롤 종료 시그널, 내부 href→캐노니컬 해상도
- 롯데마트: `/products/<UUID>` vs `/products/OS..../details`, 영속 vs 임시 판별
- 코스트코: 회원/지역 의존성, 가격 단위(개당/g당), 코코달린 데이터 매칭 키

## 진행 상태
- [ ] 이마트 — 진행 중부터
- [ ] 홈플러스
- [ ] 롯데마트
- [ ] 코스트코
- [ ] G0 스키마 합본 → `devlog/round-R/G0-schema.md`

## 다음 슬롯이 집어들 것
- G0 끝나는 즉시 G1 크롤러 4사 재작성 4 에이전트 살포 준비.
- 동시 진행 가능 todo: 코코달린 데이터 임포트 파이프라인 조사 (별도 슬롯).

## 산출물 경로
- 플랜: `C:\Users\user\.copilot\session-state\913765bb-7b27-4d22-920d-56ef8d11ec22\plan.md`
- 캡쳐: `devlog/round-R/captures/`
- 크로스컷: `devlog/round-R/cross-cut/`
- 보고: `devlog/round-R/G{n}-report.md`, 최종은 `FINAL-report.md`
