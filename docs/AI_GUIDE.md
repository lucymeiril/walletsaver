# AI_GUIDE.md — AI 작업 규칙서 (Living Document)

> **이 문서의 목적**: AI의 외장 장기 기억 장치.
> 세션이 날아가도, 새 AI가 투입되어도, 이 문서 체계만 읽으면 이전 맥락 그대로 이어서 작업 가능해야 한다.
> **이 프로젝트의 기획은 미완성이다.** AI는 개발하면서 부족한 기획을 스스로 채우고, 결정을 내리고, 문서를 업데이트한다.

---

## 1. 프로젝트 온보딩 순서

AI가 이 프로젝트에 처음 투입되면 아래 순서로 문서를 읽어야 한다:

### 1.1 필수 읽기 (매 세션 시작 시)

1. **`AI_GUIDE.md`** (이 문서) — 작업 규칙, 문서 관리 프로토콜, 금지 사항
2. **`STATUS.md`** — 현재 무엇이 완료/진행/미착수인지 (가장 빈번히 바뀜)
3. **`INVARIANTS.md`** — 절대 바뀌면 안 되는 것 vs 바꿔도 되는 것
4. **`devlog/` 최신 항목** — 직전 세션에서 무엇을 했는지, 다음에 뭘 해야 하는지
5. **`ERROR_LOG.md`** — 과거 발생한 문제와 해결책 (같은 실수 반복 금지)

### 1.2 필요 시 참조

6. **`TECH_SPEC.md`** — 전체 프로젝트 설계 (목표, 아키텍처, DB, API, Phase 계획)
7. **`ARCHITECTURE.md`** — 모듈 의존성 그래프, 데이터 흐름, DB 스키마
8. **`DEV_PHILOSOPHY.md`** — 11가지 개발 철학
9. **`GLOSSARY.md`** — 도메인 용어 사전
10. **`DECISIONS.md`** — AI가 자율적으로 내린 결정 이력 (사람이 리뷰/오버라이드)
11. **`TECH_DECISIONS.md`** — 기술 스택 선택 근거

---

## 2. 디렉터리 & 파일 배치 규칙

### 2.1 모듈별 역할과 파일 위치

| 디렉터리 | 역할 | 의존 가능 대상 | 절대 금지 |
|-----------|------|----------------|-----------|
| `core/` | 인터페이스, 모델, 이벤트, 예외 **정의만** | 없음 (최하위) | 구현체 코드 넣기 |
| `core/contracts/` | ABC 인터페이스 | `core/models` | 구현 로직 |
| `engine/` | 크롤링 전략 실행기, 진단, 안티봇 | `core/` 만 | `crawlers/`, `storage/`, `api/` import |
| `engine/strategies/` | 5-전략 구현체 | `core/`, `engine/anti_detect` | 크롤러별 로직 |
| `crawlers/` | 사이트별 크롤러 플러그인 | `core/` 만 | `engine/`, `storage/` import |
| `storage/` | DB, 파일 저장소 구현 | `core/` 만 | `engine/`, `crawlers/` import |
| `api/` | FastAPI 라우트 | `core/` 만 | `engine/`, `crawlers/` 직접 import |
| `scheduler/` | APScheduler 래핑 | `core/` 만 | 다른 모듈 직접 import |
| `utils/` | 범용 유틸리티 | 없음 | 비즈니스 로직 |
| `tests/` | core 테스트 | 모든 모듈 (테스트이므로) | 프로덕션 코드에 영향 |
| `frontend-react/` | Vite + React 18 앱 | 독립 (Python 무관) | Python import |

### 2.2 새 파일 생성 규칙

```
새 크롤러 추가 시:
  crawlers/{그룹}/{사이트명}/
    ├── __init__.py
    ├── crawler.py      ← CrawlerContract 구현
    ├── parser.py       ← parse 로직 분리 (선택)
    └── README.md       ← 대상 사이트 분석 노트

새 전략 추가 시:
  engine/strategies/{전략명}_st.py

새 API 라우트 추가 시:
  api/routes/{도메인}.py

새 테스트 추가 시:
  {모듈}/tests/test_{대상}.py     (모듈 내부 테스트)
  tests/test_{대상}.py            (core 테스트)
```

---

## 3. 코드 컨벤션

### 3.1 언어 규칙

