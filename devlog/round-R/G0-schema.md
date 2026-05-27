# G0 — 4사 통합 스키마 합본 (Round R)

본 문서는 4사 정찰(`G0-emart.md`, `G0-homeplus.md`, `G0-lottemart.md`, `G0-costco.md`) 결과를 합쳐 **G1에서 즉시 적용할 신 스키마**를 확정한 것이다. G1 코드 작업 슬롯들은 이 문서를 단일 진실로 사용한다.

## 1. 4사 식별자·URL 패턴 요약표

| 마트 | 안정 상품 URL | `mart_native_code` 추출 방식 | 카테고리 URL | 외부셀러 |
|---|---|---|---|---|
| 이마트 | `/item/itemView.ssg?itemId=<13>&siteNo=7009&salestrNo=<n>` | `itemId` 쿼리 파라미터 (13자리) | `/disp/category.ssg?dispCtgId=<n>` | 있음 — `cdtl_ico_item` 라벨/`salestrNo` 분포로 플래그 |
| 홈플러스 | `/item?itemNo=<9>&storeType=HYPER\|EXP` | `itemNo` 쿼리 파라미터 (9자리) | `/list?categoryDepth=<n>&categoryId=<n>` | 있음 — 사이드바 "매직배송 vs 판매자택배" |
| 롯데마트 | `/products/OS<EAN-13>/details` | URL의 `OS` 뒤 EAN-13 = 바코드, **최강 식별자** | XHR `/api/webproductpagews/...` payload | 없음(대체로) |
| 코스트코 | `/<Path>/<Slug>/p/<번호>` | `/p/` 뒤 숫자 | `/c/cos_<a.b.c>` (점 구분 계층) | 없음(전부 직매입) |

**원칙**: 위 표의 URL이 "안정"이라는 뜻은 **시즌/주차에 따라 바뀌지 않는다는 뜻**이지 영구 보장은 아님. 따라서 URL은 식별자가 아니라 표시·이동용이며, `mart_native_code`(사이트 내부 안정 코드)와 `canon_hash`(브랜드+정규화명+팩) 이중 키로 영구 식별한다.

## 2. 신 스키마 — 상품 테이블 컬럼 (db-admin/storage/models.py 갱신 대상)

```python
# 핵심 식별자
mart                       # 'emart' | 'homeplus' | 'lottemart' | 'costco'
mart_native_code           # 사이트 내부 안정 코드 (롯데는 EAN-13, 코스트코는 /p/숫자, 이마트 itemId, 홈플 itemNo)
canon_hash                 # SHA1(brand|normalized_name|pack_qty|pack_unit) — 마트 횡단 매칭용
source                     # 마트명 자동 주입 (= mart 값, 사이트가 안 주므로 크롤러가 채움)

# 표시/이동
canonical_url              # 클릭 가능한 안정 URL (롯데는 /products/OS<EAN>/details 형식 강제)
tracking_url               # 사이트 자체 추적용 URL (있을 때만, 식별자로 안 씀)

# 카테고리
mart_native_category_id    # 사이트 원본 카테고리 ID (예: 코스트코 cos_10.1)
mart_native_category_path  # 사이트 원본 카테고리 경로 텍스트 (예: '식품 > 쌀/잡곡')
unified_category_id        # G2에서 매핑 후 채움. G1에선 null 허용.

# 가격
price                      # 정상가
sale_price                 # 할인가 (없으면 = price)
unit_price                 # 사이트 노출 환산가 (식품만 채움)
unit_price_basis           # '100g' | '10g' | '100ml' | '10ml' | '개' 등 — 마트별 다르므로 raw 보존
observed_at                # 크롤 시각 (UTC)

# 팩 정보
pack_qty                   # 수량 (예: 5700)
pack_unit                  # 'g' | 'ml' | '개' | '봉' | '마리' | '단' | '망' | '팩' | 'kg' | 'L'
pack_count                 # 묶음 개수 (예: 18개입이면 18, 단품은 1)

# 분류
external_seller            # bool — 자체상품 false, 외부 셀러 true. 디폴트 false. 코스트코·롯데는 전부 false.
brand                      # 추출 가능 시
normalized_name            # 정규화된 상품명 (대괄호 태그·행사 마크 제거, 공백·대소문자 정규화)
raw_name                   # 원본 상품명 보존

# 메타
crawled_at                 # 크롤 시각
mart_internal_seller_id    # 외부셀러 식별용 (이마트 salestrNo 등, 추적/디버깅용)
```

## 3. 가격 시계열 — `price_history` (신설)

```python
# 같은 캐노니컬 상품(mart_native_code 또는 canon_hash 기준)의 주간 누적
class PriceHistory:
    mart                # FK
    canon_key           # mart_native_code 우선, 없으면 canon_hash
    observed_at         # UTC, 일자
    price
    sale_price
    unit_price
    period_start        # 행사기간 시작 (있으면)
    period_end          # 행사기간 종료 (있으면)
    source_run_id       # 어떤 크롤 런에서 왔는지 추적
```

