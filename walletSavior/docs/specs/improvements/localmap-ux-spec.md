# 동네 물가 지도 (LocalMap) UX 개선 명세서

> **문서 버전**: v1.0  
> **작성일**: 2026-04-03  
> **대상 파일**: `packages/website/frontend/src/pages/Local/LocalPage.jsx`, `packages/website/backend/api/routes/naver_local.py`, `packages/website/frontend/src/pages/Local/utils.js`  
> **핵심 목표**: 검색 결과 스트리밍, 카테고리 중복 병합, iframe 양방향 동기화

---

## 목차

1. [문제 정의 및 사용자 시나리오](#1-문제-정의-및-사용자-시나리오)
2. [스트리밍 결과 아키텍처](#2-스트리밍-결과-아키텍처)
3. [카테고리 병합 알고리즘](#3-카테고리-병합-알고리즘)
4. [프로그레시브 UI 패턴](#4-프로그레시브-ui-패턴)
5. [iframe 양방향 동기화](#5-iframe-양방향-동기화)
6. [구현 단계별 파일 변경 명세](#6-구현-단계별-파일-변경-명세)
7. [테스트 시나리오](#7-테스트-시나리오)

---

## 1. 문제 정의 및 사용자 시나리오

### 1.1 대표 사용자 시나리오: "오리역 맛집" 검색

**현재 경험 (AS-IS)**

```
[0.0s] 사용자가 "오리역" 입력 → Enter
[0.0s] Phase: idle → locating (Geocode API 호출)
[2.5s] Geocode 응답 → Phase: locating → exploring
[2.5s] area-explore 호출 시작 (6개 카테고리 순차 검색)
       └─ "오리역 주유소" 검색 (Playwright ~2.4s) → 1초 대기
       └─ "오리역 맛집" 검색 (~2.4s) → 1초 대기
       └─ "오리역 카페" 검색 (~2.4s) → 1초 대기
       └─ "오리역 병원" 검색 (~2.4s) → 1초 대기
       └─ "오리역 미용실" 검색 (~2.4s) → 1초 대기
       └─ "오리역 편의점 마트" 검색 (~2.4s)
[22~25s] 전체 응답 도착 → Phase: exploring → categories
[22~25s] 드디어 6개 카테고리 카드가 한 번에 나타남
```

**사용자 불만**: *"검색하면 로딩이 너무 느려. 다 끝나고 한 번에 하지 말고 긁어오는 대로 하나씩 추가되면서 보여주게 해야지"*

**개선 경험 (TO-BE)**

```
[0.0s] 사용자가 "오리역" 입력 → Enter
[0.0s] Phase: idle → locating
[2.5s] Geocode 응답 → Phase: exploring (스켈레톤 6개 표시)
[4.9s] SSE: 주유소 카테고리 도착 → 첫 번째 카드 실체화 (나머지 5개 스켈레톤)
[8.3s] SSE: 맛집 카테고리 도착 → 두 번째 카드 실체화
       ... (카테고리가 도착할 때마다 하나씩 카드 교체)
[22s]  SSE: 마지막 카테고리 도착 → 모든 카드 실체화
```

**체감 차이**: 첫 결과까지 **~5초** vs 기존 **~22초**. 사용자가 관심 카테고리를 발견하면 전체 로딩을 기다리지 않고 바로 클릭 가능.

### 1.2 카테고리 과다 분류 문제

**현재 상태**: "음식" 카테고리 클릭 시 `buildSubcategories()` 결과:

```
전체 (30개)
카페 (3개)
카페,디저트 (4개)
카페,디저트,빵 (2개)
카페,디저트,베이커리 (1개)
카페,디저트,아이스크림 (1개)
한식 (5개)
한식,고기,삼겹살 (3개)
한식,고기 (2개)
중식 (4개)
중식,짜장 (2개)
일식,초밥 (1개)
일식,돈까스 (2개)
```

**문제**: 13개 서브카테고리 버튼이 나타나지만, 실질적으로 "카페", "한식", "중식", "일식" 4개면 충분. 네이버가 반환하는 세분화된 카테고리(`카페,디저트,빵`)를 그대로 키로 사용하기 때문.

### 1.3 iframe-패널 동기화 문제

**현재**: 오른쪽 패널에서 가게를 클릭하면 `mapFocusUrl`로 iframe URL을 갱신하지만, iframe 내부에서 사용자가 직접 다른 가게를 클릭하거나 검색어를 바꾸면 오른쪽 패널은 이전 상태를 유지. 양방향 동기화 부재.

---

## 2. 스트리밍 결과 아키텍처

### 2.1 기술 선택: SSE (Server-Sent Events)

| 방식 | 장점 | 단점 | 적합도 |
|------|------|------|--------|
| **SSE** | HTTP 기반, 단방향 스트리밍에 최적, 자동 재연결, EventSource API 내장 | 단방향만 가능 | ✅ **최적** |
| Chunked Transfer | 별도 API 불필요 | 파싱 복잡, 브라우저 호환성 | ❌ |
| WebSocket | 양방향 | 과도한 복잡성, 인프라 부담 | ❌ |

**SSE 선택 이유**:
- area-explore는 **서버→클라이언트 단방향** 데이터 흐름
- 카테고리별로 완성된 데이터 청크를 전송하므로 SSE의 이벤트 모델과 정확히 일치
- `EventSource` API로 프론트엔드 구현이 간단
- FastAPI의 `StreamingResponse`로 자연스럽게 구현 가능
- 연결 끊김 시 자동 재연결 내장

### 2.2 백엔드 변경: SSE 엔드포인트 추가

#### 2.2.1 새 엔드포인트: `GET /api/local/area-explore-stream`

기존 `/api/local/area-explore`는 하위 호환을 위해 유지하고, **새 SSE 엔드포인트를 추가**한다.

```python
# naver_local.py에 추가

from fastapi.responses import StreamingResponse
import json

@router.get("/area-explore-stream")
async def area_explore_stream(
    location_name: str = Query(None),
    lat: float = Query(None),
    lng: float = Query(None),
    radius: float = Query(2),
    categories: str = Query(_DEFAULT_CATEGORIES),
    max_items: int = Query(30, ge=1, le=50),
):
    """SSE 스트리밍 area-explore. 카테고리별로 결과를 즉시 전송한다.

    이벤트 타입:
    - category: 개별 카테고리 결과 (카테고리 완성 시마다 전송)
    - progress: 진행률 정보 (현재/전체 카테고리 수)
    - done: 전체 탐색 완료 신호
    - error: 에러 발생 시
    """
    # Geocoding (기존 로직과 동일)
    if not location_name and (lat is None or lng is None):
        async def error_stream():
            yield _sse_event("error", {"message": "location_name 또는 lat/lng 필요"})
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    if location_name and (lat is None or lng is None):
        loop = asyncio.get_event_loop()
        geo = await loop.run_in_executor(_executor, _geocode_sync, location_name)
        if geo and geo.get("lat") and geo.get("lng"):
            lat, lng = geo["lat"], geo["lng"]
        else:
            lat, lng = lat or 37.5665, lng or 126.9780

    if not location_name:
        location_name = ""

    cat_list = [c.strip() for c in categories.split(",") if c.strip()]

    async def event_generator():
        """카테고리별로 Playwright 검색 후 즉시 SSE 이벤트로 전송."""
        total = len(cat_list)
        total_count = 0

        for idx, cat in enumerate(cat_list):
            # 진행률 전송
            yield _sse_event("progress", {
                "current": idx + 1,
                "total": total,
                "category_name": cat,
                "status": "searching",
            })

            # 캐시 확인
            cache_key = f"area:{location_name}:{cat}"
            cached = _cache_get(cache_key)

            if cached is not None:
                cat_result = cached
            else:
                # Playwright 검색 (ThreadPool에서 실행)
                loop = asyncio.get_event_loop()
                search_keyword = _CATEGORY_SEARCH_KEYWORDS.get(cat, cat)
                query = f"{location_name} {search_keyword}".strip()

                try:
                    items = await loop.run_in_executor(
                        _executor,
                        _search_via_playwright_sync,
                        query, lat, lng, max_items,
                    )
                    for item in items:
                        item["classifications"] = _classify_item(item)
                except Exception as exc:
                    logger.error(f"[SSE] {cat} 검색 실패: {exc}")
                    items = []

                tree_info = CATEGORY_TREE.get(cat, {})
                cat_result = {
                    "name": cat,
                    "icon": tree_info.get("icon", "📍"),
                    "count": len(items),
                    "items": items,
                }
                _cache_set(cache_key, cat_result)

            total_count += cat_result["count"]

            # 카테고리 결과 즉시 전송
            yield _sse_event("category", cat_result)

            # ban 방지 딜레이 (마지막 카테고리 제외)
            if idx < total - 1:
                await asyncio.sleep(1)

        # 완료 신호
        yield _sse_event("done", {
            "location_name": location_name,
            "lat": lat,
            "lng": lng,
            "total_count": total_count,
        })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 방지
        },
    )


def _sse_event(event_type: str, data: dict) -> str:
    """SSE 프로토콜 형식의 이벤트 문자열 생성."""
    json_str = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {json_str}\n\n"
```

#### 2.2.2 SSE 이벤트 스키마

```
┌─────────────────────────────────────────────────────────────────┐
│ event: progress                                                 │
│ data: {"current":1,"total":6,"category_name":"주유소",          │
│        "status":"searching"}                                    │
├─────────────────────────────────────────────────────────────────┤
│ event: category                                                 │
│ data: {"name":"주유소","icon":"⛽","count":5,                   │
│        "items":[{...},{...},...]}                                │
├─────────────────────────────────────────────────────────────────┤
│ event: progress                                                 │
│ data: {"current":2,"total":6,"category_name":"음식",            │
│        "status":"searching"}                                    │
├─────────────────────────────────────────────────────────────────┤
│ event: category                                                 │
│ data: {"name":"음식","icon":"🍽️","count":12,                    │
│        "items":[{...},{...},...]}                                │
├─────────────────────────────────────────────────────────────────┤
│ ... (반복)                                                      │
├─────────────────────────────────────────────────────────────────┤
│ event: done                                                     │
│ data: {"location_name":"오리역","lat":37.xx,"lng":127.xx,       │
│        "total_count":42}                                        │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 프론트엔드 변경: EventSource 소비

#### 2.3.1 `areaExploreStream` 함수 (LocalPage.jsx)

기존 `areaExplore`를 대체하는 스트리밍 버전:

```javascript
const areaExploreStream = useCallback((locName, latVal, lngVal, onCategory, onProgress, onDone, onError) => {
  const params = new URLSearchParams({
    categories: EXPLORE_CATEGORIES,
    max_items: '30',
  });
  if (locName) params.set('location_name', locName);
  if (latVal != null) params.set('lat', String(latVal));
  if (lngVal != null) params.set('lng', String(lngVal));

  const url = `/api/local/area-explore-stream?${params}`;
  const eventSource = new EventSource(url);

  eventSource.addEventListener('category', (e) => {
    try {
      const catData = JSON.parse(e.data);
      onCategory(catData);
    } catch (err) {
      console.error('SSE category 파싱 실패:', err);
    }
  });

  eventSource.addEventListener('progress', (e) => {
    try {
      const progressData = JSON.parse(e.data);
      onProgress?.(progressData);
    } catch (err) {
      console.error('SSE progress 파싱 실패:', err);
    }
  });

  eventSource.addEventListener('done', (e) => {
    try {
      const doneData = JSON.parse(e.data);
      onDone(doneData);
    } catch (err) {
      console.error('SSE done 파싱 실패:', err);
    }
    eventSource.close();
  });

  eventSource.addEventListener('error', (e) => {
    // SSE 에러 또는 서버 에러 이벤트
    if (e.data) {
      try {
        const errData = JSON.parse(e.data);
        onError?.(errData.message || '탐색 실패');
      } catch {
        onError?.('탐색 실패');
      }
    }
    eventSource.close();
  });

  eventSource.onerror = () => {
    eventSource.close();
    onError?.('서버 연결이 끊어졌습니다');
  };

  // 클린업 함수 반환 (컴포넌트 언마운트 시 사용)
  return () => eventSource.close();
}, []);
```

#### 2.3.2 `runAreaExplore` 스트리밍 버전

```javascript
const eventSourceRef = useRef(null);

const runAreaExplore = useCallback((locName, latVal, lngVal) => {
  setPhase('exploring');
  // 스켈레톤용 빈 카테고리 슬롯 미리 세팅
  const categoryNames = EXPLORE_CATEGORIES.split(',');
  setExploreData({
    categories: categoryNames.map(name => ({
      name,
      icon: CATEGORY_ICONS[name] || '📍',
      count: null,       // null = 아직 로딩 중
      items: null,       // null = 아직 로딩 중
      _loading: true,    // 스켈레톤 표시 플래그
    })),
  });
  setPhase('categories');  // 즉시 카테고리 화면으로 전환 (스켈레톤 포함)

  // 이전 SSE 연결이 있으면 정리
  if (eventSourceRef.current) {
    eventSourceRef.current();
    eventSourceRef.current = null;
  }

  const cleanup = areaExploreStream(
    locName, latVal, lngVal,
    // onCategory: 카테고리 하나 도착할 때마다
    (catData) => {
      setExploreData(prev => {
        if (!prev) return prev;
        const updated = prev.categories.map(c =>
          c.name === catData.name
            ? { ...catData, _loading: false }
            : c
        );
        return { ...prev, categories: updated };
      });
    },
    // onProgress: 진행률 업데이트
    (progressData) => {
      // 현재 검색 중인 카테고리 강조 (선택 사항)
      setExploreData(prev => {
        if (!prev) return prev;
        const updated = prev.categories.map(c =>
          c.name === progressData.category_name
            ? { ...c, _searching: true }
            : { ...c, _searching: false }
        );
        return { ...prev, categories: updated };
      });
    },
    // onDone: 전체 완료
    (doneData) => {
      eventSourceRef.current = null;
      // Phase는 이미 'categories'이므로 추가 변경 불필요
    },
    // onError: 에러 처리
    (errorMsg) => {
      addToast(errorMsg || '주변 탐색에 실패했습니다.', 'warning');
      eventSourceRef.current = null;
    },
  );

  eventSourceRef.current = cleanup;
}, [areaExploreStream, addToast]);
```

#### 2.3.3 컴포넌트 언마운트 시 정리

```javascript
// LocalPage 컴포넌트 최상단에 추가
useEffect(() => {
  return () => {
    if (eventSourceRef.current) {
      eventSourceRef.current();
    }
  };
}, []);
```

### 2.4 스트리밍 적용 범위

| 엔드포인트 | 스트리밍 적용 | 이유 |
|------------|:---:|------|
| `area-explore` | ✅ SSE | 6개 카테고리 순차 검색, 총 22초+ → 카테고리별 즉시 표시 |
| `naver-search` | ❌ 유지 | 단일 검색 쿼리, 2~3초, 스트리밍 불필요 |
| `subcategory-search` | ❌ 유지 | 단일 검색 쿼리, 2~3초 |
| `geocode` | ❌ 유지 | 응답 즉시 (~2초), 단일 결과 |

---

## 3. 카테고리 병합 알고리즘

### 3.1 문제 분석

네이버 `category` 필드는 쉼표 구분 계층 구조를 사용한다:

```
"카페"
"카페,디저트"
"카페,디저트,빵"
"카페,디저트,베이커리"
"카페,디저트,아이스크림"
"한식"
"한식,고기"
"한식,고기,삼겹살"
```

현재 `buildSubcategories()`는 전체 문자열을 키로 사용하여 10개 이상의 서브카테고리가 생성됨.

### 3.2 병합 전략: 첫 번째 토큰 기반 그룹핑 + 스마트 분리

#### 핵심 원칙

1. **1차 토큰**을 기준으로 그룹핑한다 → `"카페,디저트,빵"` → `"카페"`
2. **최대 서브카테고리 수**를 제한한다 (목표: **6~8개** 이하)
3. 아이템 수가 적은(≤2) 그룹은 유사 그룹과 병합하거나 "기타"로 통합한다
4. 특수 도메인 동의어를 처리한다 (예: `"커피"` ≈ `"카페"`)

#### 3.2.1 새로운 `buildSubcategories` 함수

```javascript
// utils.js — buildSubcategories() 교체

/**
 * 동의어 매핑 테이블.
 * 네이버 카테고리의 1차 토큰이 이 테이블에 있으면 정규화된 이름으로 병합.
 */
const SYNONYM_MAP = {
  '커피': '카페',
  '디저트': '카페',
  '베이커리': '카페',
  '빵': '카페',
  '아이스크림': '카페',
  '짜장': '중식',
  '짬뽕': '중식',
  '중국집': '중식',
  '초밥': '일식',
  '스시': '일식',
  '돈까스': '일식',
  '라멘': '일식',
  '우동': '일식',
  '삼겹살': '고기',
  '갈비': '고기',
  '곱창': '고기',
  '소고기': '고기',
  '돼지고기': '고기',
  '양고기': '고기',
  '떡볶이': '분식',
  '김밥': '분식',
  '버거': '패스트푸드',
  '맥도날드': '패스트푸드',
  '통닭': '치킨',
};

/** 최대 표시 서브카테고리 수 */
const MAX_SUBCATEGORIES = 8;
/** 이 수 이하의 아이템을 가진 그룹은 병합 대상 */
const MERGE_THRESHOLD = 2;

/**
 * 네이버 카테고리 문자열에서 정규화된 1차 토큰 추출.
 *
 * "카페,디저트,빵" → "카페"
 * "커피" → "카페" (동의어 매핑)
 * "한식,고기,삼겹살" → "한식"
 */
function extractPrimaryToken(categoryStr) {
  if (!categoryStr) return '기타';
  const tokens = categoryStr.split(/[,\s>·]+/).map(t => t.trim()).filter(Boolean);
  if (tokens.length === 0) return '기타';

  const first = tokens[0];
  return SYNONYM_MAP[first] || first;
}

/**
 * 카테고리 병합 알고리즘이 적용된 서브카테고리 맵 생성.
 *
 * 단계:
 * 1. 각 아이템의 네이버 카테고리에서 1차 토큰 추출 (동의어 적용)
 * 2. 1차 토큰 기준으로 그룹핑
 * 3. 소규모 그룹(≤MERGE_THRESHOLD)은 유사 그룹에 병합 또는 "기타"로 통합
 * 4. 그룹 수가 MAX_SUBCATEGORIES 초과 시 가장 작은 그룹부터 "기타"로 병합
 * 5. 2개 이상 그룹이 있으면 "전체" 추가
 */
export function buildSubcategories(items) {
  if (!items || items.length === 0) return {};

  // Step 1: 1차 토큰 기준 그룹핑
  const groupMap = {};
  items.forEach(item => {
    const cat = item.category || '';
    const primary = extractPrimaryToken(cat);
    if (!groupMap[primary]) groupMap[primary] = [];
    if (!groupMap[primary].includes(item)) {
      groupMap[primary].push(item);
    }
  });

  // Step 2: 소규모 그룹 병합
  const entries = Object.entries(groupMap);
  const merged = {};
  const overflow = [];

  for (const [key, groupItems] of entries) {
    if (groupItems.length <= MERGE_THRESHOLD) {
      overflow.push(...groupItems);
    } else {
      merged[key] = groupItems;
    }
  }

  // overflow 아이템이 있으면 "기타"로 통합
  if (overflow.length > 0) {
    if (overflow.length <= MERGE_THRESHOLD && Object.keys(merged).length > 0) {
      // 아이템이 너무 적으면 가장 큰 그룹에 흡수
      const largestKey = Object.keys(merged)
        .sort((a, b) => merged[b].length - merged[a].length)[0];
      const existingNames = new Set(merged[largestKey].map(i => i.name));
      overflow.forEach(i => {
        if (!existingNames.has(i.name)) merged[largestKey].push(i);
      });
    } else {
      merged['기타'] = overflow;
    }
  }

  // Step 3: 그룹 수 제한 (MAX_SUBCATEGORIES 초과 시)
  const sortedKeys = Object.keys(merged)
    .sort((a, b) => merged[b].length - merged[a].length);

  if (sortedKeys.length > MAX_SUBCATEGORIES) {
    const keep = sortedKeys.slice(0, MAX_SUBCATEGORIES - 1);
    const mergeKeys = sortedKeys.slice(MAX_SUBCATEGORIES - 1);
    const etcItems = [];
    for (const k of mergeKeys) {
      etcItems.push(...merged[k]);
      delete merged[k];
    }
    merged['기타'] = [...(merged['기타'] || []), ...etcItems];
  }

  // Step 4: "전체" 추가 (2개 이상 그룹일 때)
  if (Object.keys(merged).length > 1) {
    merged['전체'] = items;
  }

  // 단일 그룹이면 그룹핑 불필요 → 빈 맵 대신 전체 아이템만
  if (Object.keys(merged).length <= 1 && !merged['전체']) {
    return { '전체': items };
  }

  return merged;
}
```

### 3.3 병합 결과 예시

**입력 (30개 음식 아이템)**:

| 네이버 category | 1차 토큰 | 정규화 |
|----------------|---------|--------|
| `카페` | 카페 | 카페 |
| `카페,디저트` | 카페 | 카페 |
| `카페,디저트,빵` | 카페 | 카페 |
| `카페,디저트,베이커리` | 카페 | 카페 |
| `카페,디저트,아이스크림` | 카페 | 카페 |
| `한식` | 한식 | 한식 |
| `한식,고기` | 한식 | 한식 |
| `한식,고기,삼겹살` | 한식 | 한식 |
| `중식` | 중식 | 중식 |
| `중식,짜장` | 중식 | 중식 |
| `일식,초밥` | 일식 | 일식 |
| `일식,돈까스` | 일식 | 일식 |
| `치킨` | 치킨 | 치킨 |

**출력 (병합 후)**:

```
전체 (30개)
카페 (10개)      ← 카페 + 카페,디저트 + 카페,디저트,빵 + ...
한식 (8개)       ← 한식 + 한식,고기 + 한식,고기,삼겹살
중식 (6개)       ← 중식 + 중식,짜장
일식 (4개)       ← 일식,초밥 + 일식,돈까스
치킨 (2개)       ← 기타에 병합되거나 독립 유지 (MERGE_THRESHOLD에 따라)
```

**13개 → 5~6개**로 감소. 사용자가 한 눈에 파악 가능.

### 3.4 서브카테고리 버튼 정렬 순서

병합된 서브카테고리를 표시할 때의 정렬 우선순위:

```javascript
// 서브카테고리 키 정렬: "전체" → 아이템 수 내림차순 → "기타"는 마지막
const sortedSubKeys = useMemo(() => {
  const keys = Object.keys(subcategoryMap);
  return keys.sort((a, b) => {
    if (a === '전체') return -1;
    if (b === '전체') return 1;
    if (a === '기타') return 1;
    if (b === '기타') return -1;
    return (subcategoryMap[b]?.length || 0) - (subcategoryMap[a]?.length || 0);
  });
}, [subcategoryMap]);
```

### 3.5 카테고리 병합 시 원본 보존

병합된 카테고리를 사용하더라도, 각 아이템의 원본 `category` 필드는 그대로 유지한다. 이는 상세 모달에서 정확한 업종 표시를 위해 필요하다.

```
서브카테고리 버튼: "카페" (10개)
└─ 아이템 1: 스타벅스 (원본 카테고리: "카페,디저트")
└─ 아이템 2: 투썸플레이스 (원본 카테고리: "카페,디저트,빵")
└─ 아이템 3: 파리바게뜨 (원본 카테고리: "카페,디저트,베이커리")
```

---

## 4. 프로그레시브 UI 패턴

### 4.1 스켈레톤 → 실체화 전환 설계

#### 4.1.1 카테고리 카드 3단계 상태

```
┌──────────────────────────────────────────────────────┐
│ 상태 1: _loading=true, _searching=false              │
│ [스켈레톤] 회색 펄스 애니메이션                         │
│ ┌─────────────────────────┐                          │
│ │ ░░░░░░░░░░░░░░░░░░░░░░ │ ← 아이콘 + 이름 + 건수    │
│ │ ░░░░░░░░░░             │    모두 스켈레톤            │
│ └─────────────────────────┘                          │
├──────────────────────────────────────────────────────┤
│ 상태 2: _loading=true, _searching=true               │
│ [검색 중] 스켈레톤 + 검색 인디케이터                     │
│ ┌─────────────────────────┐                          │
│ │ ⛽ 주유소               │ ← 이름은 표시              │
│ │ 🔍 검색 중...           │ ← 스피너 + 텍스트         │
│ └─────────────────────────┘                          │
├──────────────────────────────────────────────────────┤
│ 상태 3: _loading=false                               │
│ [완료] 실제 데이터 표시                                │
│ ┌─────────────────────────┐                          │
│ │ ⛽ 주유소     5건        │ ← fadeIn 애니메이션       │
│ │ 평균 휘발유 1,785원      │    으로 나타남             │
│ └─────────────────────────┘                          │
└──────────────────────────────────────────────────────┘
```

#### 4.1.2 CSS 애니메이션

```css
/* LocalPage.module.css에 추가 */

/* 스켈레톤 펄스 */
.skeletonPulse {
  background: linear-gradient(90deg, #e8e8e8 25%, #f5f5f5 50%, #e8e8e8 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 8px;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* 카테고리 카드 등장 애니메이션 */
.categoryCard {
  opacity: 0;
  transform: translateY(12px);
  animation: cardAppear 0.35s ease-out forwards;
}

@keyframes cardAppear {
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 검색 중 인디케이터 */
.searchingIndicator {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #666;
  font-size: 0.85rem;
}

.searchingDot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #4a90d9;
  animation: dotBounce 1.4s infinite ease-in-out;
}

.searchingDot:nth-child(2) { animation-delay: 0.2s; }
.searchingDot:nth-child(3) { animation-delay: 0.4s; }

@keyframes dotBounce {
  0%, 80%, 100% { transform: scale(0); }
  40% { transform: scale(1); }
}

/* 아이템 리스트 진입 애니메이션 */
.itemEnter {
  opacity: 0;
  transform: translateX(-10px);
  animation: itemSlideIn 0.25s ease-out forwards;
}

@keyframes itemSlideIn {
  to {
    opacity: 1;
    transform: translateX(0);
  }
}
```

### 4.2 카테고리 카드 렌더링 (스켈레톤 지원)

```jsx
{/* 카테고리 그리드 — exploring / categories 단계 */}
{(phase === 'categories' || phase === 'exploring') && exploreData?.categories && (
  <div className={s.categoryGrid}>
    {exploreData.categories.map((cat, idx) => (
      <div
        key={cat.name}
        className={`${s.categoryCard} ${cat._loading ? s.skeletonPulse : ''}`}
        style={{ animationDelay: cat._loading ? '0s' : `${idx * 0.07}s` }}
        onClick={() => !cat._loading && handleCategoryClick(cat)}
        role={cat._loading ? undefined : 'button'}
        tabIndex={cat._loading ? -1 : 0}
      >
        {cat._loading ? (
          // 스켈레톤 상태
          <div className={s.skeletonCard}>
            <div className={s.skeletonIcon} />
            {cat._searching ? (
              <div className={s.searchingIndicator}>
                <span>{cat.icon} {cat.name}</span>
                <div className={s.searchingDot} />
                <div className={s.searchingDot} />
                <div className={s.searchingDot} />
              </div>
            ) : (
              <>
                <div className={s.skeletonText} style={{ width: '60%' }} />
                <div className={s.skeletonText} style={{ width: '40%' }} />
              </>
            )}
          </div>
        ) : (
          // 실제 데이터
          <>
            <span className={s.categoryIcon}>{cat.icon}</span>
            <span className={s.categoryName}>{cat.name}</span>
            <span className={s.categoryCount}>{cat.count}건</span>
          </>
        )}
      </div>
    ))}
  </div>
)}
```

### 4.3 프로그레스 바

전체 진행률을 상단에 표시하여 사용자에게 대기 시간의 기대치를 제공한다.

```jsx
// 진행률 상태
const [exploreProgress, setExploreProgress] = useState({ current: 0, total: 0 });

// onProgress 콜백에서 업데이트
onProgress: (progressData) => {
  setExploreProgress({
    current: progressData.current,
    total: progressData.total,
  });
}

// 렌더링
{phase === 'categories' && exploreProgress.total > 0 && exploreProgress.current <= exploreProgress.total && (
  <div className={s.progressBarContainer}>
    <div
      className={s.progressBar}
      style={{ width: `${(exploreProgress.current / exploreProgress.total) * 100}%` }}
    />
    <span className={s.progressText}>
      주변 탐색 중... ({exploreProgress.current}/{exploreProgress.total})
    </span>
  </div>
)}
```

```css
/* 프로그레스 바 */
.progressBarContainer {
  position: relative;
  width: 100%;
  height: 28px;
  background: #f0f0f0;
  border-radius: 14px;
  overflow: hidden;
  margin-bottom: 16px;
}

.progressBar {
  height: 100%;
  background: linear-gradient(90deg, #4a90d9, #67b8f7);
  border-radius: 14px;
  transition: width 0.5s ease-out;
}

.progressText {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 0.8rem;
  font-weight: 500;
  color: #333;
  white-space: nowrap;
}
```

### 4.4 아이템 리스트 프로그레시브 렌더링

서브카테고리 클릭 후 `subcategory-search` API 결과가 추가될 때, 기존 아이템에 새 아이템이 하나씩 추가되는 효과:

```javascript
// 기존 handleSubcategoryClick에서 moreItems 추가 시
const moreItems = await fetchSubcategoryResults(locationName, subName, lat, lng);
if (moreItems.length > 0) {
  const existingNames = new Set(filtered.map(i => i.name));
  const newItems = moreItems.filter(i => !existingNames.has(i.name));

  // 한 번에 추가하는 대신, 100ms 간격으로 하나씩 추가 (최대 20개)
  for (let i = 0; i < newItems.length && i < 20; i++) {
    await new Promise(r => setTimeout(r, 80));
    setDisplayItems(prev => [...prev, newItems[i]]);
  }
  // 나머지는 한 번에 추가
  if (newItems.length > 20) {
    setDisplayItems(prev => [...prev, ...newItems.slice(20)]);
  }
}
```

> **주의**: `requestAnimationFrame` 기반이 아닌 `setTimeout` 기반이므로, 탭이 백그라운드에 있으면 지연될 수 있다. 프로덕션에서는 `IntersectionObserver` 기반 가상 스크롤과 병행하는 것이 좋다.

### 4.5 실시간 카운트 업데이트

카테고리 카드에 아이템 수가 0에서 실제 수로 카운트업되는 효과:

```jsx
function AnimatedCount({ value, duration = 600 }) {
  const [display, setDisplay] = useState(0);
  const ref = useRef(null);

  useEffect(() => {
    if (value === null || value === undefined) return;
    let start = 0;
    const startTime = performance.now();

    function animate(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // easeOutQuad
      const eased = 1 - (1 - progress) * (1 - progress);
      setDisplay(Math.round(eased * value));
      if (progress < 1) {
        ref.current = requestAnimationFrame(animate);
      }
    }

    ref.current = requestAnimationFrame(animate);
    return () => {
      if (ref.current) cancelAnimationFrame(ref.current);
    };
  }, [value, duration]);

  return <span>{display}건</span>;
}
```

---

## 5. iframe 양방향 동기화

### 5.1 현재 문제

```
┌──────────────────┐     ┌──────────────────┐
│   오른쪽 패널     │ ──→ │   네이버 지도      │  ← 패널→지도: 동작함
│   (React)        │     │   (iframe)        │     (iframeUrl 변경)
│                  │ ✗── │                   │  ← 지도→패널: 동작 안 함
└──────────────────┘     └──────────────────┘     (iframe은 cross-origin)
```

### 5.2 근본적 제약: Cross-Origin iframe

네이버 지도 iframe (`map.naver.com`)은 **cross-origin**이므로:
- `postMessage`를 보낼 수는 있지만, 네이버가 수신 처리를 하지 않음
- iframe 내부 DOM에 접근 불가 (`SecurityError`)
- iframe 내부의 URL 변경을 감지할 수 없음 (`contentWindow.location` 접근 불가)

### 5.3 실현 가능한 개선 전략

#### 전략 A: 패널→지도 동기화 강화 (현실적, 즉시 적용 가능)

지도→패널 완전 동기화는 기술적으로 불가능하므로, **패널→지도 방향을 더 정밀하게** 만든다.

##### A-1: 아이템 호버 시 지도 포커스

```jsx
// 아이템에 마우스 호버 시 지도를 해당 장소로 이동
const handleItemHover = useCallback(
  debounce((item) => {
    if (item.url) {
      setMapFocusUrl(item.url);
    } else if (item.name) {
      setMapFocusUrl(
        `https://map.naver.com/p/search/${encodeURIComponent(item.name)}`
      );
    }
  }, 300),  // 300ms 디바운스: 빠르게 스크롤할 때 과도한 iframe 전환 방지
  []
);

const handleItemHoverEnd = useCallback(() => {
  // 호버 종료 후 원래 검색 결과로 복원
  setMapFocusUrl(null);
}, []);
```

##### A-2: 현재 포커스 아이템 하이라이트

```jsx
const [focusedItemName, setFocusedItemName] = useState(null);

// 아이템 리스트에서 현재 지도에 포커스된 아이템 강조
<div
  className={`${s.itemCard} ${item.name === focusedItemName ? s.itemFocused : ''}`}
  onMouseEnter={() => {
    setFocusedItemName(item.name);
    handleItemHover(item);
  }}
  onMouseLeave={() => {
    setFocusedItemName(null);
    handleItemHoverEnd();
  }}
>
```

```css
.itemFocused {
  border-left: 3px solid #4a90d9;
  background: #f0f7ff;
  transition: all 0.2s ease;
}
```

##### A-3: iframe URL 변경 감지 (제한적)

`iframe`의 `load` 이벤트는 감지할 수 있다. 네이버 지도 내에서 검색어가 바뀌면 새 페이지가 로드되므로, `onLoad` 이벤트 횟수로 사용자의 지도 내 탐색을 간접 추적한다.

```jsx
const handleIframeLoad = useCallback(() => {
  iframeLoadCount.current += 1;

  // 최초 로드가 아닌 경우 (사용자가 iframe 내에서 탐색)
  if (iframeLoadCount.current > 1) {
    // 패널의 "지도와 다를 수 있습니다" 알림 표시
    setMapSyncWarning(true);
  }
}, []);

// 렌더링
{mapSyncWarning && (
  <div className={s.syncWarning}>
    <span>⚠️ 지도에서 다른 검색을 하셨나요?</span>
    <button
      onClick={() => {
        setMapSyncWarning(false);
        // 현재 패널 상태로 지도를 리셋
        handleMapReset();
      }}
    >
      패널과 다시 동기화
    </button>
  </div>
)}
```

#### 전략 B: 네이버 지도 API 직접 사용 (장기적, 높은 효과)

iframe 대신 네이버 지도 JavaScript API를 직접 사용하면 완전한 양방향 동기화가 가능하다.

> ⚠️ **이 전략은 네이버 클라우드 플랫폼 API 키가 필요하며, 별도 과금이 발생할 수 있다.**

##### B-1: 아키텍처 변경

```
현재:  iframe(map.naver.com/p/search/...) ← URL만 제어 가능
변경:  <NaverMapComponent> ← Naver Maps JavaScript API v3
       └─ 마커/오버레이 직접 제어
       └─ 클릭/드래그 이벤트 수신
       └─ 검색 결과 마커 동기화
```

##### B-2: 컴포넌트 구조 (참고용)

```jsx
// 향후 NaverMapDirect.jsx (개략적 구조)
function NaverMapDirect({ items, center, onMarkerClick, onBoundsChange }) {
  const mapRef = useRef(null);
  const markersRef = useRef([]);

  useEffect(() => {
    // 네이버 지도 API 초기화
    const map = new naver.maps.Map(mapRef.current, {
      center: new naver.maps.LatLng(center.lat, center.lng),
      zoom: 15,
    });

    // 지도 이동 시 패널에 알림 (양방향 동기화의 핵심)
    naver.maps.Event.addListener(map, 'idle', () => {
      const bounds = map.getBounds();
      onBoundsChange?.(bounds);
    });
  }, []);

  useEffect(() => {
    // 아이템이 변경되면 마커 업데이트
    markersRef.current.forEach(m => m.setMap(null)); // 기존 마커 제거
    markersRef.current = items
      .filter(item => item.x && item.y)
      .map(item => {
        const marker = new naver.maps.Marker({
          position: new naver.maps.LatLng(item.y, item.x),
          map: mapRef.current,
          title: item.name,
        });
        naver.maps.Event.addListener(marker, 'click', () => onMarkerClick?.(item));
        return marker;
      });
  }, [items]);

  return <div ref={mapRef} style={{ width: '100%', height: '100%' }} />;
}
```

##### B-3: 양방향 동기화 흐름

```
사용자가 지도에서 마커 클릭
  → onMarkerClick(item)
  → 패널에서 해당 아이템 하이라이트 + 스크롤
  → 상세 모달 표시

사용자가 지도를 드래그/줌
  → onBoundsChange(bounds)
  → 패널에서 현재 보이는 영역의 아이템만 필터링
  → "이 영역에서 재검색" 버튼 표시

사용자가 패널에서 아이템 클릭
  → map.panTo(itemLatLng)
  → 해당 마커에 InfoWindow 표시
```

### 5.4 권장 구현 순서

| 단계 | 전략 | 난이도 | 효과 | 소요 시간 |
|------|------|--------|------|----------|
| **1단계** | A-1, A-2 (호버 동기화) | 낮음 | 중간 | 2~3시간 |
| **2단계** | A-3 (iframe 로드 감지) | 낮음 | 낮음 | 1시간 |
| **3단계** | B (네이버 지도 API 전환) | 높음 | 높음 | 2~3일 |

**1단계는 즉시 적용 가능하며, 사용자 체감 개선이 크다.** 3단계는 API 키 확보 후 별도 스프린트로 진행.

---

## 6. 구현 단계별 파일 변경 명세

### Phase 1: 스트리밍 + 프로그레시브 UI (핵심)

#### 6.1 백엔드 변경

**파일: `packages/website/backend/api/routes/naver_local.py`**

| 변경 | 내용 |
|------|------|
| import 추가 | `from fastapi.responses import StreamingResponse`, `import json` |
| 함수 추가 | `_sse_event(event_type, data)` — SSE 이벤트 포맷터 |
| 엔드포인트 추가 | `GET /area-explore-stream` — SSE 스트리밍 area-explore |
| 기존 유지 | `GET /area-explore` — 하위 호환 (제거하지 않음) |

**변경하지 않는 것**:
- `_search_via_playwright_sync` — 기존 검색 로직 그대로 사용
- `_classify_item` — 분류 로직 유지
- `_BrowserPool` — 브라우저 풀 유지
- 다른 엔드포인트 (`naver-search`, `subcategory-search`, `geocode`) — 변경 없음

#### 6.2 프론트엔드 변경

**파일: `packages/website/frontend/src/pages/Local/LocalPage.jsx`**

| 변경 | 내용 |
|------|------|
| 상태 추가 | `exploreProgress` (진행률), `mapSyncWarning` (동기화 경고), `focusedItemName` (호버 포커스) |
| ref 추가 | `eventSourceRef` (SSE 클린업) |
| 함수 추가 | `areaExploreStream()` — EventSource 기반 SSE 소비 |
| 함수 수정 | `runAreaExplore()` — 기존 batch → SSE 스트리밍 전환 |
| 함수 추가 | `handleItemHover()`, `handleItemHoverEnd()` — 아이템 호버 시 지도 포커스 |
| 함수 수정 | `handleIframeLoad()` — iframe 로드 카운트 기반 동기화 감지 |
| 렌더링 수정 | 카테고리 카드에 스켈레톤/검색중/실체화 3단계 분기 |
| 렌더링 추가 | 프로그레스 바 컴포넌트 |
| 렌더링 추가 | 동기화 경고 배너 |
| effect 추가 | 컴포넌트 언마운트 시 EventSource 정리 |

**파일: `packages/website/frontend/src/pages/Local/utils.js`**

| 변경 | 내용 |
|------|------|
| 상수 추가 | `SYNONYM_MAP`, `MAX_SUBCATEGORIES`, `MERGE_THRESHOLD` |
| 함수 추가 | `extractPrimaryToken(categoryStr)` |
| 함수 교체 | `buildSubcategories(items)` — 전체 재작성 (카테고리 병합 알고리즘) |
| 함수 유지 | `getRepresentativePrice`, `parseMenuItems`, `sortItems`, `isGasCategory` — 변경 없음 |

**파일: `packages/website/frontend/src/pages/Local/LocalPage.module.css`**

| 변경 | 내용 |
|------|------|
| 추가 | `.skeletonPulse`, `@keyframes shimmer` — 스켈레톤 애니메이션 |
| 추가 | `.categoryCard`, `@keyframes cardAppear` — 카드 등장 |
| 추가 | `.searchingIndicator`, `.searchingDot`, `@keyframes dotBounce` — 검색 중 표시 |
| 추가 | `.progressBarContainer`, `.progressBar`, `.progressText` — 프로그레스 바 |
| 추가 | `.itemFocused` — 호버 포커스 하이라이트 |
| 추가 | `.syncWarning` — 동기화 경고 배너 |
| 추가 | `.itemEnter`, `@keyframes itemSlideIn` — 아이템 등장 |

**파일: `packages/website/frontend/src/pages/Local/components/SkeletonLoader.jsx`**

| 변경 | 내용 |
|------|------|
| 수정 | 카테고리 카드 스켈레톤에 `_searching` 상태 분기 추가 (기존 SkeletonLoader는 exploring 페이즈 전용이었으므로, 카테고리 카드 내 인라인 스켈레톤과 역할 분리 검토) |

### Phase 2: iframe 호버 동기화

**파일: `packages/website/frontend/src/pages/Local/LocalPage.jsx`**

| 변경 | 내용 |
|------|------|
| 유틸 import | `debounce` (lodash 또는 자체 구현) |
| 함수 추가 | `handleItemHover`, `handleItemHoverEnd` |
| 렌더링 수정 | 아이템 카드에 `onMouseEnter`, `onMouseLeave` 핸들러 추가 |

### Phase 3: 네이버 지도 API 전환 (장기)

**새 파일**: `packages/website/frontend/src/pages/Local/components/NaverMapDirect.jsx`

| 변경 | 내용 |
|------|------|
| 신규 | 네이버 지도 JavaScript API v3 래퍼 컴포넌트 |
| 신규 | 마커 관리, 클릭 이벤트, bounds 변경 이벤트 |

**파일: `packages/website/frontend/public/index.html`**

| 변경 | 내용 |
|------|------|
| 추가 | `<script src="https://oapi.map.naver.com/openapi/v3/maps.js?ncpClientId=...">` |

---

## 7. 테스트 시나리오

### 7.1 스트리밍 테스트

| # | 시나리오 | 기대 결과 |
|---|---------|----------|
| S-1 | "오리역" 검색 후 카테고리 카드 영역 관찰 | 6개 스켈레톤 → 하나씩 실체화 (첫 카드 ~5초, 전체 ~22초) |
| S-2 | 스트리밍 중 첫 번째 카드(주유소) 클릭 | 나머지 카테고리 스트리밍이 중단되고, 주유소 상세 진입 |
| S-3 | 스트리밍 중 브라우저 뒤로가기 | EventSource 정리, 메모리 누수 없음 |
| S-4 | 네트워크 끊김 시 | 에러 토스트 표시, 이미 로드된 카테고리는 유지 |
| S-5 | 캐시된 카테고리 존재 시 | 캐시 히트된 카테고리는 즉시 실체화, 미스된 것만 스켈레톤 |

### 7.2 카테고리 병합 테스트

| # | 입력 카테고리들 | 기대 병합 결과 |
|---|---------------|---------------|
| C-1 | `카페`, `카페,디저트`, `카페,디저트,빵` | 모두 → `카페` 1개 그룹 |
| C-2 | `한식`, `한식,고기`, `한식,고기,삼겹살` | 모두 → `한식` 1개 그룹 |
| C-3 | `커피` | → `카페` (동의어 매핑) |
| C-4 | `짜장`, `중식` | → `중식` (동의어 매핑) |
| C-5 | 15개 고유 1차 토큰 | 상위 7개 + `기타` = 8개 (MAX_SUBCATEGORIES) |
| C-6 | 아이템 1개인 `양식` 그룹 | → `기타`에 병합 또는 최대 그룹에 흡수 |
| C-7 | 모든 아이템이 같은 카테고리 | 서브카테고리 분기 없이 바로 아이템 표시 |

### 7.3 iframe 동기화 테스트

| # | 시나리오 | 기대 결과 |
|---|---------|----------|
| I-1 | 아이템 카드에 마우스 호버 (300ms 이상) | iframe이 해당 장소 URL로 변경 |
| I-2 | 아이템 카드에서 마우스 빠르게 이탈 | iframe 변경 없음 (디바운스) |
| I-3 | iframe 내에서 사용자가 다른 검색 수행 | "지도와 다를 수 있습니다" 경고 표시 |
| I-4 | 경고 배너의 "다시 동기화" 클릭 | iframe이 현재 패널 상태로 리셋 |

### 7.4 성능 목표

| 지표 | 현재 | 목표 |
|------|------|------|
| 첫 번째 카테고리 카드 표시 | ~22초 | **~5초** |
| 전체 카테고리 로딩 | ~22초 | ~22초 (총 시간 동일, 체감 시간 감소) |
| 서브카테고리 수 (음식) | 10~15개 | **4~8개** |
| iframe 호버 반응 시간 | N/A | **300ms** 디바운스 후 즉시 |

---

## 부록 A: SSE 폴백 전략

`EventSource`를 지원하지 않는 환경(일부 구형 프록시)을 위한 폴백:

```javascript
function createAreaExploreConnection(url, handlers) {
  if (typeof EventSource !== 'undefined') {
    // SSE 사용
    return createEventSourceConnection(url, handlers);
  } else {
    // Fetch + ReadableStream 폴백
    return createFetchStreamConnection(url, handlers);
  }
}

async function createFetchStreamConnection(url, { onCategory, onProgress, onDone, onError }) {
  try {
    const response = await fetch(url);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const event of events) {
        const lines = event.split('\n');
        let eventType = '', data = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.slice(7);
          if (line.startsWith('data: ')) data = line.slice(6);
        }
        if (!eventType || !data) continue;
        const parsed = JSON.parse(data);
        switch (eventType) {
          case 'category': onCategory(parsed); break;
          case 'progress': onProgress?.(parsed); break;
          case 'done': onDone(parsed); break;
          case 'error': onError?.(parsed.message); break;
        }
      }
    }
  } catch (err) {
    onError?.(err.message);
  }
}
```

## 부록 B: 카테고리 동의어 확장 가이드

`SYNONYM_MAP`은 실제 네이버 검색 결과를 수집하면서 지속적으로 확장해야 한다. 권장 프로세스:

1. **데이터 수집**: area-explore 결과의 `category` 필드를 로깅
2. **분석**: 고유 1차 토큰 빈도 집계
3. **판단**: 빈도 3 미만이면서 기존 그룹과 의미적으로 유사한 토큰 → 동의어 추가
4. **검증**: 병합 후 서브카테고리 수가 MAX_SUBCATEGORIES 이하인지 확인

```python
# 백엔드에서 카테고리 로깅 (개발 단계에서만)
import collections
_category_counter = collections.Counter()

def _extract_place_items(data, max_items):
    # ... 기존 코드 ...
    for place in place_list[:max_items]:
        cat = place.get("category", "")
        _category_counter[cat] += 1  # 카테고리 빈도 수집
    # ...

# /api/local/debug/categories — 개발용 디버그 엔드포인트
@router.get("/debug/categories")
async def debug_categories():
    return {"categories": _category_counter.most_common(100)}
```

## 부록 C: 주유소 가격 미수집 문제 (참고)

사용자가 "주유소 가격이 안 나온다"고 보고한 문제는 SSE/카테고리와는 별개 이슈이나, 관련 정보를 기록한다.

**원인 분석**: 네이버 allSearch API 응답의 `petrolInfo` 필드가 항상 포함되지는 않는다. 특정 검색어(`주유소`)로 검색할 때만 포함되며, 일반 검색어(`오리역 근처`)로 검색하면 누락될 수 있다.

**현재 코드의 올바른 처리**:
```python
petrol = place.get("petrolInfo")
if petrol and isinstance(petrol, dict):
    item["petrol_info"] = { ... }
```

**가능한 개선**:
- area-explore에서 주유소 카테고리 검색 시 검색어를 `"{location} 주유소 가격"`으로 변경하여 가격 정보 포함 확률 향상
- `petrolInfo`가 없는 주유소 아이템에 대해 개별 장소 페이지 크롤링으로 가격 보완 (추가 비용 발생)

---

> **다음 단계**: Phase 1 (스트리밍 + 프로그레시브 UI + 카테고리 병합)을 먼저 구현하고, 사용자 피드백을 받은 후 Phase 2~3 진행.
