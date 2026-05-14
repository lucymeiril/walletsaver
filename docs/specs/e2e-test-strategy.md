# WalletSavior E2E 테스트 전략

## 0. 왜 지금 테스트가 실패하는가

현재 테스트는 **수는 많지만 실제 배포 형태를 거의 검증하지 못한다.**

- `packages\website\backend\tests` 기준 **247개 테스트 수집**은 되지만, 이것만으로는 서비스 경계가 보장되지 않는다.
- `packages\integration-tests`는 **164개**가 존재하지만 실제 서버 6개를 띄운 상태가 아니라 `TestClient`, `storage=None`, 인메모리 DB 중심이다.
- 실제로 현재 통합 테스트도 인증/응답 계약과 어긋난 실패가 다수 존재한다.
  - crawler-admin 보호 엔드포인트를 `X-API-Key` 없이 호출
  - autocomplete 응답 shape 기대가 실제와 다름
  - auth/register, token refresh 기대가 실제 쿠키/JWT 동작과 어긋남
- 즉, **"테스트 통과 = 런타임 정상"이 아니다.**

이 문서는 **실제 서버 6개**, **실제 DB**, **실제 인증**, **실제 서비스 간 호출**, **실제 데이터 흐름**을 기준으로 회귀를 막기 위한 E2E 전략이다.

---

## 1. 목표와 원칙

### 목표
1. 크롤러 → DB-admin → Website API → Frontend 데이터 흐름을 실제로 검증한다.
2. 프론트엔드가 호출하는 API가 **실제로 존재하고**, **shape가 맞고**, **인증도 맞는지** 검증한다.
3. 회귀가 가장 치명적인 지점(P0)을 PR 단계에서 즉시 잡는다.
4. 외부 사이트 의존성이 있는 라이브 크롤링은 nightly로 분리하되, 합성(synthetic) E2E는 항상 재현 가능하게 만든다.

### 원칙
- **mock 금지**: 서비스 경계 테스트에서는 mock/fake storage 금지.
- **실제 프로세스 사용**: 3 backend + 3 frontend를 실제 포트로 띄운다.
- **실제 인증 사용**: 쿠키/JWT/X-API-Key를 우회하지 않는다.
- **실제 DB 검증**: HTTP 200만 보지 말고 `py -c`로 DB row를 확인한다.
- **실패를 설명하는 출력**: 모든 스크립트는 `PASS/FAIL + 이유`를 출력한다.

### 테스트 계층
- **P0 PR Gate**: 인증, 핵심 CRUD, synthetic full pipeline, 필수 페이지 계약
- **P1 Nightly**: 실제 crawler run, SSE 장기 스트림, circuit breaker, 동시성
- **P2 Weekly/Release**: 데이터 품질, rate limit, soft-delete, 성능/복구

---

## 2. 테스트 환경 구축 (A. 테스트 환경 구축)

### 2.1 서비스 토폴로지

| 서비스 | 포트 | 역할 |
|---|---:|---|
| website backend | 8000 | 사용자 API |
| website frontend | 5173 | 사용자 UI |
| crawler-admin backend | 8001 | 크롤러 실행/상태/API |
| crawler-admin frontend | 5174 | 크롤러 관리 UI |
| db-admin backend | 8002 | 데이터/검수/API |
| db-admin frontend | 5175 | DB 관리 UI |

기본 전체 기동 스크립트는 `start-all.ps1`이며, 위 6개를 한 번에 띄운다.

### 2.2 표준 테스트 환경 변수

E2E는 아래 값을 기본값으로 고정한다.

```powershell
$env:REQUIRE_AUTH = 'true'
$env:DEBUG = 'true'
$env:COOKIE_SECURE = 'false'
$env:CRAWLER_ADMIN_API_KEY = 'ws-crawler-admin-test-key'
$env:DB_ADMIN_EMAIL = 'admin@walletsavior.com'
$env:DB_ADMIN_PASSWORD = 'admin1234!'
$env:CORS_ALLOWED_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175'
```

주의:
- db-admin은 startup 시 기본 관리자 `admin@walletsavior.com / admin1234!`를 seed한다.
- crawler-admin API는 `X-API-Key`가 필요하다.
- crawler-admin pipeline → db-admin은 현재 JWT 로그인 기반(`DB_ADMIN_EMAIL`, `DB_ADMIN_PASSWORD`)도 검증해야 한다.

### 2.3 전체 서버 시작 스크립트

```powershell
# Test: 전체 6개 서버 시작
$root = 'E:\pdf\capston01\walletSavior'
$env:REQUIRE_AUTH = 'true'
$env:DEBUG = 'true'
$env:COOKIE_SECURE = 'false'
$env:CRAWLER_ADMIN_API_KEY = 'ws-crawler-admin-test-key'
$env:DB_ADMIN_EMAIL = 'admin@walletsavior.com'
$env:DB_ADMIN_PASSWORD = 'admin1234!'
$env:CORS_ALLOWED_ORIGINS = 'http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:5175,http://127.0.0.1:5175'

$proc = Start-Process powershell -PassThru -WindowStyle Hidden -ArgumentList @(
  '-NoProfile',
  '-ExecutionPolicy','Bypass',
  '-File', (Join-Path $root 'start-all.ps1')
)

Start-Sleep -Seconds 15

$targets = @(
  @{Name='website backend'; Url='http://127.0.0.1:8000/api/health'},
  @{Name='website frontend'; Url='http://127.0.0.1:5173'},
  @{Name='crawler backend'; Url='http://127.0.0.1:8001/health'},
  @{Name='crawler frontend'; Url='http://127.0.0.1:5174'},
  @{Name='db-admin backend'; Url='http://127.0.0.1:8002/health'},
  @{Name='db-admin frontend'; Url='http://127.0.0.1:5175'}
)

$allOk = $true
foreach ($t in $targets) {
  try {
    $resp = Invoke-WebRequest -Uri $t.Url -UseBasicParsing -TimeoutSec 5
    if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500) {
      Write-Host "✅ PASS: $($t.Name) reachable ($($resp.StatusCode))"
    } else {
      Write-Host "❌ FAIL: $($t.Name) unexpected status $($resp.StatusCode)"
      $allOk = $false
    }
  } catch {
    Write-Host "❌ FAIL: $($t.Name) not reachable - $($_.Exception.Message)"
    $allOk = $false
  }
}

if ($allOk) {
  Write-Host '✅ PASS: 전체 6개 서버 기동 확인'
} else {
  Write-Host '❌ FAIL: 서버 기동 실패'
}
```

