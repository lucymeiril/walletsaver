# 008: 좀비 프로세스, API 불일치, 네이버 스텔스 수정

**날짜**: 2026-03-31  
**작업자**: AI Agent (Copilot)  
**브랜치**: feature/monorepo-restructure  
**커밋**: 0b343f4

---

## 요약

"되는 게 하나도 없다"는 사용자 피드백에 대응. 근본 원인은 **좀비 워커 프로세스**가 구 코드를 서빙하고 있었던 것. 이를 해결하고 모든 API 불일치를 수정, 네이버 지도 검색을 Playwright 스텔스 모드로 완전 재구현.

## 해결한 문제들

### 1. 좀비 프로세스 (근본 원인)
- **증상**: 코드를 수정해도 서버 응답이 변하지 않음
- **원인**: `uvicorn --reload`의 WatchFiles가 Windows cmd.exe에서 "Terminate batch job (Y/N)?" 프롬프트를 유발 → 부모 reloader는 죽지만 자식 worker는 살아남아 구 코드 서빙
- **해결**: `--reload` 제거, `cmd.exe /c npm run dev` → `npx.cmd vite --port XXXX`로 교체
- **교훈**: Windows + WatchFiles + cmd.exe 조합은 프로세스 라이프사이클이 꼬임. 개발 시 수동 재시작이 더 안전

### 2. 커뮤니티 글쓰기 401
- **원인**: `get_current_user` 의존성이 필수였음 (토큰 없으면 401)
- **해결**: Optional 의존성으로 변경, 토큰 없으면 게스트 허용

### 3. DB-Admin 307 리다이렉트
- **원인**: FastAPI router `prefix="/keywords"` + endpoint `"/"` = 경로가 `/api/keywords/`인데, 프론트에서 `/api/keywords` (슬래시 없이) 요청
- **해결**: client.js 모든 URL에 trailing slash 추가

### 4. 네이버 지도 검색
- **원인 1**: httpx 직접 호출 → 네이버 봇 감지로 400/404/429/captcha
- **원인 2**: Playwright async API → Windows ProactorEventLoop에서 `NotImplementedError`
- **원인 3**: 바닐라 headless Playwright → 네이버 봇 감지 ("검색 결과가 없습니다")
- **해결**: Playwright **동기** API를 `ThreadPoolExecutor`에서 실행 + 스텔스 설정:
  - `--disable-blink-features=AutomationControlled`
  - `navigator.webdriver = undefined`
  - 실제 Chrome UA, viewport, locale, timezone, geolocation
  - 내부 allSearch API 응답 인터셉트

### 5. 기타 수정
- Keywords.jsx: `toLocaleString()` crash → null guard
- plugin.yaml: `required_fields` 스키마 불일치
- pipeline.py: `schedule.get()` → `isinstance` 체크
- CommunityPage.jsx: `link:` → `url:` 필드명
- dbAdminStore.js: 카테고리 id 자동 생성

## 테스트 결과
| 기능 | 상태 | 상세 |
|------|------|------|
| 커뮤니티 글쓰기 | ✅ | 200, 게스트 허용 |
| 키워드 등록 | ✅ | 201 |
| 카테고리 등록 | ✅ | 201 |
| 이마트 크롤러 | ✅ | 44 items, quality=1.0 |
| 네이버 검색 | ✅ | 5개 실제 맛집 결과 |
| 인제스천 큐 | ✅ | 12 entries |
| 분석 API | ✅ | 16 products, 110 keywords |

## 설계 결정
1. **`--reload` 영구 제거** — 개발 편의보다 안정성 우선. 코드 변경 시 수동 재시작.
2. **httpx 폴백 제거** — 네이버 대상으로는 무의미. Playwright만 사용.
3. **ThreadPoolExecutor** — Windows asyncio 한계 우회. max_workers=2로 리소스 관리.
4. **Trailing slash 통일** — FastAPI 기본 동작에 맞춤. 모든 프론트엔드 URL에 `/` 추가.
