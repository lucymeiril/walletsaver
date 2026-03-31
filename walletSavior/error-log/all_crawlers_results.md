# 전체 크롤러 테스트 결과 (2025-07-28)

## 요약

| 카테고리 | 전체 | 성공 | SPA 제한 | 차단/비활성 |
|---------|------|------|---------|-----------|
| 핫딜    | 7    | 5    | 0       | 2         |
| 쇼핑    | 3    | 0    | 3       | 0         |
| 배달    | 3    | 0    | 0       | 3         |
| 마트    | 4    | 2    | 2       | 0         |
| **합계** | **17** | **7** | **5** | **5** |

## 핫딜 크롤러 (crawlers/hotdeals/)

| 크롤러 | 상태 | 수집 | 전략 | 비고 |
|--------|------|------|------|------|
| ✅ 뽐뿌 (ppomppu) | SUCCESS | 26건 | requests | 안정 작동 |
| ✅ FM코리아 (fmkorea) | SUCCESS | 15건 | cloudscraper | Cloudflare 우회 필요 |
| ✅ 클리앙 (clien) | SUCCESS | 31건 | requests | 안정 작동 |
| ✅ 퀘이사존 (quasarzone) | SUCCESS | 30건 | requests | 안정 작동 |
| ⚠️ 아카라이브 (arca) | SUCCESS | 0건 | cloudscraper | Cloudflare 강력 차단 — Playwright 필요 |
| ✅ 알구몬 (algumon) | SUCCESS | 20건 | requests | 안정 작동 |
| ❌ 코코달 (cocodal) | FAILED | 0건 | - | 사이트 접속 불가 (비활성) |

### 핵심 수정 사항
- **anti_detect.py**: `Accept-Encoding` 헤더에서 `br` (brotli) 제거 → `requests` 라이브러리가 brotli 압축을 해제하지 못하는 문제 해결. 퀘이사존·에펨코리아 등 다수 크롤러 정상화.
- **fmkorea/crawler.py**: `cloudscraper`를 우선 시도하도록 변경 → 일반 `requests`는 15KB 축소 HTML만 반환.

## 쇼핑 크롤러 (crawlers/shopping/)

| 크롤러 | 상태 | 수집 | 제한 사항 |
|--------|------|------|----------|
| ⚠️ 무신사 (musinsa) | PARTIAL | 0건 | Next.js SPA — API 404, HTML에 상품 데이터 없음 |
| ⚠️ 유니클로 (uniqlo) | PARTIAL | 0건 | Fast Retailing SPA — API 404, JS 렌더링 필요 |
| ⚠️ 지오다노 (giordano) | PARTIAL | 0건 | Cafe24 SPA — HTML 1.2KB 셸만 반환 |

### 제한 사항
- 3개 쇼핑몰 모두 SPA(Single Page Application)로 전환됨
- HTTP 요청만으로는 상품 데이터 수집 불가
- **해결 방안**: Selenium/Playwright 기반 브라우저 자동화 전략 추가 필요

## 배달 크롤러 (crawlers/delivery/)

| 크롤러 | 상태 | 수집 | 제한 사항 |
|--------|------|------|----------|
| ⚠️ 배달의민족 (baemin) | PARTIAL | 0건 | 앱 API 인증 토큰 필요 |
| ⚠️ 쿠팡이츠 (coupangeats) | PARTIAL | 0건 | 주소 설정 + JS 챌린지 필요 |
| ⚠️ 요기요 (yogiyo) | PARTIAL | 0건 | 위치 기반 API, 인증 필요 |

### 제한 사항
- 배달앱 3종 모두 모바일 앱 API 기반으로 웹 공개 정보가 극히 제한적
- **해결 방안**: 앱 API 리버스 엔지니어링 또는 Selenium 기반 웹 크롤링

## 마트 크롤러 (crawlers/marts/)

| 크롤러 | 상태 | 수집 | 전략 | 비고 |
|--------|------|------|------|------|
| ✅ 이마트 (emart) | SUCCESS | 44건 | requests | SSG __NEXT_DATA__ JSON 추출 |
| ⚠️ 롯데마트 (lottemart) | PARTIAL | 0건 | requests | lottemartzetta.com SPA 전환 |
| ⚠️ 홈플러스 (homeplus) | PARTIAL | 0건 | requests | mfront.homeplus.co.kr SPA 전환 |
| ✅ 코코달인 (cocodalin) | SUCCESS | 28건 | requests (API) | 직접 JSON API 접근 |

### 핵심 수정 사항
- **lottemart/crawler.py**: SPA 리다이렉트 감지 로직 추가 (lottemartzetta.com)
- **homeplus/crawler.py**: SPA 셸 감지 로직 추가 (mfront.homeplus.co.kr)

## 파이프라인 (pipeline/)

| 모듈 | 상태 | 비고 |
|------|------|------|
| ✅ dedup.py (HotdealDeduplicator) | 정상 | URL 정규화 + 제목 유사도(Jaccard) + 가격 비교 |

### 테스트 결과
- 입력 3건 → 출력 3건 (유사하지만 다른 제목은 중복으로 판정되지 않음)
- Union-Find 기반 그룹핑 정상 작동

## 근본 원인 분석

### brotli 인코딩 문제 (핵심)
- `engine/anti_detect.py`의 `Accept-Encoding: gzip, deflate, br` 헤더가 원인
- `requests` 라이브러리는 brotli 압축을 네이티브로 지원하지 않음 (`brotli` 패키지 미설치)
- 서버가 brotli로 응답 → 압축 해제 실패 → 깨진 HTML → 파싱 결과 0건
- **수정**: `br`/`zstd` 제거 → `gzip, deflate`만 사용

### SPA 전환 트렌드
- 2025년 기준 대부분의 대형 이커머스/마트 사이트가 SPA로 전환
- HTTP 요청만으로는 서버 사이드 렌더링된 데이터를 가져올 수 없음
- Next.js, Cafe24, Fast Retailing 등 프레임워크별 대응 전략 필요

## 향후 개선 방향

1. **Playwright 전략 추가**: `engine/strategies/playwright_st.py`를 활성화하여 SPA 크롤링 지원
2. **brotli 패키지 설치**: `pip install brotli` → `Accept-Encoding: br` 복원 가능
3. **배달앱 API 연구**: 모바일 앱 트래픽 분석으로 API 엔드포인트 확보
4. **롯데마트/홈플러스**: Playwright로 전단지 페이지 렌더링 후 상품 추출
5. **아카라이브**: Playwright + stealth 플러그인으로 Cloudflare 우회
