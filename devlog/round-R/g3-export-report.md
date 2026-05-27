# Round R G3-2 Unmatched Export Report

## 산출물
- 신규 서비스: `packages\db-admin\backend\services\unmatched_isolation.py`
  - A: 선택 주차에 처음 관측된 `mart + mart_native_code`.
  - B: `[행사]`, `[1+1]`, `(NEW)`, `【한정】`, `신상품`, `EVENT` 등 휘발성 마커 제거 후 `name_core`가 달라지는 이름 변형.
  - C: `unified_category_id IS NULL`이고 `mart_category_mappings`에 native category 매핑이 없는 항목.
  - D: 현재 주 가격이 직전 관측 주 대비 `<= 0.5x` 또는 `>= 1.5x`인 가격 오기 의심.
- 신규 정규화 유틸: `packages\db-admin\backend\services\name_normalize.py`
  - 마커 토큰 제거 기반 `normalize_name_core()`와 name_core 기반 `compute_canon_hash()`를 제공한다.
- 크롤러 헬퍼 보강: `packages\crawler-admin\backend\crawlers\marts\source_utils.py`
  - 동일한 마커 제거 로직을 `compute_canon_hash()` 입력에 반영해 `[행사]` 같은 접두/접미 변경에도 hash가 안정적으로 유지된다.
- Export 통합: `packages\db-admin\backend\services\external_ai_export.py`
  - 기존 `unclassified.jsonl` 외에 `case_a_new_native_code.jsonl`, `case_b_name_variant.jsonl`, `case_c_unmapped_native_category.jsonl`, `case_d_price_suspicious.jsonl`을 생성한다.
  - `manifest.json`에 케이스별 count와 추천 처리 방식을 추가했다.
- CLI: `scripts\g3_export_unmatched.py`
  - `py -3 scripts\g3_export_unmatched.py --out artifacts\g3-unmatched-bundle`로 번들 폴더를 출력한다.
- API: `POST /api/admin/unmatched/export`
  - admin 권한으로 unmatched bundle을 만들고 zip 파일로 다운로드한다.

## 케이스 분류 결과
- Case A는 선택 주차의 `price_history.week_of`에 존재하지만 이전 주차 가격 이력이 없는 상품으로 격리한다.
- Case B는 raw name에서 행사/신상 마커가 제거될 때 별도 파일로 내보내며, 재계산 hash와 기존 `canon_hash` 일치 여부를 `canon_hash_stable`로 표시한다.
- Case C는 native category가 매핑 테이블에 없어 자동 카테고리 부여가 실패한 상품을 외부 AI/매핑 보강 대상으로 격리한다.
- Case D는 이전 관측 가격 대비 50% 이상 하락 또는 50% 이상 상승한 상품을 가격 검수 대상으로 격리한다.

## 검증
```powershell
cd packages\db-admin\backend; py -3 -m pytest tests\test_unmatched_isolation.py tests\test_auto_classify.py tests\test_external_ai_export.py -q
```
결과: `12 passed, 34 warnings`.

## 알려진 한계
- Case A의 “처음 본” 판단은 DB에 남아 있는 `price_history` 기준이다. 과거 이력이 삭제된 상품은 신규로 보일 수 있다.
- Case D는 가장 가까운 이전 관측 주와 비교한다. 정확히 직전 주 데이터가 없으면 마지막 과거 주와 비교한다.
- 마커 제거 정규식은 보수적 패턴 기반이다. 새로운 프로모션 표기가 생기면 `_MARKER_WORDS` 보강이 필요하다.
