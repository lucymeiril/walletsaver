# 플러그인 규격서

## 1. 크롤러 플러그인

### 인터페이스
각 크롤러는 `CrawlerContract`를 구현하는 독립 플러그인입니다.

```python
class CrawlerContract(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """크롤러 이름"""
    
    @property
    @abstractmethod
    def category(self) -> str:
        """카테고리 (mart, hotdeal, delivery, shopping, government, location)"""
    
    @property
    @abstractmethod
    def difficulty(self) -> int:
        """크롤링 난이도 (1-5)"""
    
    @abstractmethod
    async def crawl(self) -> CrawlResult:
        """크롤링 실행"""
    
    @abstractmethod
    def parse(self, raw_data: str) -> list[dict]:
        """원시 데이터 파싱"""
    
    @abstractmethod
    def validate(self, items: list[dict]) -> list[dict]:
        """데이터 유효성 검증"""
```

### 디렉토리 구조
```
crawlers/{category}/{name}/
├── __init__.py
├── crawler.py          # CrawlerContract 구현
├── parser.py           # 파싱 로직 (선택)
├── plugin.yaml         # 플러그인 메타데이터
├── tests/
│   ├── test_crawler.py
│   └── fixtures/       # 테스트 데이터
└── README.md           # 크롤러 설명
```

### plugin.yaml 형식
```yaml
name: emart
display_name: 이마트
category: mart
version: 1.0.0
description: 이마트 전단지 및 세일 정보 크롤러
author: walletSavior-team

target:
  url: https://emart.ssg.com
  difficulty: 2
  strategy: cloudscraper

schedule:
  cron: "0 6 * * *"  # 매일 06:00
  retry_count: 3
  retry_delay: 300    # 5분

output:
  model: DiscountItem
  required_fields:
    - name
    - price
    - original_price
    - source_url

dependencies: []
```

### 자동 등록
크롤러 레지스트리가 `crawlers/` 디렉토리를 스캔하여 `plugin.yaml`이 있는 폴더를 자동 등록합니다.
새 크롤러 추가 시 코드 수정 없이 폴더만 추가하면 됩니다.

---

## 2. 웹사이트 사용자 플러그인

### 보안 원칙
- 모든 사용자 플러그인은 **iframe 샌드박스** 내에서 실행
- 외부 URI/API 접근은 iframe 내부에서만 허용
- 메인 사이트 DOM 직접 접근 불가
- postMessage API로만 데이터 교환

### 플러그인 API
```javascript
// 플러그인이 사용할 수 있는 API (postMessage 기반)
const WalletSaviorPlugin = {
  // 데이터 조회 (읽기 전용)
  async getProductPrice(productId) { ... },
  async getHotdeals(filters) { ... },
  async getCategories() { ... },
  
  // UI 커스터마이징
  registerTheme(themeConfig) { ... },
  registerWidget(widgetConfig) { ... },
  
  // 이벤트 구독
  on(event, callback) { ... },
  // events: 'price-update', 'new-hotdeal', 'category-change'
};
```

### 플러그인 매니페스트 (plugin.json)
```json
{
  "name": "dark-mode",
  "display_name": "다크 모드",
  "version": "1.0.0",
  "description": "사이트 전체 다크 모드 적용",
  "author": "user123",
  "permissions": ["theme"],
  "entry": "index.html",
  "icon": "icon.png"
}
```

### 권한 체계
| 권한 | 설명 | 위험도 |
|------|------|--------|
| theme | UI 테마 변경 | 낮음 |
| widget | 위젯 추가 | 낮음 |
| read-products | 상품 데이터 읽기 | 낮음 |
| read-prices | 가격 데이터 읽기 | 낮음 |
| read-hotdeals | 핫딜 데이터 읽기 | 낮음 |
| notifications | 알림 표시 | 중간 |

### 마켓플레이스
- 사용자가 플러그인 업로드/공유
- 별점/리뷰 시스템
- 다운로드 수 기반 인기 순위
- 관리자 검수 후 공개