UNIQUE(mart, canon_key, observed_at) — 같은 날 같은 상품 중복 방지. 주간 1회 크롤 가정. 첫 주 가격 시그널은 **현재가 4사 비교 + 코코달린 시드(코스트코 한정)**.

## 4. 핫딜 DB 분리

- 별도 alembic head로 분리. 모델 모듈도 `storage/hotdeals_models.py`로 분리.
- 크롤러 측에서 마트와 다른 입력 채널(알구몬 등)의 스키마 차이 큼: 출처 사이트, 만료시간, 추천수, 댓글수 등 마트 모델과 합치면 NULL 컬럼 폭증.
- 라운드 R G1에서 헤드 분리만 끝내고 실제 핫딜 크롤러는 G5-b.

## 5. 단위환산가 정규식 (4사 공통 파서)

```python
# source_utils.py
UNIT_PRICE_RE = re.compile(
    r'(?P<basis>\d+)\s*(?P<unit>g|ml|kg|L)\s*당\s*(?P<price>[\d,]+)\s*원',
    re.IGNORECASE
)
# 매칭 케이스
#   이마트: "10g 당 314원"
#   홈플:   "10G당 200원"
#   롯데:   사이트 표시 형식 (G1에서 확정)
#   코스트코: "100g당 400원"
```

`unit_price_basis`는 raw 그대로 보존 ('10g', '100g' 등). 횡단 비교는 G2에서 100g 또는 100ml 기준으로 정규화한 view 컬럼/계산 함수 별도.

## 6. 외부셀러 처리 (옵션 B 플래그)

- 이마트: `cdtl_ico_item` 라벨 + `salestrNo=7009`(자체) 분포 확인 → `external_seller` 계산. 추정 실패 시 false 보수적 기본.
- 홈플러스: 사이드바·카드 라벨에서 "매직배송"/"새벽배송"/"판매자택배" 식별 → "판매자택배" = true.
- 롯데/코스트코: 디폴트 false.

웹 프론트는 기본 `external_seller=false`만 노출, 토글로 외부 표시 가능.

## 7. URL 정규화 헬퍼 (G1 source_utils)

```python
def normalize_lottemart_url(raw, ean13_or_code) -> str:
    # 죽은 UUID 경로 거부, OS+EAN-13 강제
    return f"https://lottemartzetta.com/products/OS{ean13_or_code}/details"

def normalize_emart_url(item_id, store_no='7009', salestr_no=None) -> str:
    base = f"https://emart.ssg.com/item/itemView.ssg?itemId={item_id}&siteNo={store_no}"
    return base + (f"&salestrNo={salestr_no}" if salestr_no else "")

def normalize_homeplus_url(item_no, store_type='HYPER') -> str:
    return f"https://mfront.homeplus.co.kr/item?itemNo={item_no}&storeType={store_type}"

def normalize_costco_url(path_with_slug, p_number) -> str:
    return f"https://www.costco.co.kr{path_with_slug}/p/{p_number}"
```

## 8. G1 마이그레이션 계획 (alembic 새 헤드)

1. 상품 테이블에 신 컬럼 추가 (위 #2). 기존 행은 nullable로 받아두고 크롤 재시작 시 채움.
2. `price_history` 테이블 신설.
3. 핫딜 DB 분리 — 별도 메타 헤드.
4. 카테고리 매핑 테이블 골격 (G2에서 사용) 미리 생성 — `mart_native_category` + `unified_category` + `mapping`.
5. 다운그레이드 경로 작성 강제 (롤백 안전망).

## 9. 크롤러-admin 프론트 동시 갱신 (M6)

신 필드 표시·진행률 0초 멈춤 금지:
- 상품 리스트 그리드: `mart_native_code`, `mart_native_category_path`, `unit_price`+`unit_price_basis`, `external_seller` 컬럼 노출.
- 크롤 진행률: "마트별 진행/완료/오류" + "신규/중복/필터된 건수" 실시간.
- 오류 단계 표시 (timeout/parse/dedup).

## 10. web 프론트 동시 갱신 (M6)

- 마트 탭: 4사 할인 카드. 카드 단위환산가는 식품만, 비식품은 pack 정보.
- 물가비교 탭: **진입 시 최상위 카테고리만**. 잎새 상품 노출 금지(현재 버그). 클릭 드릴다운 → 최하위에서 4사 묶음.
- 가격 히스토리 모달: 박스 그래프. 첫 주는 코스트코만 (코코달린 시드), 다른 마트는 "아직 누적 중" 안내 — 모달 자체는 안 깨지게.

## 11. G1 슬롯 분배 (4 에이전트 병렬)

- A1 — 이마트 크롤러 전면 재작성 + 카테고리 수집
- A2 — 홈플러스 크롤러 재작성 + 메인몰/익스프레스 분리 + 동적 스크롤 3중 안전망
- A3 — 롯데마트 크롤러 수정 (UUID 코드 삭제, OS+EAN 추출, __INITIAL_STATE__.data 안정 키)
- A4 — 코스트코 크롤러 + 코코달린 시드 임포트
- 메인 — db-admin/storage/models.py + alembic 헤드 + crawler-admin/web 프론트 신 필드 + source_utils.py 공통 헬퍼