| 항목 | 규칙 | 예시 |
|------|------|------|
| **docstring** | 한국어 | `"""핫딜 가격이 평균을 오염시키지 않도록 이상치를 제거한다."""` |
| **주석** | 한국어, **의도 중심** | `# 같은 UA 반복 시 핑거프린팅에 걸리므로 매 요청마다 교체` |
| **로그 메시지** | 한국어 | `logger.info("크롤러 레지스트리: 미구현")` |
| **변수/함수명** | 영문 snake_case | `crawl_delay_min`, `get_random_headers()` |
| **클래스명** | 영문 PascalCase | `StrategyExecutor`, `CrawlerContract` |
| **상수** | 영문 UPPER_SNAKE | `CRAWL_STARTED`, `USER_AGENTS` |
| **Enum 값** | 영문 lowercase | `CrawlStatus.PENDING = "pending"` |
| **파일명** | 영문 snake_case | `anti_detect.py`, `crawl_pipeline.py` |
| **에러 메시지** | 한국어 (사용자 노출) / 영문 (내부 디버그) | 상황에 따라 |
| **커밋 메시지** | 한국어 or 영문 (일관성 유지) | — |

### 3.2 import 순서

```python
# 1) 표준 라이브러리
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

# 2) 서드파티
from pydantic import BaseModel, Field

# 3) core (자체 프로젝트 최하위)
from core.contracts.engine import StrategyContract
from core.models import CrawlResult, CrawlStatus
from core.exceptions import CrawlError
from core.events import EventBus, CRAWL_STARTED

# 4) 같은 패키지 내부
from engine.anti_detect import AntiDetect
```

### 3.3 타입 힌트

- **모든 함수**에 파라미터 + 리턴 타입 힌트 필수
- `from __future__ import annotations` 파일 최상단에 추가 (PEP 604 `X | Y` 사용 가능)
- Pydantic 모델은 `core/models.py`에 정의, 로컬 모델 금지

### 3.4 주석 & docstring 철학: "기능이 아니라 의도를 써라"

**핵심 원칙**: AI의 컨텍스트는 언제든 날아간다. 3개월 뒤 새 AI가 이 코드를 보고
"이게 뭘 하는 코드지?"가 아니라 **"왜 이렇게 만들었지? 어디에 쓰는 거지?"**를
이해할 수 있어야 한다.

#### ❌ 나쁜 주석 (기능을 반복)

```python
# 딜레이 적용
delay = self._anti_detect.get_random_delay()

# 사용자 에이전트를 가져온다
ua = self.get_random_user_agent()

def remove_outliers_iqr(prices):
    """IQR 방식으로 이상치를 제거한다."""
```

#### ✅ 좋은 주석 (의도를 전달)

```python
# 봇 탐지 회피: 요청 간 인간처럼 불규칙한 간격을 둬야 차단 안 당함
delay = self._anti_detect.get_random_delay()

# 같은 UA를 반복 사용하면 핑거프린팅에 걸리므로 매 요청마다 교체
ua = self.get_random_user_agent()

def remove_outliers_iqr(prices):
    """
    핫딜이나 입력 오류로 들어온 비정상 가격을 평균 산출에서 제외한다.
    
    왜 필요한가:
        마트 크롤링 시 "1원 이벤트" 같은 이상치가 섞이면
        평균가가 왜곡되어 "지금 비싼가?" 판단을 망친다.
        IQR(사분위범위)로 극단값을 걸러내야 baseline 신뢰도가 유지된다.
    
    어디서 쓰이나:
        statistics.compute_stats() → 이 함수 → 정제된 리스트 → 평균/중간값 산출
    """
```

#### docstring 작성 규칙

```python
class StrategyExecutor:
    """
    크롤링 전략을 가벼운 것부터 순서대로 시도하고, 하나라도 성공하면 즉시 반환한다.
    
    왜 이런 구조인가:
        대형마트 사이트마다 봇 차단 수준이 다르다.
        이마트는 requests로 되지만, 코스트코는 Playwright까지 가야 한다.
        매번 무거운 브라우저를 띄우면 느리니까, 가벼운 것부터 시도하고
        실패하면 자동으로 다음 단계로 넘어가는 cascade 구조.
    
    어디서 쓰이나:
        container.py에서 초기화 → 각 크롤러 플러그인이 crawl() 안에서 호출
        또는 main.py CLI의 "crawl" 명령에서 직접 실행
    
    의존:
        core/contracts, core/events만 — engine 내부는 core 외 아무것도 모름
    """
```