### 2.4 DB 초기화 + 시드 데이터 적재

테스트는 **항상 deterministic seed**에서 시작해야 한다. 권장 순서:
1. db-admin 로그인
2. `/api/admin/reset-all` 호출
3. `py -c`로 카테고리/상품/가격/사용자 seed 주입

```powershell
# Test: DB 초기화 + seed
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$root = 'E:\pdf\capston01\walletSavior'

$loginBody = @{ email = 'admin@walletsavior.com'; password = 'admin1234!' } | ConvertTo-Json
$loginResp = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/auth/login' -Method POST -ContentType 'application/json' -Body $loginBody -UseBasicParsing
if ($loginResp.StatusCode -ne 200) { Fail "db-admin 로그인 실패 ($($loginResp.StatusCode))" }
$dbToken = ($loginResp.Content | ConvertFrom-Json).access_token
$headers = @{ Authorization = "Bearer $dbToken"; 'Content-Type' = 'application/json' }
Pass 'db-admin 로그인'

$resetBody = @{ confirm = 'RESET_ALL_DATA' } | ConvertTo-Json
$resetResp = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/admin/reset-all' -Method POST -Headers $headers -Body $resetBody -UseBasicParsing
if ($resetResp.StatusCode -ne 200) { Fail "reset-all 실패 ($($resetResp.StatusCode))" }
Pass 'reset-all 완료'

$seedCode = @'
from pathlib import Path
import sys
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

root = Path(r"E:\pdf\capston01\walletSavior")
sys.path.insert(0, str(root / "packages" / "db-admin" / "backend"))
from storage.models import Base, Category, Product, BaselinePrice, DiscountHistory, User, UserRole
from api.auth import hash_password

engine = create_engine(f"sqlite:///{root / 'packages' / 'db-admin' / 'backend' / 'walletguardian.db'}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)
s = Session()

cats = [
    Category(id='food', name='식품', depth=0, sort_order=1, is_active=True),
    Category(id='food.vegetable', name='채소', parent_id='food', depth=1, sort_order=1, is_active=True),
    Category(id='food.meat', name='축산', parent_id='food', depth=1, sort_order=2, is_active=True),
]
for c in cats:
    if not s.get(Category, c.id):
        s.add(c)
s.flush()

products = [
    Product(name='QA 양파 1kg', category_id='food.vegetable', unit='1kg', is_active=True, source_type='mart_crawl'),
    Product(name='QA 삼겹살 100g', category_id='food.meat', unit='100g', is_active=True, source_type='mart_crawl'),
    Product(name='QA 우유 900ml', category_id='food.vegetable', unit='900ml', is_active=True, source_type='baseline'),
]
for p in products:
    s.add(p)
s.flush()

now = datetime.utcnow()
for p in products:
    s.add(BaselinePrice(product_id=p.id, price=3000 if '양파' in p.name else 1800, source='KAMIS', unit=p.unit, recorded_at=now - timedelta(days=1)))

s.add(DiscountHistory(product_id=products[0].id, price=1980, original_price=2980, discount_rate=0.33, source='emart', crawled_at=now))
s.add(DiscountHistory(product_id=products[0].id, price=2100, original_price=2980, discount_rate=0.29, source='homeplus', crawled_at=now))
s.add(DiscountHistory(product_id=products[1].id, price=1150, original_price=1890, discount_rate=0.39, source='emart', crawled_at=now))

if not s.query(User).filter(User.email == 'qa-user@walletsavior.local').first():
    s.add(User(email='qa-user@walletsavior.local', hashed_password=hash_password('qa123456!'), nickname='QA사용자', role=UserRole.USER, is_active=True))

s.commit()
print('seeded')
'@

$seedResult = py -c $seedCode
if ($LASTEXITCODE -ne 0) { Fail 'seed 스크립트 실패' }
Pass 'seed 데이터 적재'
```

### 2.5 테스트 간 상태 리셋

매 테스트 실행 전후 리셋 원칙:
- 서버 프로세스: `stop.ps1`로 종료
- DB 상태: `reset-all` + 재시드
- ingestion 큐: `/api/ingestions/cleanup`
- crawler DLQ: `packages\crawler-admin\backend\data\dead_letter\*.jsonl` 비움
- 브라우저 수동 테스트 전: 새 브라우저 프로필/시크릿 창 사용

```powershell
# Test: 런 간 상태 초기화
$root = 'E:\pdf\capston01\walletSavior'
& (Join-Path $root 'stop.ps1') | Out-Null

$dlq = Join-Path $root 'packages\crawler-admin\backend\data\dead_letter'
if (Test-Path $dlq) {
  Get-ChildItem $dlq -Filter '*.jsonl' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
}

Write-Host '✅ PASS: 프로세스/DLQ 정리 완료'
```

---

## 3. 서비스 간 통합 테스트 (B. 서비스 간 통합 테스트)

### 3.1 반드시 검증할 호출 매트릭스

| Caller | Callee | 엔드포인트/채널 | 꼭 확인할 것 | 우선순위 |
|---|---|---|---|---|
| crawler-admin pipeline | db-admin | `POST /api/auth/login` | JWT 발급, 200, refresh 가능 | P0 |
| crawler-admin pipeline | db-admin | `POST /api/ingestions` | 무인증 401, 인증 200, payload 저장 | P0 |
| crawler-admin pipeline | db-admin | `POST /api/prices/bulk` | moderator/service 권한 필요, 201 | P1 |
| crawler-admin backend | db-admin | `/api/ingestions/*` proxy | 헤더 전달, 상태/본문 보존 | P0 |
| website backend | db-admin sqlite/shared DB | 상품/가격 조회 | website 응답 shape가 실제 DB와 일치 | P0 |
| website frontend | website backend | 모든 `/api/*` 호출 | 엔드포인트 존재, response shape 일치 | P0 |
| crawler-admin frontend | crawler-admin backend | `/api/crawlers/*`, `/status/stream` | X-API-Key 보호 + SSE 예외 규칙 | P0 |
| website frontend(Local) | website backend | `/api/local/area-explore-stream` | stream chunk/종료/error shape | P1 |

### 3.2 핵심 통합 테스트 목록

