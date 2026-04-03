# 전단지 뷰어 & 커뮤니티 에디터 개선 기획서

## 1. 전단지 뷰어 개선

### 1.1 문제점
- 확대(zoom)는 가능하나 **확대 후 이동(pan/drag)이 불가**
- 중앙 부분만 보이고 나머지는 확인 불가
- 모바일 터치 제스처 미지원

### 1.2 개선 사항

#### A. 드래그 이동 (Pan) 시스템
```
구현 방식: CSS transform + mousedown/mousemove/mouseup 이벤트
상태: { zoom: number, panX: number, panY: number, isDragging: boolean }
transform: `scale(${zoom}) translate(${panX}px, ${panY}px)`
```

**마우스 이벤트:**
- `onMouseDown` → isDragging = true, 시작점 기록
- `onMouseMove` → isDragging 중이면 delta 계산, panX/panY 업데이트
- `onMouseUp` → isDragging = false
- 커서: 기본 `grab`, 드래그 중 `grabbing`
- zoom === 1일 때는 드래그 비활성화 (불필요)

**마우스 휠 줌:**
- `onWheel` → deltaY 기반 줌 조절
- 커서 위치 기준 줌 (transform-origin 동적 변경)
- `e.preventDefault()` 로 페이지 스크롤 방지

**더블클릭 줌:**
- 더블클릭 시 1x ↔ 2x 토글
- 클릭 위치 기준으로 줌인

#### B. 터치 제스처 (모바일)
- `onTouchStart/Move/End` 로 핀치투줌 + 스와이프
- 두 손가락 거리 변화 → 줌 비율
- 한 손가락 스와이프 → 페이지 넘기기 (좌우)
- 두 손가락 드래그 → 패닝

#### C. 줌 컨트롤 개선
- 현재: +/- 버튼 + 퍼센트 표시
- 추가: 
  - 「맞춤」 버튼 (fit to container)
  - 「원본」 버튼 (100%)  
  - 줌 슬라이더 (0.5x ~ 4x)
  - 미니맵 오버레이 (줌인 시 현재 보이는 영역 표시)

### 1.3 구현 파일
| 파일 | 변경 내용 |
|------|----------|
| `MartPage.jsx` | 줌/팬 상태 관리, 이벤트 핸들러, 미니맵 |
| `MartPage.module.css` | grab/grabbing 커서, 미니맵 스타일 |

### 1.4 핵심 코드 구조
```jsx
// 상태
const [zoom, setZoom] = useState(1);
const [pan, setPan] = useState({ x: 0, y: 0 });
const [isDragging, setIsDragging] = useState(false);
const dragStart = useRef({ x: 0, y: 0 });

// 컨테이너
<div 
  className={s.flyerViewer}
  onMouseDown={handleMouseDown}
  onMouseMove={handleMouseMove}
  onMouseUp={handleMouseUp}
  onMouseLeave={handleMouseUp}
  onWheel={handleWheel}
  style={{ cursor: zoom > 1 ? (isDragging ? 'grabbing' : 'grab') : 'default' }}
>
  <img 
    style={{ 
      transform: `scale(${zoom}) translate(${pan.x}px, ${pan.y}px)`,
      transformOrigin: 'center center'
    }}
    draggable={false}
  />
</div>
```

---

## 2. 커뮤니티 에디터 개선

### 2.1 문제점
- `<textarea rows={5}>` — 5줄짜리 일반 텍스트만 가능
- 이미지를 중간중간 삽입 불가 (별도 섹션)
- 품목명 선택이 `<datalist>`로 수백 개 항목 나열
- 에디터가 너무 작고 긴 글 불편

### 2.2 에디터 선택: TipTap

**선택 이유:**
- React 네이티브 지원 (Vue에서 포크)
- 확장 시스템 (Extension) 으로 필요한 기능만 추가
- 인라인 이미지, 마크다운 단축키, 링크 삽입 지원
- 경량 (core ~40KB gzip)
- 커스텀 노드/마크 쉬움
- MIT 라이선스

**비교:**
| 기준 | TipTap | Slate.js | Draft.js |
|------|--------|---------|---------|
| React 지원 | ✅ 네이티브 | ✅ 네이티브 | ✅ 네이티브 |
| 인라인 이미지 | ✅ 내장 | ⚠️ 커스텀 필요 | ⚠️ 복잡 |
| 마크다운 | ✅ 확장 | ⚠️ 직접 구현 | ❌ |
| 학습 곡선 | 낮음 | 높음 | 중간 |
| 유지보수 | 활발 | 활발 | 페이스북 중단 |