#### 주석이 필요한 곳 / 필요 없는 곳

| 상황 | 주석 필요? | 쓸 내용 |
|------|:---:|---------|
| 복잡한 비즈니스 로직 | ✅ | **왜** 이 로직이 필요한지, **어떤 문제**를 풀고 있는지 |
| 워크어라운드/핵 | ✅ | **왜** 정석이 아닌 방법을 썼는지, 원래 어떻게 해야 하는지 |
| 비직관적인 상수/임계값 | ✅ | 이 숫자가 **어디서 나온 건지** (예: "KAMIS 기준", "실측치") |
| 외부 API 호출 | ✅ | **왜** 이 API를 쓰는지, 응답 형식 특이사항 |
| 이름만으로 의도가 명확한 코드 | ❌ | `get_random_user_agent()`는 이름이 곧 설명 |
| 단순 CRUD | ❌ | 과도한 주석은 노이즈 |

### 3.5 에러 처리 패턴

```python
# 올바른 패턴: CrawlError로 래핑
try:
    return await self._do_fetch(url, **options)
except CrawlError:
    raise  # 이미 CrawlError면 그대로 전파
except Exception as e:
    raise CrawlError(
        str(e),
        error_type=ErrorType.UNKNOWN,
        strategy_name=self.name,
    ) from e

# 이벤트 핸들러 내 에러는 전파 금지 (EventBus._safe_call 패턴)
try:
    await handler(event)
except Exception as e:
    logger.error(f"이벤트 핸들러 오류: {handler.__name__}: {e}", exc_info=True)
```

---

## 4. 테스트 규칙

### 4.1 TDD 사이클

1. **Red**: 실패하는 테스트를 먼저 작성
2. **Green**: 테스트를 통과시키는 최소한의 코드 작성
3. **Refactor**: 중복 제거, 구조 개선

### 4.2 테스트 파일 위치

```
core 관련    → tests/test_*.py
engine 관련  → engine/tests/test_*.py
crawlers 관련 → crawlers/{그룹}/{사이트}/tests/test_*.py
storage 관련 → storage/tests/test_*.py
api 관련     → api/tests/test_*.py
scheduler    → scheduler/tests/test_*.py
```

### 4.3 테스트 작성 규칙

```python
# 마커 필수
@pytest.mark.unit
async def test_executor_cascade_on_failure(event_bus):
    """첫 번째 전략 실패 시 두 번째 전략으로 cascade한다."""
    # Given
    ...
    # When
    result = await executor.execute(url)
    # Then
    assert result.status == CrawlStatus.SUCCESS

# 네이밍: test_{대상}_{시나리오}_{기대결과}
# 예: test_executor_all_strategies_fail_returns_failed
# 예: test_diagnosis_ip_banned_highest_severity
```

### 4.4 테스트 실행

```bash
# 전체 테스트
pytest

# 특정 마커
pytest -m unit
pytest -m "not slow"

# 커버리지
pytest --cov=core --cov=engine --cov-report=term-missing
```

### 4.5 Fixture 활용

- 공용 fixture는 `conftest.py`에 정의 (event_bus, sample_crawler_info 등)
- 모듈별 fixture는 해당 모듈의 conftest.py에

---

## 5. 절대 금지 사항

### 5.1 아키텍처 위반 금지

| 금지 | 이유 |
|------|------|
| `core/`에 구현 코드 넣기 | core는 인터페이스/모델/이벤트 정의만 |
| `container.py` 외에서 concrete class import | DI 원칙 위반 |
| 모듈 간 직접 의존 (예: crawlers → engine) | 순환 의존 & 커플링 발생 |
| `config.py` 직접 import (container.py 제외) | 설정은 DI로 주입 |
| 전역 상태(global variable) 사용 | 테스트 격리 불가 |

### 5.2 데이터 무결성 금지

| 금지 | 이유 |
|------|------|
| 핫딜 가격을 baseline 평균에 포함 | "가격 오염" — 핫딜은 참고 전용 |
| 속성 태그 없이 가격 비교 | 냉동 삼겹살 ≠ 냉장 삼겹살 (가격 2~5배 차이) |
| 원본 텍스트(raw_text) 삭제 | 디버깅 & 사후 검증에 필수 |

### 5.3 코드 품질 금지

