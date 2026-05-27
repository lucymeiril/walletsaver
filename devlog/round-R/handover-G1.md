# Handover — G1 진입 (2일 데드라인)

## 직전 게이트(G0) 완료 상태
- 4사 정찰 끝: emart/homeplus/lottemart/costco md + 캡쳐 (`devlog/round-R/captures/G0-*.png`)
- 통합 스키마 합본 작성: `devlog/round-R/G0-schema.md` (G1 단일 진실)
- 핵심 결정 — `mart_native_code`+`canon_hash` 이중 키, URL은 식별자 아님, 외부셀러는 플래그(옵션 B), 핫딜 DB 분리 G1 묶음, 코스트코는 코코달린 시드.

## G1 진입 — 4 슬롯 병렬 분배

### A1 — 이마트 크롤러 전면 재작성
- 파일: `packages/crawler-admin/backend/crawlers/marts/emart/crawler.py`
- 작업:
  - 기존 `__NEXT_DATA__` 가정 **전면 삭제** (실제 페이지에 없음 — G0 정찰 확인)
  - 카테고리 페이지 `/disp/category.ssg?dispCtgId=<n>`에서 CSR 렌더 대기 후
    `a[href*="itemView.ssg"]` 카드 수집
  - `itemId`(13자리) + `siteNo` + `salestrNo` 파싱, `mart_native_code = itemId`
  - `cdtl_ico_item` 라벨과 `salestrNo` 분포로 `external_seller` 플래그 계산
  - 단위환산가 "10g 당 314원" 정규식(`source_utils.UNIT_PRICE_RE`) 적용, 식품만
  - 카테고리 트리 별도 수집 → `mart_native_category_id` + `mart_native_category_path`

### A2 — 홈플러스 크롤러 재작성
- 파일: `packages/crawler-admin/backend/crawlers/marts/homeplus/crawler.py`
- 작업:
  - `mfront.homeplus.co.kr/list?categoryDepth=N&categoryId=N`(HYPER) + `/express`(EXP) 분리 수집
  - 동적 스크롤 3중 안전망: (a) 품목수 5회 연속 불변 (b) 끝 마커 DOM (c) XHR 빈 응답. 2/3 만족 시 종료.
  - `/item?itemNo=<9>&storeType=HYPER|EXP`로 캐노니컬 URL 정규화
  - 사이드바 "매직배송 vs 판매자택배" 텍스트로 `external_seller` 계산
  - 단위환산가 "10G당 200원" 정규식
  - 내부 라우팅 href(`/p/expfreedlvr` 등)는 식별자 금지 — 캐노니컬 URL만 저장
  - 카테고리 트리 별도 수집

### A3 — 롯데마트 크롤러 수정
- 파일: `packages/crawler-admin/backend/crawlers/marts/lottemart/crawler.py`
- **버그 원점**: 1108-1111줄 `data-synthetics="product-id:<uuid>"` 추적용 UUID를 URL로 만들고 있음 → 죽은 URL.
- 작업:
  - UUID 추출 코드 삭제
  - 상품 페이지 `__INITIAL_STATE__.data`에서 안정 코드(EAN-13 추정) 추출
  - `mart_native_code = EAN-13`, 캐노니컬 URL은 `/products/OS<EAN-13>/details` 강제
  - 882줄 `product_id`/`url` 추출 우선순위 재조정
  - 외부셀러 대체로 없음 (디폴트 false)
  - 카테고리 페이로드 XHR 분석 (`/api/webproductpagews/...`)

### A4 — 코스트코 크롤러 + 코코달린 시드
- 파일: `packages/crawler-admin/backend/crawlers/marts/costco/crawler.py`(없으면 신설), `marts/cocodalin/` 활용
- 작업:
  - 카테고리: `/c/cos_<a.b.c>` 점 구분 계층 — 최상위 17개(`cos_1` ~ `cos_23`) 트리화
  - 상품: `a[href*="/p/"]`에서 `/p/<번호>` 추출 → `mart_native_code`
  - 단위환산가 "100g당 400원" 정규식
  - 비로그인으로 가격 노출 확인됨
  - `external_seller`는 전부 false
  - **코코달린 시드 임포트 파이프라인**: 코스트코 `mart_native_code`(= `/p/번호`)를 키로 매칭, `price_history`에 과거 할인 내역 backfill

### 메인 슬롯 — DB/프론트/마이그레이션
- `packages/db-admin/backend/storage/models.py` — 신 컬럼 추가 (G0-schema #2 참조)
- alembic 새 헤드 — 상품 컬럼 + `price_history` + 핫딜 DB 분리 + 카테고리 매핑 골격
- `packages/crawler-admin/backend/crawlers/marts/source_utils.py` — URL 정규화 헬퍼 4종, 단위환산가 파서, 외부셀러 플래그 헬퍼, `source` 자동 주입
- `packages/crawler-admin/frontend` — 신 필드 컬럼 노출, 크롤 진행률 0초 멈춤 제거 (M6)
- `packages/db-admin/frontend` — 신 필드 그리드, 카테고리 트리 뷰어 골격(G2 사용)
- `packages/web/frontend` — 마트 탭 카드(단위환산가 노출), 물가비교 탭 진입 시 최상위 카테고리만 노출(잎새상품 노출 버그 제거)

## 게이트 합격 증거 (M5 — 4종 강제)
1. **코드 diff** — A1~A4 + 메인 5개 PR/커밋 묶음
2. **DB 덤프 스니펫** — `sqlite3` SELECT로 신 컬럼 채워진 4사 각 5건 이상 (`mart_native_code`, `canon_hash`, `unit_price`, `external_seller`, `mart_native_category_path`)
3. **3축 캡쳐**:
   - crawler-admin 프론트: 진행률 카운터 + 신규/중복/필터 카운터 + 신 필드 컬럼
   - db-admin 프론트: 신 컬럼 그리드 + 4사 상품 표시
   - web 프론트: 마트 탭 카드 + 물가비교 탭 최상위 카테고리(잎새 X)
4. **재현 명령어** — DB wipe → 4사 크롤 → DB 덤프 → 프론트 캡쳐 한 줄 묶음

## cross-cut 후보 (G1 중 떠오르면 즉시 처리)
- 카테고리 트리 캡쳐 export 도구 — G2 직전에 필요. G1에 끼워서 함께 export하면 G2 시작 즉시 사용 가능.
- 신 필드 미설정 시 마이그레이션 다운그레이드 경로 — 안전망.

## 산출물 경로 인덱스
- `devlog/round-R/G0-emart.md`, `G0-homeplus.md`, `G0-lottemart.md`, `G0-costco.md`
- `devlog/round-R/G0-schema.md` (G1 단일 진실)
- `devlog/round-R/captures/G0-*.png` (정찰 스크린샷)
- `devlog/round-R/handover-G0.md` (이전 게이트 인계)
- 이 파일: `devlog/round-R/handover-G1.md`

## 다음 슬롯이 집어들 것
- 메인 슬롯이 먼저 `source_utils.py` + `models.py` + alembic 헤드를 만들어 A1~A4가 의존할 공용 기반을 깐다. 그 다음 A1~A4 병렬 발진.