#### P0
1. crawler-admin → db-admin 로그인 성공
2. crawler-admin → db-admin ingestion 제출 시 무인증 401
3. crawler-admin → db-admin ingestion 제출 시 Bearer 200
4. crawler-admin proxy(`/api/ingestions`)가 db-admin 상태코드/본문을 그대로 전달
5. crawler-admin 일반 API는 `X-API-Key` 없으면 401
6. crawler-admin SSE는 헤더 없이 연결 가능해야 함(브라우저 EventSource 제약)
7. website API가 seed된 DB 가격 데이터를 실제로 읽어 반환
8. website 프론트가 기대하는 필드(`data`, `meta`, `item_name`, `price_at_add` 등)가 실제 응답에 존재

#### P1
9. pipeline access token 만료 후 refresh/login 재시도
10. bulk price 업로드 권한(role) 검증
11. db-admin review 승인 후 website 검색 결과에 반영
12. SSE reconnect 후 최종 상태 메시지 수신

### 3.3 복붙 가능한 통합 검증 스크립트

#### 크롤러→DB-admin ingestion 인증

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$body = @{
  crawler_name = 'qa-pipeline'
  crawl_status = 'success'
  schema_type = 'DiscountItem'
  strategy_used = 'synthetic'
  duration_seconds = 1.23
  items = @(@{
    name = 'QA 통합 양파 1kg'
    sale_price = 1990
    original_price = 2990
    discount_percent = 33
    store = 'emart'
    detail_url = 'https://example.com/qa-onion'
    category = 'food.vegetable'
    unit = '1kg'
  })
  errors = @()
} | ConvertTo-Json -Depth 8

# 1) 무인증 401이어야 함
try {
  $unauth = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/ingestions' -Method POST -ContentType 'application/json' -Body $body -UseBasicParsing -ErrorAction Stop
  Fail "무인증 호출이 예상외로 성공 ($($unauth.StatusCode))"
} catch {
  $status = $_.Exception.Response.StatusCode.value__
  if ($status -eq 401) { Pass 'ingestion 무인증 401' } else { Fail "무인증 상태코드=$status" }
}

# 2) 인증 후 200이어야 함
$loginBody = @{ email = 'admin@walletsavior.com'; password = 'admin1234!' } | ConvertTo-Json
$loginResp = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/auth/login' -Method POST -ContentType 'application/json' -Body $loginBody -UseBasicParsing
$token = ($loginResp.Content | ConvertFrom-Json).access_token
$headers = @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' }
$ok = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/ingestions' -Method POST -Headers $headers -Body $body -UseBasicParsing
if ($ok.StatusCode -eq 200) {
  $json = $ok.Content | ConvertFrom-Json
  Pass "ingestion 인증 성공 (id=$($json.id))"
} else {
  Fail "ingestion 인증 실패 ($($ok.StatusCode))"
}
```

#### crawler-admin 보호 API + SSE 예외

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

# 일반 API는 X-API-Key 필요
try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8001/api/crawlers' -UseBasicParsing -ErrorAction Stop | Out-Null
  Fail 'crawler 목록이 무인증으로 열림'
} catch {
  $status = $_.Exception.Response.StatusCode.value__
  if ($status -eq 401) { Pass 'crawler 목록 무인증 401' } else { Fail "crawler 목록 상태코드=$status" }
}

$headers = @{ 'X-API-Key' = 'ws-crawler-admin-test-key' }
$listResp = Invoke-WebRequest -Uri 'http://127.0.0.1:8001/api/crawlers' -Headers $headers -UseBasicParsing
if ($listResp.StatusCode -ne 200) { Fail 'crawler 목록 인증 실패' }
$listJson = $listResp.Content | ConvertFrom-Json
$crawlerId = $listJson.crawlers[0].id
Pass "crawler 목록 인증 성공 ($crawlerId)"

# SSE는 EventSource 제약 때문에 헤더 없이도 열려야 함
$stream = curl.exe -N -s --max-time 5 "http://127.0.0.1:8001/api/crawlers/$crawlerId/status/stream"
if ($LASTEXITCODE -eq 0) {
  Pass 'crawler SSE 연결 가능'
} else {
  Fail 'crawler SSE 연결 실패'
}
```

---

## 4. 전체 파이프라인 E2E (C. 전체 파이프라인 E2E)

### 4.1 두 종류로 나눠야 한다

#### 1) Synthetic Full Pipeline (PR Gate, P0)
외부 사이트 의존성 없이 항상 재현 가능한 전체 흐름.

흐름:
1. ingestion payload 생성
2. db-admin 인증 후 제출
3. ingestion 상세 조회
4. crawler-review 승인
5. db-review 승인
6. DB row 생성 확인
7. website `/api/products/search`에서 검색됨 확인
8. website `/api/products/{id}/price-compare` shape 확인
9. frontend가 사용하는 필드 존재 확인

#### 2) Live Crawl Full Pipeline (Nightly, P1)
실제 crawler를 실행해 외부 사이트 변화까지 감시.

흐름:
1. crawler-admin에서 실제 crawler 실행
2. status/stream으로 상태 추적
3. crawl log 또는 ingestion queue 증가 확인
4. db-admin review 또는 auto path 확인
5. website API에서 신규 데이터 관찰

**PR에서는 synthetic**, **nightly에서는 live crawl**을 돌려야 한다.

### 4.2 Synthetic Full Pipeline 스크립트

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$root = 'E:\pdf\capston01\walletSavior'

# 로그인
$loginBody = @{ email = 'admin@walletsavior.com'; password = 'admin1234!' } | ConvertTo-Json
$loginResp = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/auth/login' -Method POST -ContentType 'application/json' -Body $loginBody -UseBasicParsing
$token = ($loginResp.Content | ConvertFrom-Json).access_token
$headers = @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' }

# 1. submit
$payload = @{
  crawler_name = 'qa-full-pipeline'
  crawl_status = 'success'
  schema_type = 'DiscountItem'
  strategy_used = 'synthetic'
  duration_seconds = 2.34
  items = @(
    @{
      name = 'QA 파이프라인 양파 1kg'
      sale_price = 1870
      original_price = 2870
      discount_percent = 35
      store = 'emart'
      detail_url = 'https://example.com/qa-pipeline-onion'
      category = 'food.vegetable'
      unit = '1kg'
    },
    @{
      name = 'QA 파이프라인 양파 1kg'
      sale_price = 1950
      original_price = 2870
      discount_percent = 32
      store = 'homeplus'
      detail_url = 'https://example.com/qa-pipeline-onion-2'
      category = 'food.vegetable'
      unit = '1kg'
    }
  )
  errors = @()
} | ConvertTo-Json -Depth 8