| 금지 | 이유 |
|------|------|
| 테스트 없이 구현 코드 머지 | TDD 원칙 위반 |
| `print()` 디버깅 남기기 | `logger` 사용 |
| 하드코딩된 URL/API 키 | `.env` + `config.py`로 관리 |
| `# TODO` 없이 미구현 코드 남기기 | 추적 불가 |

---

## 6. 📋 문서 생명주기 프로토콜 (Document Lifecycle Protocol)

**핵심 원칙: 문서 = AI의 장기 기억. 코드를 바꾸면 문서도 바꾼다.**

### 6.1 작업 중 필수 문서 업데이트 트리거

| 이벤트 | 업데이트 대상 | 내용 |
|--------|-------------|------|
| 작업 시작 | `STATUS.md` | 해당 항목 상태를 🔄 진행중으로 변경 |
| 작업 완료 | `STATUS.md` | 해당 항목 상태를 ✅ 완료로 변경, 테스트 수 갱신 |
| 에러 발생 & 해결 | `ERROR_LOG.md` | 증상/원인/해결/교훈 기록 (번호 이어서) |
| 기획에 없던 결정을 내림 | `DECISIONS.md` | 결정 내용, 근거, 대안, 리스크 기록 |
| 새 모듈/파일 추가 | `ARCHITECTURE.md` | 의존성 그래프나 디렉터리 구조 갱신 |
| 모델/인터페이스 변경 | `TECH_SPEC.md` | 해당 섹션 갱신 |
| 새 용어/개념 등장 | `GLOSSARY.md` | 용어 추가 |
| 불변 규칙 위반 가능성 발견 | `INVARIANTS.md` | 조건부 변경 섹션에 메모 추가 |
| 의미 있는 작업 단위 완료 | `devlog/NNN_*.md` | 세션 핸드오프용 개발 일지 작성 |
| 세션 종료 직전 | `devlog/NNN_*.md` | **반드시** 핸드오프 노트 작성 (Section 7 참조) |

### 6.2 문서 업데이트 우선순위

세션 중 시간이 부족할 때 (컨텍스트 한계 근접 등):

```
반드시: devlog 핸드오프 노트 > STATUS.md > ERROR_LOG.md
가능하면: DECISIONS.md > ARCHITECTURE.md
나중에: GLOSSARY.md > TECH_SPEC.md
```

### 6.3 문서 일관성 규칙

- 문서 간 모순이 발견되면 **즉시 수정** (어떤 문서가 최신인지 날짜로 판단)
- 모든 문서 상단에 `마지막 업데이트: YYYY-MM-DD` 유지
- 구조가 크게 바뀌면 ARCHITECTURE.md의 다이어그램도 갱신

---

## 7. 🔄 세션 핸드오프 & 개발 일지 (Session Handoff & Devlog)

**AI의 컨텍스트는 반드시 날아간다.** 세션이 끝나기 전에 "다음 AI를 위한 브리핑"을 남긴다.

### 7.1 개발 일지의 본질: "블로그를 쓰듯이"

devlog는 단순한 체크리스트가 아니다. **개발 블로그를 쓰듯이** 맥락과 의도를 기록한다.
다음 AI가 이 글만 읽고 "아, 이 사람이 무슨 생각으로 이걸 만들었구나, 다음엔 이걸 해야겠다"를
이해할 수 있어야 한다.

기록해야 하는 것:
- **대체 뭐 때문에** 이 작업을 했는지 (동기, 배경)
- **어디에** 코드를 넣었는지 (파일 경로, 모듈)
- **무슨 방법으로** 구현했는지 (접근법, 왜 이 방법을 택했는지)
- **어떻게** 만들었는지 (구현 핵심 포인트, 트릭, 주의사항)
- **시도했다가 실패한 것** (다음 AI가 같은 삽질 안 하도록)
- **발견한 것** (사이트 구조, API 동작, 예상 밖 제약 등)

### 7.2 핸드오프 노트 작성 시점

- 의미 있는 작업 단위가 완료되었을 때
- 세션이 길어져서 곧 끝날 것 같을 때
- 사용자가 작업 중단을 지시했을 때
- 중요한 맥락을 잊으면 안 될 때

### 7.3 devlog 포맷

파일명: `devlog/NNN_{키워드}.md` (번호는 기존 최대 + 1)

