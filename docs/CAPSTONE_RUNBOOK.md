# WalletSaver 정출 실행 안내

이 문서는 실제 수집 데이터와 승인된 공개 snapshot을 사용하는 정출 운영 절차다. 합성 데이터는 parser/matching 회귀 테스트 fixture에만 사용하며 공개 DB에 넣지 않는다.

## 1. Windows 로컬 전체 실행

필수 도구는 Python 3, Node.js/npm이다. 저장 DB와 공개 snapshot은 저장소 밖의 생성 영역인 `.walletsavior/`에 만들어진다.

```powershell
.\start-all.bat
```

기본 실행 주소:

- 공개 웹/API: `http://localhost:5173`, `http://localhost:8000`
- 크롤러 관리자/API: `http://localhost:5174`, `http://localhost:8001`
- DB 관리자/API: `http://localhost:5175`, `http://localhost:8002`

필요한 포트가 이미 사용 중이면 실행은 해당 PID를 표시하고 안전하게 중단한다. 기존 프로세스를 의도적으로 종료해도 되는 경우에만 다음처럼 실행한다.

```powershell
.\start-all.bat -ForcePorts
```

공개 catalog가 아직 승인되지 않은 새 환경에서는 API 프로세스 자체는 기동하지만 상품 API는 snapshot 미설정 오류를 반환한다. 샘플 상품을 대신 노출하지 않는다.

## 2. 수집·분류·승인 순서

1. 크롤러 관리자에서 이마트·홈플러스·롯데마트·코스트코를 각각 실행한다.
2. 실행별 0건 여부, 필수 필드, URL·이미지 존재율, 잘못된 행과 중복률을 확인하고 crawler 승인한다.
3. raw batch를 export하고 `walletsaver-raw-batch-v3` bundle과 원본 증거를 별도 작업 디렉터리에서 분류한다.
4. DB 관리자의 catalog bundle preview와 CSV/HTML 검수 보고서를 확인한다.
5. 미분류·저신뢰·충돌 행을 처리한 뒤 apply한다. 동일 bundle 재적용은 상태를 바꾸지 않는다.
6. 공개 snapshot을 명시적으로 승인한다.

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8002/api/catalog-bundles/snapshot/publish
```

승인본과 rollback 가능 여부는 다음으로 확인한다.

```powershell
Invoke-RestMethod `
  -Uri http://127.0.0.1:8002/api/catalog-bundles/snapshot/status
```

직전 승인본으로 즉시 되돌리기:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8002/api/catalog-bundles/snapshot/rollback
```

공개 교체 전에는 SQLite `quick_check`, 필수 테이블, snapshot 메타데이터, 활성 상품의 통합 리프 카테고리 귀속을 다시 검증한다. 현재 승인본은 `.walletsavior/public_snapshot.sqlite`, 직전 승인본은 `.walletsavior/public_snapshot.sqlite.previous`다.

## 3. Docker 공개 웹/API

Docker 환경은 로컬 관리자 DB에 의존하지 않는다. 공개 read-only snapshot 세 개와 서버 소유 쓰기 DB 세 개를 `/data` 영속 볼륨에 분리한다.

```powershell
Copy-Item .env.docker.example .env.docker
# .env.docker의 JWT_SECRET_KEY와 WALLETSAVIOR_REMOTE_ADMIN_TOKEN을 서로 다른 긴 난수로 교체
docker compose --env-file .env.docker up -d --build
```

새 볼륨에는 catalog가 없으므로 컨테이너는 기동되지만 샘플 데이터를 만들지 않는다. 승인된 snapshot을 인증된 관리 API로 올린다.

```powershell
$token = (Get-Content .env.docker | Where-Object { $_ -like 'WALLETSAVIOR_REMOTE_ADMIN_TOKEN=*' }).Split('=', 2)[1]
$headers = @{ 'X-WalletSavior-Admin-Token' = $token }

Invoke-WebRequest -Method Put -Headers $headers -ContentType 'application/octet-stream' `
  -InFile .walletsavior\public_snapshot.sqlite `
  -Uri http://localhost:8080/api/admin/remote/snapshots/catalog

Invoke-WebRequest -Method Put -Headers $headers -ContentType 'application/octet-stream' `
  -InFile .walletsavior\external_hotdeals.sqlite `
  -Uri http://localhost:8080/api/admin/remote/snapshots/external-hotdeals

Invoke-WebRequest -Method Put -Headers $headers -ContentType 'application/octet-stream' `
  -InFile .walletsavior\opinet.db `
  -Uri http://localhost:8080/api/admin/remote/snapshots/opinet
```

업로드는 최대 크기, SQLite 헤더, `quick_check`, 종류별 필수 테이블을 확인한 뒤 원자적으로 교체한다. 계정·찜·알림은 `accounts.sqlite`와 `interactions.sqlite`, 커뮤니티는 `board.sqlite`에 남아 snapshot 교체의 영향을 받지 않는다.

상태 확인:

```powershell
Invoke-RestMethod http://localhost:8080/api/health
docker compose --env-file .env.docker ps
```

## 4. 로그인과 지역 데이터

Google 로그인은 `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_BASE`가 모두 설정돼야 한다. 누락 시 가짜 로그인을 만들지 않고 설정 오류를 표시한다.

오피넷은 발급 키가 있으면 공식 API를 사용한다. 키가 없을 때 공개 지역 페이지를 한 번 읽는 수동 fallback은 명시적으로만 켠다.

```powershell
$env:OPINET_PUBLIC_FALLBACK_ENABLED = 'true'
```

fallback은 공개 HTML만 저빈도로 요청하고 6시간 캐시를 사용한다. 로그인, CAPTCHA, WAF 우회는 하지 않는다. 가격 화면에는 출처와 관측 시각을 표시한다.

네이버 장소 공개 페이지 기반 브라우저 검색은 기본 비활성이다. 설정이 없으면 화면은 즉시 사용 불가 상태와 외부 네이버 지도 링크를 표시한다. 로컬 수동 검증에서만 다음처럼 명시적으로 켠다.

```powershell
$env:NAVER_PLACE_BROWSER_SEARCH_ENABLED = 'true'
```

이 fallback은 공개 웹 검색 보조일 뿐 정출 catalog나 OPINET 가격의 원천으로 사용하지 않는다.

## 5. 정출 전 회귀 확인

```powershell
# 각 backend 디렉터리에서
py -3 -m pytest -q

# 각 frontend 디렉터리에서
npm.cmd test -- --run
npm.cmd run build
```

라이브 수집 검사는 네 마트별 요청 수를 작게 제한해 별도로 수행한다. 결정적 parser fixture 회귀와 섞지 않으므로 외부 사이트 장애가 전체 테스트 결과를 가리지 않는다.