$submit = Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/ingestions' -Method POST -Headers $headers -Body $payload -UseBasicParsing
if ($submit.StatusCode -ne 200) { Fail 'ingestion submit 실패' }
$ingestionId = ($submit.Content | ConvertFrom-Json).id
Pass "ingestion submit ($ingestionId)"

# 2. 상세 확인
$detail = Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/ingestions/$ingestionId" -Headers $headers -UseBasicParsing
$detailJson = $detail.Content | ConvertFrom-Json
if ($detailJson.items_count -ge 2 -and $detailJson.status -eq 'pending') { Pass 'ingestion 상세 저장 확인' } else { Fail 'ingestion 상세 저장 불일치' }

# 3. crawler review approve
$approve1 = @{ action = 'approve'; notes = 'qa crawler review' } | ConvertTo-Json
$r1 = Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/ingestions/$ingestionId/crawler-review" -Method POST -Headers $headers -Body $approve1 -UseBasicParsing
if (($r1.Content | ConvertFrom-Json).status -eq 'crawler_approved') { Pass 'crawler-review 승인' } else { Fail 'crawler-review 실패' }

# 4. db review approve
$approve2 = @{ action = 'approve'; notes = 'qa db review' } | ConvertTo-Json
$r2 = Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/ingestions/$ingestionId/db-review" -Method POST -Headers $headers -Body $approve2 -UseBasicParsing
$r2Json = $r2.Content | ConvertFrom-Json
if ($r2Json.status -eq 'approved' -and $r2Json.saved -ge 2) { Pass 'db-review 승인 및 실제 저장' } else { Fail 'db-review 실패' }

# 5. DB 확인
$dbCheck = @'
from pathlib import Path
import sqlite3
root = Path(r"E:\pdf\capston01\walletSavior")
db = root / "packages" / "db-admin" / "backend" / "walletguardian.db"
conn = sqlite3.connect(db)
cur = conn.cursor()
product = cur.execute("select id from products where name=? order by id desc limit 1", ('QA 파이프라인 양파 1kg',)).fetchone()
if not product:
    print('NO_PRODUCT')
else:
    pid = product[0]
    cnt = cur.execute("select count(*) from discount_history where product_id=?", (pid,)).fetchone()[0]
    print(f'{pid}:{cnt}')
'@
$dbResult = py -c $dbCheck
if ($dbResult -eq 'NO_PRODUCT') { Fail 'DB product 미생성' }
$parts = $dbResult.Trim().Split(':')
if ([int]$parts[1] -ge 2) { Pass 'DB discount_history 적재 확인' } else { Fail 'DB discount_history 건수 부족' }
$productId = [int]$parts[0]

# 6. website API 검색
$search = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/products/search?q=QA%20파이프라인%20양파' -UseBasicParsing
$searchJson = $search.Content | ConvertFrom-Json
$match = $searchJson.data | Where-Object { $_.id -eq $productId }
if ($match) { Pass 'website 검색 반영' } else { Fail 'website 검색 미반영' }

# 7. price-compare shape = frontend modal이 기대하는 데이터
$compare = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/products/$productId/price-compare" -UseBasicParsing
$compareJson = $compare.Content | ConvertFrom-Json
$compareData = $compareJson.data
if ($compareData -and (($compareData.other_stores.Count -ge 1) -or ($compareData.stores.Count -ge 1))) {
  Pass 'price-compare 다중 스토어 shape 확인'
} else {
  Fail 'price-compare multi-store shape 없음'
}
```

### 4.3 Live Crawl Nightly 스크립트

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$crawlerHeaders = @{ 'X-API-Key' = 'ws-crawler-admin-test-key' }
$list = Invoke-WebRequest -Uri 'http://127.0.0.1:8001/api/crawlers' -Headers $crawlerHeaders -UseBasicParsing
$crawlerId = (($list.Content | ConvertFrom-Json).crawlers | Select-Object -First 1).id
if (-not $crawlerId) { Fail '실행할 crawler 없음' }

$run = Invoke-WebRequest -Uri "http://127.0.0.1:8001/api/crawlers/$crawlerId/run" -Method POST -Headers $crawlerHeaders -UseBasicParsing
if ($run.StatusCode -ne 200) { Fail 'crawler run 호출 실패' }
Pass "crawler 실행 요청 ($crawlerId)"

Start-Sleep -Seconds 20

$stream = curl.exe -N -s --max-time 10 "http://127.0.0.1:8001/api/crawlers/$crawlerId/status/stream"
if ($LASTEXITCODE -eq 0) { Pass 'crawler status stream 수신' } else { Fail 'crawler status stream 실패' }
```

---

## 5. 프론트엔드-백엔드 계약 테스트 (D. 프론트엔드-백엔드 계약 테스트)

### 5.1 페이지별 계약 매트릭스

> 원칙: **모든 페이지는 "엔드포인트 존재 + 응답 shape + 에러 처리 + 인증 여부"를 검증**한다.

| 페이지/컴포넌트 | 호출 API | 반드시 검증할 것 | 우선순위 |
|---|---|---|---|
| HomePage | `/api/dashboard`, `/api/posts`, `/api/gas/nearby`, `/api/hotdeals`, `/api/marts/{store}/promotions` | dashboard aggregate shape, 섹션별 fallback | P0 |
| HotdealPage | `/api/hotdeals`, `/api/hotdeals/sources`, `/api/products/search`, comments/vote | 목록/상세/댓글/투표 계약 | P1 |
| MartPage | `/api/marts/{store}/promotions`, `/api/marts/{store}/flyers`, `/api/products/search` | 매장 키별 응답 shape | P1 |
| LocalPage | `/api/local/geocode`, `/api/local/naver-search`, `/api/local/subcategory-search`, `/api/local/area-explore-stream` | SSE chunk shape, geocode 실패 처리 | P1 |
| PricePage | `/api/products/search`, `/api/products/{id}`, `/api/products/{id}/price-history`, `/api/hotdeals` | 상품 상세/chart shape | P0 |
| CategoryComparePage | `/api/products/category/{categoryId}/compare` | `summary/products/alternatives/pagination` + `per_100g` | P1 |
| SearchPage | `/api/search`, `/api/search/autocomplete`, `/api/search/trending` | 자동완성 구조, Enter submit, type filter | P0 |
| CommunityPage | `/api/products/search`, `/api/posts`, `/api/posts/{id}`, comments/vote, `/suggested-tier` | `product_ids` 저장, 댓글/투표 동작 | P0 |
| ProfilePage | `/api/profile`, `/api/profile/activity` | GET/PUT/DELETE path, soft-delete 이후 차단 | P0 |
| WishlistPage | `/api/wishlist`, `PUT/DELETE /api/wishlist/{id}` | field 이름 일치, 목표가 수정 | P0 |
| AuthCallback | `/api/auth/me` | 쿠키 기반 로그인 완료 처리 | P1 |
| ProductDetailModal | `/api/products/{id}/price-compare`, `/api/products/{id}/price-history`, `/api/wishlist` | price-compare shape, wishlist add | P0 |
| SearchAutocomplete | `/api/search/autocomplete`, `/api/search/trending`, `/api/search/track` | 키보드/Enter/클릭 동작 | P0 |
| LoginModal/AuthService | `/api/auth/login`, `/api/auth/register`, `/api/auth/logout`, `/api/auth/refresh`, `/api/auth/oauth/*` | 401→refresh→재시도 흐름 | P0 |
| cartStore + appStore.shoppingList | `/api/cart`, `/api/cart/merge` | 두 cart 시스템 동기화 | P0 |

