# 에러 로그 008: 좀비 프로세스 & API 불일치 & 네이버 봇 감지

**날짜**: 2026-03-31

---

## 에러 1: 좀비 워커 프로세스 (치명적)

**위치**: `start-all.ps1` — uvicorn `--reload` 플래그  
**증상**: 코드를 수정해도 API 응답이 바뀌지 않음. 모든 수정이 무효.  
**원인**:
```
uvicorn --reload 실행 시:
  부모 프로세스 (reloader) → PID 1000
  자식 프로세스 (worker)   → PID 1001 (실제 서빙)

Ctrl+C 또는 "Terminate batch job":
  부모 PID 1000 → 종료됨
  자식 PID 1001 → 살아남음 (고아 프로세스, 구 코드 서빙 지속)

새로 서버 시작:
  새 부모 PID 2000 → 포트 사용 중 에러 또는 다른 포트 바인딩
  고아 PID 1001 → 여전히 8000 포트 점유, 구 코드 서빙
```
**해결**: `--reload` 제거. 개발 시 코드 변경하면 수동으로 서버 재시작.  
**예방**: Windows에서는 `--reload` 사용 금지. `start-all.ps1`에 주석으로 이유 명시.

---

## 에러 2: cmd.exe 캐스케이드 킬

**위치**: `start-all.ps1` — `cmd.exe /c npm run dev`  
**증상**: Ctrl+C 시 "Terminate batch job (Y/N)?" 프롬프트가 뜨고 프로세스가 깔끔하게 종료되지 않음  
**원인**: `cmd.exe /c`가 자체 프로세스 그룹을 만들어 PowerShell의 신호 전달을 방해  
**해결**: `npx.cmd vite --port XXXX`로 직접 실행 (cmd.exe 레이어 제거)

---

## 에러 3: POST /api/posts 401 Unauthorized

**위치**: `packages/website/backend/api/routes/community.py`  
**증상**: 커뮤니티 글쓰기 시 401 에러  
**원인**: `get_current_user` 의존성이 인증 토큰을 필수로 요구. 게스트는 글쓸 수 없음.  
**해결**:
```python
# Before
async def create_post(..., user=Depends(get_current_user)):

# After  
async def create_post(..., user=Depends(get_current_user_optional)):
    author = user.username if user else "guest"
```

---

## 에러 4: POST /api/keywords/ 422 Unprocessable Content

**위치**: `packages/db-admin/frontend/src/api/client.js`  
**증상**: 키워드 등록 시 422 에러  
**원인**: 
1. URL에 trailing slash 누락 → 307 리다이렉트 → POST body 소실
2. 프론트에서 보내는 필드명과 백엔드 스키마 불일치  
**해결**: URL에 trailing slash 추가, 필드 매핑 수정

---

## 에러 5: Keywords.jsx TypeError "Cannot read properties of undefined (reading 'toLocaleString')"

**위치**: `packages/db-admin/frontend/src/pages/Keywords/Keywords.jsx:118`  
**증상**: 키워드 페이지 접근 시 React crash  
**원인**: API 응답의 `created_at` 필드가 undefined인 키워드 존재  
**해결**: `(item.created_at || '').toLocaleString()` null guard 추가

---

## 에러 6: Playwright NotImplementedError on Windows

**위치**: `packages/website/backend/api/routes/naver_local.py`  
**증상**: 네이버 검색 시 `NotImplementedError` 발생  
**원인**: Python 3.13 Windows에서 기본 이벤트 루프가 `ProactorEventLoop`. Playwright async API가 내부적으로 `asyncio.create_subprocess_exec()` 호출 → ProactorEventLoop에서 미지원.
```python
# 실패하는 코드
async with async_playwright() as p:
    browser = await p.chromium.launch()  # NotImplementedError!
```
**해결**: Playwright **동기** API를 `ThreadPoolExecutor`에서 실행:
```python
_executor = ThreadPoolExecutor(max_workers=2)

def _search_sync(query, lat, lng):  # 동기 함수
    with sync_playwright() as p:
        browser = p.chromium.launch(...)
        ...

async def search_endpoint(...):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _search_sync, ...)
```

---

## 에러 7: 네이버 봇 감지

**위치**: `packages/website/backend/api/routes/naver_local.py`  
**증상**: httpx/requests로 네이버 API 호출 시 400/404/429/captcha. 바닐라 Playwright도 "검색 결과가 없습니다" 반환.  
**원인**: 네이버의 다층 봇 감지:
- User-Agent 검증
- `navigator.webdriver` 속성 체크
- Blink automation 기능 감지
- 요청 빈도 제한  
**해결**: Playwright 스텔스 설정:
```python
browser = p.chromium.launch(
    headless=True,
    args=["--disable-blink-features=AutomationControlled"]
)
context = browser.new_context(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
    viewport={"width": 1920, "height": 1080},
    locale="ko-KR",
    timezone_id="Asia/Seoul",
    geolocation={"latitude": lat, "longitude": lng},
    permissions=["geolocation"],
)
page.add_init_script(
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)
```

---

## 에러 8: Crawler pipeline 'str' has no attribute 'get'

**위치**: `packages/crawler-admin/backend/pipeline/pipeline.py:107`  
**증상**: Giordano 크롤러 실행 시 AttributeError  
**원인**: `config.get("schedule", {}).get(...)` — schedule 값이 dict가 아니라 str인 경우  
**해결**: `isinstance(schedule, dict)` 체크 추가