### 2.3 에디터 기능 설계

#### A. 툴바
```
[B] [I] [U] [S] | [H1] [H2] | [•] [1.] | [🔗] [📷] [📹] | [미리보기]
```
- **텍스트 서식**: 볼드, 이탤릭, 밑줄, 취소선
- **제목**: H1, H2
- **리스트**: 순서없는/순서있는
- **삽입**: 링크, 이미지, 영상(URL)
- **미리보기**: 작성 중 미리보기 토글

#### B. 인라인 이미지 시스템
- **삽입 방법 3가지:**
  1. 툴바 📷 버튼 → 파일 선택
  2. 드래그 앤 드롭 → 에디터 영역에 이미지 파일 드롭
  3. 클립보드 붙여넣기 → Ctrl+V로 스크린샷 삽입
- **이미지 처리:**
  - 클라이언트에서 리사이즈 (max 1200px width)
  - Base64 → 서버 업로드 후 URL로 교체
  - 에디터 내 크기 조절 핸들 (드래그로 리사이즈)
  - 정렬: 왼쪽/중앙/오른쪽
- **API:** `POST /api/uploads/image` → `{ url: string }`

#### C. 에디터 레이아웃
- **최소 높이**: 300px (현재 5줄 → 15줄 이상)
- **자동 확장**: 내용에 따라 높이 자동 증가 (max 80vh)
- **전체화면 모드**: 에디터 풀스크린 토글
- **작성/미리보기 탭**: 좌우 분할 또는 탭 전환
- **글자 수 카운터**: 우측 하단

#### D. 품목 선택 개선 (핫딜 게시판)
- `<datalist>` 제거 → **자동완성 검색 드롭다운** 으로 교체
- 기존 autocomplete API 재사용 (`/api/search/autocomplete`)
- 드롭다운에 카테고리 경로, 현재가 표시
- 200ms 디바운스, 1글자 이상부터 검색
- "새 상품 등록" 옵션 (검색 결과 없을 때)
- 선택 시 카테고리 자동 채움, 적정가 자동 표시

#### E. 가격 검증 강화
- 현재: 단순 텍스트 (🔥 ✅ ⚠️ 🚨)
- 개선:
  - 가격 위치 바 (전체 가격 분포에서 입력가 위치)
  - 최근 30일 평균가 대비 할인율 자동 계산
  - 비슷한 핫딜 최근 게시글 3개 표시 (비교용)

### 2.4 구현 파일
| 파일 | 변경 내용 |
|------|----------|
| `package.json` | `@tiptap/react`, `@tiptap/starter-kit`, `@tiptap/extension-image`, `@tiptap/extension-link` 추가 |
| `components/editor/PostEditor.jsx` | 새 리치텍스트 에디터 컴포넌트 |
| `components/editor/EditorToolbar.jsx` | 툴바 컴포넌트 |
| `components/editor/PostEditor.module.css` | 에디터 스타일 |
| `CommunityPage.jsx` | `<textarea>` → `<PostEditor>` 교체, 이미지 업로드 로직 |
| website backend `api/routes/uploads.py` | 이미지 업로드 API |

### 2.5 데이터 형식 변경
```
현재: { content: "평문 텍스트", images: ["base64..."] }
변경: { content: "<p>HTML 콘텐츠 <img src='...' /></p>", content_type: "html" }
```
- 기존 평문 게시글과 호환: `content_type` 필드로 구분
- HTML 렌더링 시 XSS 방지: DOMPurify로 sanitize

---

## 3. 테스트 시나리오

### 전단지 뷰어
1. 줌인 후 마우스 드래그로 상하좌우 이동 가능 확인
2. 마우스 휠로 커서 위치 기준 줌 가능 확인
3. 줌 1x에서는 드래그 커서 미표시
4. 더블클릭 줌 토글 작동 확인
5. 페이지 넘기기 시 줌/팬 리셋 확인
6. 맞춤/원본 버튼 작동

### 커뮤니티 에디터
1. 볼드/이탤릭 등 서식 적용 확인
2. 텍스트 중간에 이미지 삽입 → 위치 유지 확인
3. 드래그앤드롭 이미지 업로드
4. 클립보드 붙여넣기 이미지 삽입
5. 품목 검색 자동완성 작동 (1글자 이상)
6. 에디터 자동 높이 확장
7. 기존 평문 게시글 호환 표시
8. XSS 공격 문자열 sanitize 확인