### 특별히 반드시 넣어야 할 회귀 테스트

1. **Cart sync**
   - `appStore.shoppingList`에 추가
   - `cartStore.items`에도 반영
   - 로그인 후 `/api/cart/merge` 호출
   - 다시 `/api/cart` 조회 시 동일 item 존재

2. **Community product 연결**
   - 프론트는 현재 선택 상품 상태(`wSelectedProducts`)를 들고 있지만, write payload에 `product_ids` 누락 위험이 있다.
   - 작성 후 DB의 `posts.product_id`가 실제로 저장되었는지 검증해야 한다.

3. **Product modal price compare**
   - `/api/products/{id}/price-compare`가 404가 아니어야 함
   - `other_stores` 또는 `stores` 배열이 있어야 함
   - 매장별 `price`, `source/store` 필드가 있어야 함

4. **Search autocomplete**
   - 현재 프론트는 구조화된 `{keywords, products, total_*}`를 기대한다.
   - 단순 list만 반환하면 깨진다.

### 5.2 핵심 계약 스크립트

#### Cart: add → fetch → item appears

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

# login
$loginBody = @{ email = 'qa-user@walletsavior.local'; password = 'qa123456!' } | ConvertTo-Json
$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$login = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/login' -Method POST -ContentType 'application/json' -Body $loginBody -WebSession $sess -UseBasicParsing
if ($login.StatusCode -ne 200) { Fail 'website login 실패' }
Pass 'website login'

# add cart item
$cartBody = @{ product_id = 1; item_name = 'QA 양파 1kg'; item_price = 1990; quantity = 1; store_name = 'emart' } | ConvertTo-Json
$add = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/cart' -Method POST -ContentType 'application/json' -Body $cartBody -WebSession $sess -UseBasicParsing
if ($add.StatusCode -ne 200) { Fail 'cart add 실패' }
Pass 'cart add'

# fetch cart
$get = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/cart' -WebSession $sess -UseBasicParsing
$data = ($get.Content | ConvertFrom-Json).data
$item = $data | Where-Object { $_.item_name -eq 'QA 양파 1kg' }
if ($item -and $item.product_id -and $item.item_price -eq 1990 -and $item.quantity -ge 1) {
  Pass 'cart fetch shape OK'
} else {
  Fail 'cart fetch 결과 불일치'
}
```

#### Wishlist: add → fetch → correct field names

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/login' -Method POST -ContentType 'application/json' -Body (@{ email='qa-user@walletsavior.local'; password='qa123456!' } | ConvertTo-Json) -WebSession $sess -UseBasicParsing | Out-Null

$wishBody = @{ product_id = 1; item_name = 'QA 양파 1kg'; notify_on_drop = $true } | ConvertTo-Json
$add = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/wishlist' -Method POST -ContentType 'application/json' -Body $wishBody -WebSession $sess -UseBasicParsing
if ($add.StatusCode -ne 200) { Fail 'wishlist add 실패' }

$get = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/wishlist' -WebSession $sess -UseBasicParsing
$item = (($get.Content | ConvertFrom-Json).data | Where-Object { $_.item_name -eq 'QA 양파 1kg' } | Select-Object -First 1)
if ($item -and $item.product_id -and $null -ne $item.price_at_add -and $item.PSObject.Properties.Name -contains 'current_price') {
  Pass 'wishlist field names OK'
} else {
  Fail 'wishlist field names mismatch'
}
```

#### Profile + soft delete + relogin block

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

# create fresh user
$reg = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/register' -Method POST -ContentType 'application/json' -Body (@{ email='qa-softdelete@walletsavior.local'; password='qa123456!'; nickname='소프트삭제QA' } | ConvertTo-Json) -UseBasicParsing
if ($reg.StatusCode -ne 201) { Fail 'register 실패' }
Pass 'register'

$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/login' -Method POST -ContentType 'application/json' -Body (@{ email='qa-softdelete@walletsavior.local'; password='qa123456!' } | ConvertTo-Json) -WebSession $sess -UseBasicParsing | Out-Null

$profile = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/profile' -WebSession $sess -UseBasicParsing
if ($profile.StatusCode -eq 200) { Pass 'profile GET' } else { Fail 'profile GET 실패' }

$update = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/profile' -Method PUT -ContentType 'application/json' -Body (@{ nickname='소프트삭제QA2'; bio='qa' } | ConvertTo-Json) -WebSession $sess -UseBasicParsing
if ($update.StatusCode -eq 200) { Pass 'profile PUT' } else { Fail 'profile PUT 실패' }

$delete = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/profile' -Method DELETE -WebSession $sess -UseBasicParsing
if ($delete.StatusCode -eq 200) { Pass 'profile DELETE(soft delete)' } else { Fail 'profile DELETE 실패' }

