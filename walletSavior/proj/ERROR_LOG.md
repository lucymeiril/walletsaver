# 오류 기록 (Error Log)

> 모든 오류, 잘못된 접근, 삽질 내용을 기록한다.
> AI가 새 세션을 시작하면 이 파일을 먼저 읽는다.
> 같은 실수를 반복하지 않기 위한 프로젝트 기억 장치.

---

## [2026-03-18] Windows 콘솔 cp949 인코딩 깨짐

- **증상**: `crawl_demo.py` 실행 시 콘솔에 이모지와 한글이 출력되지 않음. `UnicodeEncodeError: 'cp949' codec can't encode character`
- **원인**: Windows PowerShell 기본 인코딩이 cp949이며, 이모지(U+1F6E1 등)는 cp949에 없는 유니코드 문자
- **잘못된 접근**: `chcp 65001 && python ...` → PowerShell은 `&&` 구문을 지원하지 않아 ParseError 발생
- **해결**:
  1. sys.stdout을 UTF-8 TextIOWrapper로 래핑: `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")`
  2. 환경변수로 실행: `$env:PYTHONIOENCODING='utf-8'; python crawl_demo.py`
  3. 이모지를 ASCII 대체 텍스트로 변경 (🔍 → `[알구몬]`)
- **교훈**: Windows 콘솔은 UTF-8이 기본이 아니다. 한국어 프로젝트에서 콘솔 출력 시 항상 인코딩 처리를 명시하라. 이모지는 가능하면 피하거나 fallback을 준비하라.

---

## [2026-03-18] requests 한국어 응답 인코딩 자동 추론 실패

- **증상**: 알구몬 크롤링 결과의 JSON에 한국어가 깨짐 (`ê·¸ë£¹ë` 등 모자이크 문자)
- **원인**: `requests` 라이브러리가 HTTP 응답의 Content-Type 헤더에서 charset을 찾지 못하면 `ISO-8859-1`로 추론함. 알구몬은 UTF-8이지만 charset을 명시하지 않아 잘못 추론됨.
- **잘못된 접근**: BeautifulSoup의 파서를 바꾸려 함 → 파서 문제가 아니라 입력 데이터가 이미 깨진 상태
- **해결**: `response.encoding = "utf-8"` 한 줄 추가. `response.text` 접근 전에 encoding을 명시적으로 설정.
- **교훈**: `requests`의 `.text`는 `.encoding` 속성에 의존한다. 한국어 사이트를 크롤링할 때는 **항상** `response.encoding`을 명시적으로 설정하라. `response.apparent_encoding`을 사용하면 chardet이 추론해주지만, 확실할 때는 직접 지정하는 것이 안전하다.

---

## [2026-03-18] PowerShell에서 `&&` 연산자 미지원

- **증상**: `chcp 65001 >nul && python crawl_demo.py` 실행 시 `ParserError: '&&' 토큰은 이 버전에서 유효한 문 구분 기호가 아닙니다`
- **원인**: PowerShell 5.x는 `&&` (pipeline chain operator)를 지원하지 않음. PowerShell 7+ 에서만 지원.
- **해결**: 세미콜론(`;`)으로 구분하거나, `$env:VAR='value'; command` 패턴 사용.
- **교훈**: Windows 환경에서 명령어 체이닝 시 `&&` 대신 세미콜론(`;`)을 사용하라. 또는 `cmd /c "A && B"` 패턴.

---

*이후 오류 발생 시 이 형식에 맞춰 추가 기록*

---

## [2026-03-18] 코코달인 SPA 데이터 수집 실패 (0건 수집)

- **증상**: CocodalinCrawler v1이 HTML 파싱으로 0건 수집. `popular-product-grid` div가 비어 있음.
- **원인**: 코코달인은 SPA가 아닌 전통적 HTML+JS 사이트이지만, 상품 데이터를 JS로 동적 로드함. `__NEXT_DATA__`도 없음.
- **잘못된 접근**: Next.js SPA라고 가정하고 `__NEXT_DATA__` JSON 파싱 시도 → 존재하지 않아 빈 결과
- **해결**: `js/script.js`에서 `g_api_url` 변수 발견 → `https://www.cocodalin.com/api/front/bestLikeProducts` API 직접 호출 → 27개 상품 JSON 수집 성공
- **교훈**: 사이트 구조를 가정하지 말고, JS 파일을 분석해서 실제 API 엔드포인트를 찾아라. SPA라도 결국 어딘가에서 데이터를 fetch한다.

---

## [2026-03-18] 알구몬 크롤러 v1 가격 미추출 (0/20건)

- **증상**: AlgumonCrawler v1이 20건 수집했으나 가격이 전부 null.
- **원인**: `a[href*='/l/d/']` 링크의 텍스트에는 가격이 없음. 가격은 별도의 `<p class="deal-price-text">` 요소에 표시됨. 소스 커뮤니티도 부모의 괄호 문자열이 아닌 카드 내 텍스트에 포함.
- **잘못된 접근**: 링크 텍스트에서 가격 정규식 추출 시도 → 링크 텍스트에 가격 없어서 null
- **해결**: `.deal-card-content` 카드 단위로 파싱. `.deal-price-text`에서 가격 추출. 알려진 커뮤니티 이름 매칭으로 소스 추출 → 18/20건 가격 추출 성공
- **교훈**: 크롤러 작성 전에 실제 HTML 구조를 분석하라. 셀렉터의 텍스트에 원하는 데이터가 있을 것이라 가정하지 말고, DOM 계층 전체를 파악하라.
