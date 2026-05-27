# G0 정찰 — 코스트코 (costco.co.kr)

## 핵심 발견
- 비로그인 상태에서도 상품 가격·단위환산가 모두 노출. **회원/지역 의존성은 없음** (적어도 정찰용 데이터 수집에는). 추후 매장별 재고/배송은 회원 필요할 수 있음.
- 외부 입점 셀러 없음 — 모두 코스트코 직매입. `external_seller` 분류 단순(전부 false).

## URL 패턴 / 안정 식별자
- 카테고리: `/c/cos_<숫자.숫자.숫자>` — 점 구분 계층 코드. 예: `cos_10` = 식품, `cos_10.1` = 쌀/잡곡, `cos_1.5.3` = All Mac.
- 상품: `/<EnglishPath>/<ProductSlug>/p/<숫자>` — 예: `/Foods/RiceGrains/Rice/kimhwa-Nonghyup-Cheolwon-Odae-Rice-10kg/p/686497`
- **`mart_native_code` = `/p/` 뒤 숫자** (예: `686497`). 안정 식별자.

## 단위 환산가
- "100g당 400원" 형식으로 카테고리 페이지·상품 페이지 모두 노출. 다른 마트와 같은 정규식으로 추출 가능.

## 카테고리 트리 — 식품군
- 식품 최상위: `cos_10`
- 하위 일부: `cos_10.1` 쌀/잡곡 등 — G1에서 풀 트리 수집.

## 코코달린(cocodalin) 연동
- `packages/crawler-admin/backend/crawlers/marts/cocodalin/`에 이미 디렉토리 있음 — 활용해서 코스트코 상품의 **과거 할인 내역 시드** import.
- 매칭 키 = `mart_native_code` (=`/p/` 뒤 숫자) 우선, fallback으로 (상품명) 정규화 매칭.

## G1에서 해야 할 액션 (코스트코 슬롯)
1. 카테고리 트리는 메인 홈 페이지의 `a[href^="/c/cos_"]` 전부 수집해 트리화.
2. 상품 리스트 페이지에서 `/p/<번호>`로 끝나는 URL 카드 수집, 단위환산가 정규식 추출.
3. 외부셀러 처리는 불필요 (모두 false 디폴트).
4. 코코달린 import 파이프라인 별도 todo로 분리 (`cocodalin-seed`).