```markdown
# NNN. [작업 제목] (YYYY-MM-DD)

## 배경 — 왜 이 작업을 했나

> 이 작업의 동기와 맥락. "TECH_SPEC Phase N의 어떤 기능을 구현하기 위해"
> 또는 "이전 세션에서 X가 안 돼서 Y 방식으로 재시도" 등.
> 다음 AI가 "아 이 맥락이구나" 하고 바로 이해할 수 있게.

## 뭘 했나 — 구현 내용

### [세부 작업 1]
어디에(`파일 경로`) 무엇을(`기능`) 왜 이 방법으로(`접근법 선택 이유`) 만들었는지.
코드의 핵심 포인트, 특이한 부분, 주의사항.

### [세부 작업 2]
...

## 시도했다가 실패한 것

> 이 섹션이 진짜 중요하다. 다음 AI가 같은 삽질을 반복하지 않도록.
- 처음에 A 방식으로 시도 → B 이유로 실패 → 결국 C로 해결

## 발견한 것

- 대상 사이트 구조, API 동작 방식, 예상 밖 제약 등
- "이 사이트는 SPA가 아니라 실은 API가 따로 있더라" 같은 것

## 다음에 할 일

> 다음 AI가 이것만 읽고 바로 이어서 작업할 수 있게 **구체적으로**.
> "프론트 만들기" ✗ → "frontend-react/src/pages/Home.jsx에서 
> mockData.js의 todayDeals를 카드 컴포넌트로 렌더링하기" ✅

1. 구체적 다음 작업 1
2. 구체적 다음 작업 2
3. ...

## Git 상태
- 브랜치: `feature/xxx`
- 마지막 커밋: `커밋 메시지`
- 커밋 안 한 변경: 있음/없음
- PR: 있음 (#번호) / 없음
```

### 7.4 핸드오프 체크리스트

세션 종료 전 반드시 확인:

```
□ devlog 핸드오프 노트 작성했나?
□ STATUS.md가 현재 상태를 정확히 반영하나?
□ 에러가 있었으면 ERROR_LOG.md에 기록했나?
□ 자율 결정이 있었으면 DECISIONS.md에 기록했나?
□ 커밋 안 한 코드 변경이 있나? → 있으면 커밋 또는 stash
□ 브랜치 상태를 devlog에 명시했나?
```

---

## 8. 🌿 Git 워크플로우 (Git Workflow)

### 8.0 원격 저장소

```
GitHub: https://github.com/lucymeiril/walletSavior
origin: https://github.com/lucymeiril/walletSavior.git
브랜치 현황:
  main                            ← 안정 기준
  feature/wallet-guardian-strategy ← 현재 개발 브랜치 (Phase 1~2 완료 코드)
```

### 8.1 브랜치 전략

```
main                    ← 안정 버전만 머지 (PR 필수)
├── develop             ← 개발 통합 브랜치
│   ├── feature/xxx     ← 기능 개발 (Phase 단위 또는 모듈 단위)
│   ├── fix/xxx         ← 버그 수정
│   └── docs/xxx        ← 문서 작업
```

### 8.2 브랜치 네이밍

```
feature/phase3-kamis-crawler       # Phase 단위 기능
feature/storage-postgresql         # 모듈 단위 기능
feature/frontend-home-page         # 프론트엔드 기능
fix/cocodalin-parser-error         # 버그 수정
docs/architecture-update           # 문서 업데이트
```

### 8.3 커밋 규칙

```
[Phase N] 작업 요약

- 구체적 변경 내용 1
- 구체적 변경 내용 2

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

커밋 타이밍:
- **원자적 커밋**: 하나의 논리적 변경 = 하나의 커밋
- 테스트가 통과하는 상태에서만 커밋
- "WIP" 커밋은 feature 브랜치에서만 허용
- 문서 변경은 별도 커밋 (코드 변경과 분리)

### 8.4 Pull Request 규칙

```
PR 제목: [Phase N] 기능 요약
PR 본문:
  ## 변경 사항
  - 무엇을 왜 바꿨는지
  
  ## 테스트
  - pytest 결과 (통과/실패)
  - 수동 검증 내용
  
  ## 문서 업데이트
  - 어떤 문서를 갱신했는지
  
  ## 체크리스트
  - [ ] INVARIANTS.md 제약 준수
  - [ ] 테스트 추가/통과
  - [ ] STATUS.md 업데이트
  - [ ] ERROR_LOG.md 갱신 (에러 있었을 경우)
