# Round R fix-name-normalize Report

## 변경 요약
- `packages\db-admin\backend\services\name_normalize.py`와 `packages\crawler-admin\backend\crawlers\marts\source_utils.py`의 프로모션 마커 제거 정규식을 동일하게 강화했다.
- `compute_canon_hash()`는 기존 SHA1 payload 공식은 유지하고, hash 전 `normalize_name_core()`를 반드시 거친다.
- shared normalize 헬퍼는 별도 패키지에서 발견되지 않아 기존 두 위치의 동작을 일관되게 맞췄다.

## 추가/보강된 마커
- 괄호형: `[행사]`, `[1+1]`, `[NEW]`, `[한정]`, `【한정】`, `<특가>`, `(NEW)`, `(신상)`, `(EVENT)`, `{신상}`, `{한정}`
- 별표형: `★무배★`, `★특가★`
- 단독형: `행사상품`, `신상품`, `한정판매`, `1+1`, `2+1`
- 공백: 다중 공백을 단일 공백으로 축약하고 앞뒤 구분자를 trim
- 옵션: `normalize_name_core(..., fold_case=True)`로 영문 대소문자 무시 가능

## Before / After 예시
| 입력 | name_core | canon_hash |
| --- | --- | --- |
| `테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `[행사] 테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `[1+1] 테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `(NEW) 테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `{신상} 테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `【한정】 테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `<특가> 테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `★무배★ 테스트 우유 1L` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `테스트 우유 1L 행사상품` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |
| `테스트 우유 1L 2+1` | `테스트 우유 1L` | `30d7232ae1e0e44f60a88ddb69361a486d0f0bb9` |

## 테스트 결과
```powershell
cd packages\db-admin\backend; py -3 -m pytest tests\test_unmatched_isolation.py::test_case_b_name_variant_keeps_stable_canon_hash -q
# 1 passed, 2 warnings

cd packages\crawler-admin\backend; py -3 -m pytest tests\test_source_utils_g1.py -q
# 16 passed
```
