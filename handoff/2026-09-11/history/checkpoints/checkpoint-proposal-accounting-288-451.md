# WalletSaver proposal accounting checkpoint — pending 288~451

## 기준

- 기준 브랜치: `cleanup/remove-legacy-ai-admin-coupling`
- 기준 pass: `pass41`
- 기준 pending 관측: 3,916
- 기존 explicit review decision: 431
- 이 작업은 GitHub read/write 기반 회계 정리이며 DB/운영 반영이 아니다.
- `bulk-pending-288-451-final-sweep.json`의 ordered classification sweep 자체는 이미 완료되어 있다.

## 이번에 확정한 288~451 회계

- final sweep가 읽은 관측: **281**
- 이미 classification resolved여서 분류 진척에서 제외한 관측: **15**
- final sweep가 classification-pending으로 재검토한 관측: **266**
- ordered sweep 이전 proposal_only가 이미 덮고 있던 전체 관측: **253**
- 그 253 중 이미 classification resolved인 15관측을 제외한 legacy classification-review overlap: **238**
- 따라서 final sweep의 실제 고유 신규 classification 검토: **28**
- 계산: `266 - 238 = 28`

### 왜 238인가

PENDING_INDEX의 288~404는 그룹당 2관측, 405~451은 그룹당 1관측이라 전체가 281관측이다.

ordered sweep 이전 proposal들의 `reviewed_pending_groups`와 raw observation 범위를 합집합으로 대조하면 288~451 중 legacy proposal이 이미 덮은 그룹은 정확히 다음과 같다.

- `289~291`
- `305~451`

즉 150개 그룹, 253관측이다. 그 안에서 final sweep가 이미 분류 완료로 제외한 그룹은 `289, 308, 354, 382, 389, 399, 432, 433, 451`이고 합계가 15관측이다. 따라서 실제 classification-review overlap은 238관측이다.

반대로 legacy proposal에 없었던 그룹은 정확히 다음 14개뿐이다.

- `288`
- `292~304`

이들은 모두 그룹당 2관측이므로 28관측이다.

## 28개 unique-new 관측의 원본 식별자

| pending | source_record_key | raw_record_ids |
|---|---|---|
| 288 | `149806813` | `ingestion:2:32`, `ingestion:51:27` |
| 292 | `071295244` | `ingestion:18:43`, `ingestion:67:26` |
| 293 | `071035628` | `ingestion:17:27`, `ingestion:66:71` |
| 294 | `071396465` | `ingestion:11:95`, `ingestion:61:37` |
| 295 | `070904535` | `ingestion:10:3`, `ingestion:59:34` |
| 296 | `071195708` | `ingestion:9:84`, `ingestion:59:25` |
| 297 | `138313382` | `ingestion:10:37`, `ingestion:59:62` |
| 298 | `122624764` | `ingestion:11:78`, `ingestion:61:19` |
| 299 | `101423045` | `ingestion:11:87`, `ingestion:61:28` |
| 300 | `071402995` | `ingestion:11:94`, `ingestion:61:36` |
| 301 | `071386039` | `ingestion:12:6`, `ingestion:61:48` |
| 302 | `071426811` | `ingestion:10:46`, `ingestion:60:29` |
| 303 | `069804919` | `ingestion:6:57`, `ingestion:56:1` |
| 304 | `105116704` | `ingestion:15:49`, `ingestion:64:87` |

## 431 explicit review decision 충돌 검사

위 14개 `source_record_key`를 `review-decisions-input.json`의 431개 explicit decision과 exact-key로 대조했다.

- exact match: **0**
- 따라서 위 28관측은 explicit decision 선행 일치 때문에 추가로 제외할 필요가 없다.
- existing explicit review decision 파일은 수정하지 않았다.

## proposal evolution 충돌 발견

회계 중 첫 proposal과 final sweep의 판단이 달라진 사례를 확인했다.

### pending 313

- 제목: `농심 생생 우동 용기 276G`
- 기존 `homeplus-noodles-canned-311-316.json`: `food.meals.noodles.cup_ramen`
- final `bulk-pending-288-451-final-sweep.json`: title-first override로 `food.meals.noodles.udon`

이 항목은 final sweep를 자동 우선하지 않는다. **첫 판단과 최종 판단의 충돌로 hold**하고, 전체 duplicate proposal의 first-vs-final 비교를 마친 뒤 승격 여부를 정한다.

## 중요한 해석

- `+266`을 과거 누적 검토 수에 더하면 안 된다.
- 이번 정리로 확정된 것은 **288~451 final sweep의 고유 신규 증분이 +28**이라는 점이다.
- `checkpoint-after-pending-287.md`의 2,165 역시 역사적 회계값으로 남겨야 하며, 001~287 구간의 legacy/bulk proposal 중복을 전역 dedupe하기 전에는 이를 최종 unique-reviewed total로 쓰지 않는다.
- 따라서 지금도 3,916 pending이 DB에서 감소했다고 표현하면 안 된다.

## 생성한 파일

- `handoff/2026-09-11/proposals/reconciliation-pending-288-451.json`
- 이 체크포인트 파일

두 파일 모두 회계/제안 문서이며 importer 입력이나 운영 승인 파일이 아니다.

## 실행하지 않은 것

- staging SQLite import/rebuild
- proposal -> explicit review decision 승격
- catalog rebuild
- taxonomy 코드 수정
- `verify_initial_stage.py`
- pytest / 회귀 테스트
- 멱등 import 검사
- 새 pass DB 생성

## 다음 재개점

1. pending `001~287`에 대해 proposal_only의 `raw_record_id` / `source_record_key` 합집합을 같은 방식으로 전역 dedupe한다.
2. 같은 observation이 여러 proposal에 있을 때 최초/최종 leaf 또는 hold 판단을 비교하고 충돌표를 만든다. pending 313은 이미 첫 충돌로 기록했다.
3. 그 후에만 `unique reviewed / hold / already-classified-only / non-classification-only` 최종 회계를 게시한다.
4. 실행 가능한 환경에서 승인된 항목만 explicit review decision으로 승격하고 새 pass를 재구축한다.
