# 크롤러 플러그인 개발 가이드

## 목차
1. [개요](#개요)
2. [빠른 시작](#빠른-시작)
3. [플러그인 구조](#플러그인-구조)
4. [plugin.yaml 작성](#pluginyaml-작성)
5. [크롤러 구현](#크롤러-구현)
6. [PluginInterface 활용](#plugininterface-활용)
7. [테스트 작성](#테스트-작성)
8. [배포](#배포)
9. [FAQ](#faq)

---

## 개요

WalletSavior 크롤러 플러그인 시스템은 새 크롤러를 **코드 수정 없이** 추가할 수 있게 설계되었다.

핵심 원칙:
- **독립성**: 플러그인은 서로 의존하지 않는다 (명시 선언 제외)
- **자동 발견**: `plugin.yaml`이 있는 폴더가 자동으로 등록된다
- **에러 격리**: 하나의 플러그인 오류가 다른 플러그인에 영향을 주지 않는다
- **핫 리로드**: 서버 재시작 없이 플러그인을 교체할 수 있다

---

## 빠른 시작

### 1. 디렉토리 생성

```
packages/crawler-admin/backend/crawlers/hotdeals/my-crawler/
├── __init__.py
├── crawler.py
├── plugin.yaml
├── tests/
│   └── test_crawler.py
└── README.md
```

### 2. plugin.yaml 작성

```yaml
name: my-crawler
display_name: 내 크롤러
category: hotdeal
version: 1.0.0
description: "내 크롤러 설명"
target:
  url: https://example.com/deals
  difficulty: 2
  strategy: requests
schedule:
  cron: "0 6 * * *"
  retry_count: 3
  retry_delay: 300
output:
  model: HotdealPost
  required_fields: [title, url]
dependencies: []
```

### 3. 크롤러 구현

```python
from core.contracts.crawler import CrawlerContract
from core.models import CrawlerInfo, CrawlerGroup, CrawlResult, CrawlStatus, HotdealPost

class MyCrawler(CrawlerContract):
    @property
    def info(self) -> CrawlerInfo:
        return CrawlerInfo(
            name="my-crawler",
            version="1.0.0",
            group=CrawlerGroup.HOTDEAL,
            target_url="https://example.com/deals",
            strategies=["requests"],
        )

    async def crawl(self) -> CrawlResult:
        # 크롤링 로직
        ...

    async def parse(self, raw_data: str) -> list[dict]:
        # 파싱 로직
        ...

    async def validate(self, items: list[dict]) -> list[dict]:
        # 검증 로직
        ...
```

### 4. 테스트 실행

```bash
cd E:\pdf\capston01\walletSavior
py -m pytest packages/crawler-admin/backend/crawlers/hotdeals/my-crawler/tests/ -v
```

끝! 서버가 다음 번에 플러그인 스캔을 하면 자동으로 등록된다.

---

## 플러그인 구조

```
crawlers/{category}/{name}/
├── __init__.py          # 패키지 마커
├── crawler.py           # CrawlerContract 구현 (필수)
├── parser.py            # 파싱 로직 분리 (선택)
├── plugin.yaml          # 플러그인 메타데이터 (필수)
├── tests/
│   ├── test_crawler.py  # 크롤러 테스트
│   └── fixtures/        # 테스트 HTML/JSON 파일
└── README.md            # 문서
```

---

## plugin.yaml 작성

### 필수 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `name` | string | 플러그인 고유 이름 (영문, 소문자) |
| `version` | string | semver 형식 (`1.0.0`) |

### 선택 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `display_name` | string | 표시 이름 (한글 OK) |
| `category` | string | `mart`, `hotdeal`, `food`, `delivery`, `shopping`, `government`, `location`, `public` |
| `description` | string | 설명 |
| `author` | string | 작성자 |
| `target.url` | string | 대상 URL |
| `target.difficulty` | int | 난이도 1~5 |
| `target.strategy` | string | 기본 크롤링 전략 |
| `schedule.cron` | string | cron 표현식 |
| `schedule.retry_count` | int | 재시도 횟수 |
| `schedule.retry_delay` | int | 재시도 간격 (초) |
| `output.model` | string | 출력 모델 (`DiscountItem`, `HotdealPost`) |
| `output.required_fields` | list | 필수 출력 필드 |
| `dependencies` | list | 의존 플러그인 이름 |

---

## 크롤러 구현

### CrawlerContract (기본)

`CrawlerContract`는 필수 인터페이스이다:

- `info` (property) — 크롤러 메타 정보
- `crawl()` — 크롤링 실행
- `parse(raw_data)` — 원본 데이터 파싱
- `validate(items)` — 데이터 유효성 검증
- `setup()` — 초기화 (선택)
- `teardown()` — 정리 (선택)

### PluginInterface (확장)

라이프사이클 훅과 메트릭이 필요하면 `PluginInterface`를 사용한다:

```python
from plugins.plugin_interface import PluginInterface

class MyCrawler(PluginInterface):
    def __init__(self):
        super().__init__()  # 반드시 호출

    async def on_load(self):
        await super().on_load()
        # 리소스 초기화

    async def on_unload(self):
        await super().on_unload()
        # 리소스 해제

    async def on_error(self, error):
        await super().on_error(error)
        # 에러 알림
```

---

## PluginInterface 활용

### 상태 확인

```python
health = plugin.get_health()
print(health.is_healthy)        # True/False
print(health.consecutive_failures)  # 연속 실패 횟수
```

### 메트릭 조회

```python
metrics = plugin.get_metrics()
print(metrics.success_rate)     # 0.0 ~ 1.0
print(metrics.avg_duration_seconds)
print(metrics.total_items_collected)
```

### 설정 접근

```python
config = plugin.get_config()    # plugin.yaml 내용
version = plugin.get_version()  # 버전 문자열
deps = plugin.get_dependencies()  # 의존 플러그인 목록
```

---

## 테스트 작성

### PluginTestFramework 사용

```python
from plugins.test_framework import PluginTestFramework

framework = PluginTestFramework(my_crawler)

# 인터페이스 준수 검사
result = framework.check_compliance()
assert result.is_compliant

# CrawlResult 스키마 검증
crawl_result = await my_crawler.crawl()
errors = PluginTestFramework.validate_crawl_result(crawl_result)
assert not errors

# Mock HTML로 오프라인 테스트
html = PluginTestFramework.get_mock_html("simple")
items = await my_crawler.parse(html)

# 벤치마킹
bench = await framework.benchmark_parse(html, iterations=10)
print(f"평균 {bench.avg_seconds:.4f}초/회")
```

### 건강 상태 검사 (PluginInterface용)

```python
health_report = framework.check_health(my_plugin)
assert health_report["all_passed"]
```

---

## 배포

1. 플러그인 폴더를 `crawlers/{category}/{name}/`에 복사
2. `plugin.yaml` 검증:
   ```python
   from plugins.plugin_loader import PluginLoader
   loader = PluginLoader([Path("crawlers/")])
   loader.discover()
   errors = loader.validate_config(config)
   ```
3. 테스트 통과 확인
4. 서버가 자동으로 발견하거나, 핫 리로드:
   ```python
   manager = PluginManager()
   await manager.reload_plugin("my-crawler")
   ```

---

## FAQ

### Q: 새 플러그인 추가 시 서버를 재시작해야 하나?
A: 아니다. `PluginManager.reload_plugin()`으로 핫 리로드할 수 있다.

### Q: 다른 플러그인에 의존할 수 있나?
A: `plugin.yaml`의 `dependencies`에 선언하면 의존 플러그인이 먼저 로드된다.

### Q: 플러그인 하나가 에러를 내면 다른 것도 멈추나?
A: 아니다. 에러 격리가 적용되어 다른 플러그인은 정상 동작한다.

### Q: CrawlerContract와 PluginInterface 중 무엇을 쓰나?
A: 단순 크롤러는 `CrawlerContract`, 라이프사이클/메트릭이 필요하면 `PluginInterface`를 사용한다.