```

### 8.5 머지 규칙

- `feature/*` → `develop`: 테스트 전체 통과 + 문서 갱신 확인 후 머지
- `develop` → `main`: 안정성 확인 후 머지 (의미 있는 마일스톤 단위)
- 충돌 시: 최신 develop을 feature 브랜치에 머지한 후 해결

### 8.6 Git 작업 순서 (매 세션)

```
1. git pull origin develop          # 최신 코드 가져오기
2. git checkout -b feature/xxx      # 작업 브랜치 생성
3. (코드 작성 + 테스트)
4. git add . && git commit          # 원자적 커밋
5. (반복)
6. git push origin feature/xxx      # 푸시
7. (PR 생성 또는 기존 PR 업데이트)
8. devlog 핸드오프 노트 작성
```

---

## 9. 🤖 AI 자율 판단 가이드라인 (Autonomous Decision Making)

**이 프로젝트의 기획은 미완성이다.** AI는 빈 곳을 발견하면 스스로 판단해서 채운다.

### 9.1 자율 판단 허용 범위

| 판단 유형 | 자율 결정 가능? | 조건 |
|-----------|:---:|------|
| 코드 구현 세부사항 (변수명, 알고리즘 선택) | ✅ 가능 | INVARIANTS 준수 |
| 새 유틸리티 함수/헬퍼 추가 | ✅ 가능 | 배치 규칙 준수 |
| 테스트 케이스 추가 | ✅ 가능 | 항상 환영 |
| 버그 수정 | ✅ 가능 | ERROR_LOG에 기록 |
| 기존 인터페이스에 메서드 **추가** | ⚠️ 조건부 | DECISIONS.md에 기록 후 진행 |
| 새 Pydantic 모델 추가 | ⚠️ 조건부 | core/models.py에, DECISIONS.md 기록 |
| 기획서에 명시되지 않은 새 기능 | ⚠️ 조건부 | DECISIONS.md에 기록 + 사람 리뷰 대기 |
| DB 스키마 변경 | ⚠️ 조건부 | DECISIONS.md + Alembic 마이그레이션 |
| 기존 인터페이스 시그니처 **변경** | ❌ 사람 승인 | INVARIANTS I-rule 위반 가능 |
| 기술 스택 교체 | ❌ 사람 승인 | INVARIANTS I-16~20 해당 |
| 불변 규칙 변경 | ❌ 사람 승인 | 절대 불가 |

### 9.2 자율 결정 시 DECISIONS.md 기록

자율 판단으로 결정을 내렸을 때 반드시 `DECISIONS.md`에 기록:

```markdown
### D-NNN: [결정 제목] (날짜)

**상황**: 왜 결정이 필요했나
**결정**: 무엇을 어떻게 결정했나
**근거**: 왜 이 선택이 최선인가
**대안**: 고려했지만 선택하지 않은 옵션
**리스크**: 이 결정의 잠재적 위험
**되돌림**: 사람이 반대하면 어떻게 원복하나
**상태**: `적용됨` | `사람 리뷰 대기` | `오버라이드됨`
```

### 9.3 기획 빈 곳 발견 시 행동 규칙

```
1. TECH_SPEC.md에 해당 기능 명세가 있나? → 있으면 그대로 구현
2. 없으면: 비슷한 패턴이 기존 코드에 있나? → 있으면 패턴 따라 구현
3. 없으면: INVARIANTS와 DEV_PHILOSOPHY에 부합하는 방향으로 판단
4. 결정 내용을 DECISIONS.md에 기록
5. 커밋 메시지에 "[자율결정]" 접두사 추가
6. 다음 사람 리뷰 시 확인 요청
```

### 9.4 자가 진단 체크리스트

**매 작업 시작 시 AI가 스스로 점검:**

```
□ STATUS.md를 읽었는가? 현재 프로젝트 상태를 파악했는가?
□ 최신 devlog를 읽었는가? 직전 세션의 맥락을 이해했는가?
□ ERROR_LOG.md를 읽었는가? 과거 실수를 반복하지 않을 것인가?
□ 지금 할 작업이 INVARIANTS를 위반하지 않는가?
□ 지금 할 작업에 필요한 선행 작업이 완료되어 있는가?
□ 필요한 문서가 최신 상태인가? 모순은 없는가?
```

**매 작업 종료 시 AI가 스스로 점검:**

```
□ 코드 변경이 있으면 테스트를 추가했는가?
□ pytest가 전부 통과하는가?
□ STATUS.md를 업데이트했는가?
□ 에러가 있었으면 ERROR_LOG.md에 기록했는가?
□ 자율 결정이 있었으면 DECISIONS.md에 기록했는가?
□ 커밋했는가? 브랜치 상태가 깨끗한가?
□ devlog 핸드오프 노트를 작성했는가?
□ 다른 문서에 갱신이 필요한 곳은 없는가?
```

### 9.5 부족한 문서 자발적 보강

AI는 작업 중 다음을 발견하면 능동적으로 문서를 보강한다:

| 발견 | 조치 |
|------|------|
| 코드에는 있지만 문서에 없는 패턴 | ARCHITECTURE.md 또는 AI_GUIDE에 추가 |
| 자주 반복되는 실수 패턴 | ERROR_LOG에 "주의 패턴"으로 기록 |
| TECH_SPEC에 빠진 세부 명세 | TECH_SPEC에 추가 + DECISIONS.md에 근거 기록 |
| 불명확한 용어 | GLOSSARY.md에 추가 |
| 테스트가 없는 기존 코드 발견 | 테스트 추가 (별도 커밋) |
| 새로운 환경 이슈 | AI_GUIDE Section 14에 추가 |

---

## 10. 새 기능 구현 체크리스트

새 기능을 추가할 때 반드시 이 순서를 따를 것:

```
□ 1. STATUS.md에서 현재 상태 확인 (선행 작업 완료 여부)
□ 2. TECH_SPEC.md에서 해당 기능의 Phase/설계 확인
□ 3. INVARIANTS.md에서 불변 제약 확인
□ 4. core/contracts/에 필요한 인터페이스가 있는지 확인 (없으면 추가)
□ 5. core/models.py에 필요한 모델이 있는지 확인 (없으면 추가)
□ 6. Git 작업 브랜치 생성 (feature/xxx)
□ 7. 실패 테스트 먼저 작성 (Red)
□ 8. 구현 (Green)
□ 9. 리팩터링 (Refactor)
□ 10. 전체 테스트 통과 확인 (pytest)
□ 11. STATUS.md 업데이트
□ 12. 에러 발생 시 ERROR_LOG.md에 기록
□ 13. 자율 결정 시 DECISIONS.md에 기록
□ 14. 커밋 + 푸시
□ 15. devlog 핸드오프 노트 작성
```

---

## 11. 크롤러 플러그인 추가 가이드

### 11.1 디렉터리 구조

```
crawlers/{그룹}/{사이트명}/
├── __init__.py
├── crawler.py          # CrawlerContract 구현
├── parser.py           # HTML/JSON 파싱 로직 (선택)
├── selectors.py        # CSS 셀렉터 상수 (DOM 변경 대응용)
├── tests/
│   ├── __init__.py
│   ├── test_crawler.py
│   └── cassettes/      # VCR 녹화 데이터
└── README.md           # 대상 사이트 분석 메모
```

### 11.2 필수 구현

```python
from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult

class EmartCrawler(CrawlerContract):
    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="이마트",
            group=CrawlerGroup.MART,
            description="이마트 전단 할인 상품 수집",
            target_url="https://emart.ssg.com/...",
            strategies=["requests", "cloudscraper"],
        )

    async def crawl(self) -> CrawlResult: ...
    async def parse(self, raw_data: str) -> list[dict]: ...
    async def validate(self, items: list[dict]) -> list[dict]: ...
```

### 11.3 파싱 결과 표준화

- 크롤러가 생산하는 데이터는 반드시 `core/models.py`의 모델로 변환
- 마트 할인 → `DiscountItem` → `.to_product_price()` → `ProductPrice`
- 핫딜 게시판 → `HotdealPost`
- 원본 텍스트는 `raw_text` 필드에 보존

---

## 12. 프론트엔드 작업 규칙

### 12.1 기술 스택

- **빌드**: Vite
- **프레임워크**: React 18 (JSX, 함수형 컴포넌트)
- **상태관리**: Zustand
- **스타일링**: CSS Modules (`*.module.css`)
- **차트**: Recharts
- **HTTP**: Axios
- **라우팅**: React Router v6
- **아이콘**: Lucide React

### 12.2 디렉터리 구조

```
frontend-react/src/
├── components/       # 재사용 가능한 UI 컴포넌트
│   ├── common/       # Button, Card, Modal 등 범용
│   └── domain/       # PriceChart, ProductCard 등 도메인 특화
├── pages/            # 라우트 단위 페이지 컴포넌트
├── stores/           # Zustand 스토어
├── data/             # 목 데이터 (개발용)
├── styles/           # 글로벌 스타일, 디자인 토큰
├── hooks/            # 커스텀 훅
├── utils/            # 유틸리티 함수
└── assets/           # 이미지, 폰트 등 정적 자원
```

### 12.3 컴포넌트 네이밍

- 파일명: PascalCase (`PriceChart.jsx`)
- CSS Module: `PriceChart.module.css`
- 한 파일 = 한 컴포넌트 (예외: 작은 서브컴포넌트는 같은 파일 가능)

---

## 13. 에러 발생 시 ERROR_LOG.md 기록 포맷

에러가 발생하면 반드시 `ERROR_LOG.md`에 아래 포맷으로 추가:

```markdown
---

### N. [에러 제목] (YYYY-MM-DD)

**증상**: 어떤 에러가 발생했는지 (에러 메시지 포함)
**원인**: 왜 발생했는지 (Root Cause Analysis)
**해결**: 어떻게 고쳤는지 (코드 변경 내용 구체적으로)
**교훈**: 앞으로 같은 실수를 피하려면 어떻게 해야 하는지
**재발 방지**: 이 에러를 방지하는 테스트를 추가했는지 (Yes/No + 파일 경로)

**관련 파일**: `파일 경로`
**관련 커밋**: `커밋 해시` (있을 경우)
```

---

## 14. 환경 주의사항 (Windows)

| 문제 | 해결 |
|------|------|
| Console cp949 인코딩 | `sys.stdout` UTF-8 래핑 + PYTHONIOENCODING=utf-8 |
| requests 한글 깨짐 | `response.encoding = "utf-8"` 명시 |
| PowerShell `&&` 미지원 | `;` 세미콜론 사용 또는 `cmd /c "A && B"` |
| 이모지 출력 에러 | ASCII 대체 문자 사용 (로그에서) |
| 경로 구분자 | Windows `\` 사용 (os.path 또는 pathlib 사용 권장) |

> 새 환경 이슈 발견 시 이 표에 추가할 것

---

## 15. 문서 체계 전체 지도

```
┌─ AI가 매 세션 반드시 읽을 것 ─────────────────────────────────┐
│                                                               │
│  AI_GUIDE.md ──→ "어떻게 작업하나" (이 문서)                    │
│  STATUS.md ────→ "지금 뭐가 되어있나" (가장 자주 바뀜)           │
│  INVARIANTS.md → "절대 하지 마" (가드레일)                      │
│  devlog/최신 ──→ "직전 세션에서 뭘 했나" (세션 핸드오프)          │
│  ERROR_LOG.md ─→ "이 실수 반복하지 마"                          │
│                                                               │
├─ 필요 시 참조 ─────────────────────────────────────────────────┤
│                                                               │
│  TECH_SPEC.md ──→ "전체 설계 청사진" (Phase, 아키텍처, 타겟)     │
│  ARCHITECTURE.md→ "모듈 관계, 데이터 흐름, DB, API"              │
│  DEV_PHILOSOPHY.md→ "왜 이렇게 만드나" (11가지 원칙)             │
│  GLOSSARY.md ───→ "이 용어가 뭔 뜻이지?"                        │
│  DECISIONS.md ──→ "AI가 스스로 뭘 결정했나" (사람 리뷰용)         │
│  TECH_DECISIONS.md→ "왜 이 기술을 골랐나"                        │
│                                                               │
├─ 기록 / 이력 ──────────────────────────────────────────────────┤
│                                                               │
│  devlog/NNN_*.md → 개발 일지 (세션별 핸드오프 + 기술 결정)       │
│  ERROR_LOG.md ───→ 오류 발생/해결 이력                          │
│  DECISIONS.md ───→ AI 자율 결정 이력                            │
│                                                               │
└────────────────────────────────────────────────────────────────┘

업데이트 빈도:
  매 작업마다: STATUS.md, devlog
  에러 시: ERROR_LOG.md
  결정 시: DECISIONS.md
  구조 변경 시: ARCHITECTURE.md, TECH_SPEC.md
  가끔: GLOSSARY.md, INVARIANTS.md, AI_GUIDE.md
```