try {
  Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/login' -Method POST -ContentType 'application/json' -Body (@{ email='qa-softdelete@walletsavior.local'; password='qa123456!' } | ConvertTo-Json) -UseBasicParsing -ErrorAction Stop | Out-Null
  Fail 'soft-deleted user login unexpectedly succeeded'
} catch {
  $status = $_.Exception.Response.StatusCode.value__
  if ($status -eq 403) { Pass 'soft-deleted user login blocked' } else { Fail "soft-delete relogin status=$status" }
}
```

#### Activity: correct field names + rate limit behavior

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/login' -Method POST -ContentType 'application/json' -Body (@{ email='qa-user@walletsavior.local'; password='qa123456!' } | ConvertTo-Json) -WebSession $sess -UseBasicParsing | Out-Null

$trackBody = @{ activity_type='wishlist_add'; target_type='product'; target_id='1'; metadata=@{ name='QA 양파 1kg' } } | ConvertTo-Json -Depth 5
$t1 = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/activity/track' -Method POST -ContentType 'application/json' -Body $trackBody -WebSession $sess -UseBasicParsing
$t1Json = ($t1.Content | ConvertFrom-Json).data
if ($t1Json.status -eq 'tracked') { Pass 'activity tracked' } else { Fail 'activity tracked 실패' }

$t2 = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/activity/track' -Method POST -ContentType 'application/json' -Body $trackBody -WebSession $sess -UseBasicParsing
$t2Json = ($t2.Content | ConvertFrom-Json).data
if ($t2Json.status -eq 'rate_limited') { Pass 'activity rate limit 동작' } else { Fail 'activity rate limit 미동작' }
```

#### Community: post with product_id actually saved

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/login' -Method POST -ContentType 'application/json' -Body (@{ email='qa-user@walletsavior.local'; password='qa123456!' } | ConvertTo-Json) -WebSession $sess -UseBasicParsing | Out-Null

$payload = @{ title='QA 커뮤니티 상품연결'; content='연결 테스트'; post_type='hotdeal'; price=1990; original_price=2990; product_ids=@(1) } | ConvertTo-Json -Depth 5
$resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/posts' -Method POST -ContentType 'application/json' -Body $payload -WebSession $sess -UseBasicParsing
$postId = (($resp.Content | ConvertFrom-Json).data.id)
if (-not $postId) { Fail 'post 생성 실패' }
Pass "post 생성 ($postId)"

$dbCheck = @'
from pathlib import Path
import sqlite3
root = Path(r"E:\pdf\capston01\walletSavior")
db = root / "packages" / "db-admin" / "backend" / "walletguardian.db"
conn = sqlite3.connect(db)
cur = conn.cursor()
row = cur.execute("select product_id from posts where id=?", (int("""$postId"""),)).fetchone()
print('NULL' if row is None or row[0] is None else row[0])
'@
$result = py -c $dbCheck
if ($result -ne 'NULL') { Pass 'community post.product_id 저장 확인' } else { Fail 'community post.product_id 누락' }
```

#### Search: autocomplete + Enter submit contract

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$ac = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/search/autocomplete?q=QA' -UseBasicParsing
$acJson = $ac.Content | ConvertFrom-Json
if (($acJson.data.PSObject.Properties.Name -contains 'keywords') -and ($acJson.data.PSObject.Properties.Name -contains 'products')) {
  Pass 'autocomplete structured shape'
} else {
  Fail 'autocomplete shape mismatch'
}

$search = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/search?q=QA' -UseBasicParsing
$searchJson = $search.Content | ConvertFrom-Json
if ($searchJson.success -eq $true -and $searchJson.data.Count -ge 1) { Pass 'search submit result exists' } else { Fail 'search submit 결과 없음' }
```

---

## 6. 장애 상황 테스트 (E. 장애 상황 테스트)

### 6.1 필수 장애 시나리오

| 시나리오 | 기대 결과 | 우선순위 |
|---|---|---|
| DB-admin down | website health=`degraded`, circuit open, 사용자 API는 500 폭발 대신 graceful degradation | P0 |
| auth token expired | 401 후 refresh 또는 재로그인 유도, 무한 루프 금지 | P0 |
| crawler rate-limited | retry/backoff 기록, 실패 원인 보존, DLQ 또는 failed 상태 남김 | P1 |
| concurrent cart writes | 중복 row 폭증 금지, quantity 일관성 보장 | P0 |
| soft-deleted user login | 403, profile/cart/wishlist 접근 차단 | P0 |
| db-admin ingestion 401 | pipeline이 재로그인 후 재시도하거나 명확히 실패 기록 | P0 |

### 6.2 실행 스크립트

#### DB-admin 다운 → website circuit breaker

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$conn = Get-NetTCPConnection -State Listen -LocalPort 8002 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $conn) { Fail '8002 listener 없음' }
$pid = $conn.OwningProcess
& powershell -NoProfile -Command "& { $id = $args[0]; Stop-Process -Id $id -Force }" $pid
Start-Sleep -Seconds 3

$health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -UseBasicParsing
$healthJson = $health.Content | ConvertFrom-Json
if ($healthJson.status -in @('degraded','error')) {
  Pass "website health degraded when db-admin down ($($healthJson.status))"
} else {
  Fail 'website health가 degrade되지 않음'
}
```

#### Concurrent cart writes

```powershell
function Pass($msg) { Write-Host "✅ PASS: $msg" }
function Fail($msg) { Write-Host "❌ FAIL: $msg"; exit 1 }

$sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/auth/login' -Method POST -ContentType 'application/json' -Body (@{ email='qa-user@walletsavior.local'; password='qa123456!' } | ConvertTo-Json) -WebSession $sess -UseBasicParsing | Out-Null

1..5 | ForEach-Object {
  Start-Job -ScriptBlock {
    param($cookieHeader)
    $headers = @{ Cookie = $cookieHeader; 'Content-Type' = 'application/json' }
    $body = @{ product_id = 1; item_name = 'QA 양파 1kg'; item_price = 1990; quantity = 1; store_name='emart' } | ConvertTo-Json
    try {
      Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/cart' -Method POST -Headers $headers -Body $body -UseBasicParsing | Out-Null
    } catch {}
  } -ArgumentList (($sess.Cookies.GetCookies('http://127.0.0.1:8000') | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join '; ')
} | Receive-Job -Wait | Out-Null

$get = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/cart' -WebSession $sess -UseBasicParsing
$data = ($get.Content | ConvertFrom-Json).data
$item = $data | Where-Object { $_.product_id -eq 1 } | Select-Object -First 1
if ($item -and $item.quantity -ge 1 -and ($data | Where-Object { $_.product_id -eq 1 }).Count -eq 1) {
  Pass 'concurrent cart write 중복 row 폭증 없음'
} else {
  Fail 'concurrent cart write 불일치'
}
```

#### Soft-deleted user blocked

(위 Profile 섹션 스크립트를 그대로 P0 장애 테스트로 재사용)

#### crawler rate-limited

실제 외부 사이트 rate limit은 CI에서 안정적으로 재현하기 어렵다. 따라서 두 단계로 나눈다.
- P1 nightly: 실제 crawler 대상에서 반복 호출 후 `429/차단 페이지` 감지, 로그/failed 상태 확인
- P2 release: 외부 mock gateway 또는 사내 proxy로 429를 주입해 backoff, audit log, DLQ 생성 확인

---

## 7. 데이터 품질 테스트 (F. 데이터 품질 테스트)

### 7.1 품질 규칙

1. 카테고리 `etc/unknown/null` 비율이 일정 임계값 이상이면 실패
2. 주요 상품은 비교 매장이 2개 이상이어야 함
3. 무게가 이름/단위에 있는 상품은 `per_100g` 또는 정규화 가격이 채워져야 함
4. ingestion 승인 후 데이터가 실제 가격 테이블에 있어야 함
5. dead letter에 오래 쌓인 파일이 있으면 실패

### 7.2 품질 검증 스크립트

#### 카테고리 품질

```powershell
$code = @'
from pathlib import Path
import sqlite3
root = Path(r"E:\pdf\capston01\walletSavior")
db = root / "packages" / "db-admin" / "backend" / "walletguardian.db"
conn = sqlite3.connect(db)
cur = conn.cursor()
total = cur.execute("select count(*) from products where is_active=1").fetchone()[0]
bad = cur.execute("select count(*) from products where is_active=1 and (category_id is null or lower(category_id) in ('etc','unknown'))").fetchone()[0]
print(f'{total}:{bad}')
'@
$result = py -c $code
$parts = $result.Trim().Split(':')
$total = [int]$parts[0]; $bad = [int]$parts[1]
if ($total -eq 0) { Write-Host '❌ FAIL: active product 없음'; exit 1 }
$ratio = [math]::Round(($bad / $total) * 100, 2)
if ($ratio -le 20) { Write-Host "✅ PASS: bad category ratio ${ratio}%" } else { Write-Host "❌ FAIL: bad category ratio ${ratio}%"; exit 1 }
```

#### 가격 비교 다중 매장

```powershell
$search = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/products/search?q=QA%20파이프라인%20양파' -UseBasicParsing
$productId = (($search.Content | ConvertFrom-Json).data | Select-Object -First 1).id
$compare = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/products/$productId/price-compare" -UseBasicParsing
$data = ($compare.Content | ConvertFrom-Json).data
$count = 0
if ($data.other_stores) { $count = $data.other_stores.Count }
elseif ($data.stores) { $count = $data.stores.Count }
if ($count -ge 1) { Write-Host "✅ PASS: multi-store compare count=$count" } else { Write-Host '❌ FAIL: multi-store compare 없음'; exit 1 }
```

#### per_100g 정규화 확인

```powershell
$resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/products/category/food.meat/compare' -UseBasicParsing
$json = ($resp.Content | ConvertFrom-Json).data
$products = $json.products
$bad = @($products | Where-Object { $_.name -match '100g|kg|g|ml|L' -and -not $_.normalized.per_100g })
if ($bad.Count -eq 0) { Write-Host '✅ PASS: per_100g populated' } else { Write-Host "❌ FAIL: per_100g 누락 $($bad.Count)건"; exit 1 }
```

#### dead letter 적체 확인

```powershell
$dlq = 'E:\pdf\capston01\walletSavior\packages\crawler-admin\backend\data\dead_letter'
if (-not (Test-Path $dlq)) { Write-Host '✅ PASS: DLQ 디렉터리 없음'; exit 0 }
$files = Get-ChildItem $dlq -Filter '*.jsonl' -ErrorAction SilentlyContinue
if ($files.Count -eq 0) { Write-Host '✅ PASS: DLQ 적체 없음' } else { Write-Host "❌ FAIL: DLQ 적체 $($files.Count)개"; $files | Select-Object Name,Length,LastWriteTime; exit 1 }
```

---

## 8. 테스트 실행 스크립트 (G. 테스트 실행 스크립트)

### 8.1 권장 실행 순서

1. 환경 변수 설정
2. 서버 6개 시작
3. DB reset + seed
4. P0 smoke
5. synthetic full pipeline
6. frontend-backend contract
7. failure scenarios
8. data quality
9. nightly live crawl

### 8.2 카테고리별 실행 묶음

#### P0 Smoke 묶음
- 서버 기동 확인
- db-admin login
- crawler-admin auth 401/200
- website auth login
- cart add/fetch
- wishlist add/fetch
- profile get/put/delete
- search autocomplete shape
- community product_id save
- synthetic full pipeline

#### Nightly 묶음
- live crawler run
- crawler SSE
- local SSE
- DB-admin down/circuit breaker
- concurrent cart writes
- dead letter replay 확인
- data quality 전체

---

## 9. 마스터 체크리스트 (H. 테스트 체크리스트)

### P0 — 서비스가 사실상 깨지는 회귀

1. website backend `/api/health` 200
2. crawler-admin backend `/health` 200
3. db-admin backend `/health` 200
4. website frontend 5173 응답
5. crawler-admin frontend 5174 응답
6. db-admin frontend 5175 응답
7. db-admin 기본 관리자 로그인 성공
8. crawler-admin 일반 API 무인증 401
9. crawler-admin `X-API-Key` 인증 200
10. crawler-admin SSE 연결 가능
11. db-admin `/api/ingestions` 무인증 401
12. db-admin `/api/ingestions` 인증 200
13. ingestion 상세 조회 가능
14. crawler-review 승인 가능
15. db-review 승인 가능
16. 승인 후 DB `products` row 생성
17. 승인 후 DB `discount_history`/`baseline_prices`/`hotdeal_prices` row 생성
18. website `/api/products/search`에서 승인 데이터 검색 가능
19. website `/api/products/{id}/price-compare` 200
20. price-compare에 multi-store 데이터 존재
21. ProductDetailModal이 기대하는 `other_stores/stores` shape 존재
22. `/api/cart` 무인증 401
23. `/api/cart` 인증 add 200
24. `/api/cart` fetch 결과에 방금 추가한 item 존재
25. cart item 필드(`product_id,item_name,item_price,quantity`) 일치
26. `/api/cart/merge` 동작
27. `appStore.shoppingList` ↔ `cartStore.items` 동기화 검증 필요
28. `/api/wishlist` 무인증 401
29. `/api/wishlist` add 200
30. `/api/wishlist` fetch에 `price_at_add,current_price,target_price` 존재
31. `/api/profile` GET 200
32. `/api/profile` PUT 200
33. `/api/profile` DELETE soft-delete 200
34. soft-deleted user 재로그인 403
35. `/api/activity/track` valid payload 200
36. `/api/activity/track` 5초 내 재호출 시 rate_limited
37. `/api/search/autocomplete` structured response 유지
38. Search submit(`/api/search?q=...`) 결과 존재
39. Community post create 200
40. Community post 작성 시 `posts.product_id` 실제 저장
41. Community comment create 200
42. Community vote 200
43. Home dashboard aggregate(`/api/dashboard`) shape 유지
44. Auth refresh 경로 존재 및 동작
45. 401 후 refresh 실패 시 로그인 유도 동작 확인

### P1 — 기능은 살지만 사용자 기능이 망가지는 회귀

46. Hotdeal 목록/상세/sources API 계약
47. Hotdeal 댓글 목록/작성/삭제 계약
48. Mart promotions/flyers 매장별 계약
49. PricePage 상품 상세/chart shape
50. CategoryCompare summary/products/alternatives/pagination shape
51. CategoryCompare `per_100g` 계산 유지
52. Local geocode 성공/실패 처리
53. Local naver-search 결과 shape
54. Local subcategory-search 결과 shape
55. Local area-explore-stream chunk/종료 shape
56. crawler-admin proxy ingestion list/detail/review 계약
57. pipeline token refresh 후 재시도 동작
58. bulk price 업로드 권한(role) 확인
59. concurrent cart writes 시 중복 row 폭증 없음
60. wishlist target_price 수정 반영
61. profile activity pagination meta 일치
62. AuthCallback에서 `/api/auth/me` 성공 시 로그인 완료
63. LoginModal register/login/logout 경로 계약
64. Search Enter key, recent search, autocomplete click 동작
65. Home fallback: dashboard 실패 시 섹션별 graceful degradation
66. Website health에서 DB circuit 상태 노출
67. db-admin ingestion cleanup 동작
68. DLQ replay 후 정상 적재 가능

### P2 — 엣지/품질/운영 이슈

69. 카테고리 `etc/unknown/null` 비율 임계치 이하
70. 주요 상품 비교 매장 2개 이상 비율 측정
71. 이름/단위에 중량이 있는 상품의 `per_100g` 누락률 측정
72. ingestion quality_score 분포 확인
73. pending ingestion 장기 적체 없음
74. dead letter 장기 적체 없음
75. live crawler rate-limit/backoff 로그 확인
76. DB-admin 다운 시 website degraded + 복구 후 정상 전환
77. auth token expiry/relogin loop 없음
78. soft-delete 후 기존 쿠키 접근 403/401
79. API 응답 시간 P95 목표 이탈 감지
80. SSE 장시간 연결(60초+) 끊김/재연결 동작
81. 대량 search/autocomplete에서도 shape 유지
82. 데이터 승인 후 검색 인덱싱/캐시 반영 지연 측정

---

## 10. 운영 권장안

- **PR 필수**: P0 전부
- **nightly**: P1 전부 + live crawl 1회 이상
- **release 전**: P2 + 수동 브라우저 점검
- 실패 시 원칙:
  - HTTP만 보지 말고 DB까지 확인
  - DB만 보지 말고 website 응답 shape까지 확인
  - API만 보지 말고 프론트가 실제 기대하는 field 이름까지 확인

---

## 11. 이 전략의 한계와 자기 비판

### 11.1 내가 놓쳤을 수 있는 것

1. **실제 브라우저 렌더링 문제**
   - 이 문서는 터미널 중심이라 CSS, hydration, focus trap, modal z-index, 모바일 레이아웃은 충분히 못 본다.
2. **httpOnly cookie + 프론트 interceptor의 진짜 동작**
   - 터미널에서는 `/api/auth/refresh`를 직접 호출할 수 있지만, 실제 브라우저에서 401 응답 후 자동 refresh/retry가 완전히 같은 방식으로 재현되지는 않는다.
3. **Vite dev server와 실제 production build 차이**
   - 본 전략은 개발 서버 기준이다. production build 번들 이슈는 별도 확인이 필요하다.
4. **외부 크롤링 사이트의 변동성**
   - 실제 live crawl은 사이트 구조 변경, Cloudflare, rate limit에 의해 flaky할 수 있다.
5. **로컬스토리지 진짜 동작**
   - cart dual-system 문제는 API/스토어 계약으로 상당 부분 잡을 수 있지만, 브라우저 탭 간 localStorage 이벤트까지는 터미널에서 직접 검증하기 어렵다.

### 11.2 터미널만으로 테스트하기 어려운 것

1. SearchAutocomplete의 키보드 UX 전체(화살표 이동, 포커스 유지)
2. LoginModal/Guarded route의 실제 모달 표시/닫힘
3. ProductDetailModal 열림/닫힘, body scroll lock
4. Header badge, profile dropdown, toast 렌더링
5. crawler-admin/frontend와 db-admin/frontend의 실제 화면 데이터 바인딩
6. SSE가 UI state에 반영되는 시각적 변화
7. 브라우저 쿠키/redirect 기반 OAuth callback 완전 흐름

### 11.3 반드시 수동 브라우저 테스트가 필요한 것

1. **장바구니/찜/프로필 실제 UI 플로우**
   - 로그인 전 → 로그인 후 → 새로고침 → 로그아웃까지
2. **Community 상품 연결 UX**
   - ProductPicker로 선택한 상품이 작성 폼에 보이고, 작성 후 상세에서 연결 정보가 노출되는지
3. **Search Enter / Arrow / Click UX**
   - 자동완성 dropdown에서 키보드 조작이 자연스러운지
4. **Local SSE 화면 업데이트**
   - chunk가 순차적으로 누적되고, 종료/에러 문구가 사용자에게 이해되게 보이는지
5. **crawler-admin 실시간 상태 UI**
   - EventSource reconnect, 완료/실패 뱃지, 로그 영역 업데이트
6. **Auth 401 → refresh → retry**
   - 실제 브라우저 탭에서 세션 만료 후 사용자에게 어떻게 보이는지

### 11.4 가장 중요한 비판

이 전략이 아무리 길어도, **CI에서 실제로 P0를 매 PR마다 돌리지 않으면 다시 useless test가 된다.**
핵심은 문서가 아니라 실행 순서다.

- PR: synthetic full pipeline + cart/wishlist/profile/community/search contract
- nightly: live crawl + SSE + 장애 테스트
- release: manual browser verification

이 세 층이 동시에 있어야만 `"테스트는 통과했는데 런타임은 망가짐"`을 끝낼 수 있다.
