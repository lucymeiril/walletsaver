# WalletSaver 교수·팀 실행 안내

교수·팀 시연의 기본 경로는 **TeamDemo**다. 저장소에 포함된 정제 catalog·관리 DB·오피넷 관측 데이터를 처음 실행할 때 검증·복원하여 사용한다. 개발용 빈 DB와 운영 배포 설정은 아래에서 별도로 설명한다. 원래 사용자 계정·세션·비공개 로그·외부 공급자 자격증명은 배포 데이터에 포함하지 않는다.

## 1. 기본: Windows TeamDemo 전체 실행

Python 3.11 이상과 Node.js/npm이 필요하다. 저장소 루트에서 실행한다.

```powershell
.\start-all.ps1 -TeamDemo
```

이 경로는 `demo.env`의 공개 데모 설정을 읽고 `demo-data`의 압축 DB와 manifest를 검증한 뒤 `.demo-runtime`에 최초 설치한다. 기존 writable 데이터와 사용자가 만든 계정은 재시작 시 유지한다. 다른 catalog를 설치하려고 기존 데이터 디렉터리를 지우지 말고 관리자의 검수·snapshot 갱신 절차를 사용한다.

### 기존 설치 재시작과 명시적 catalog 갱신

위 시작 명령은 **최초 설치 또는 기존 설치 보존**만 수행한다. 새 checkout의 유효한 배포 manifest·source pin이 최초 설치 receipt와 달라도 기존 DB·계정·관리 변경·receipt를 덮어쓰지 않고 차이를 안내한다. 현재 배포 파일의 hash·schema 검증은 계속 엄격하게 수행한다. 이 안내는 기존 설치를 최신 catalog로 교체했다는 뜻이 아니다.

데이터 갱신은 5절의 인증된 catalog bundle **preview → apply → replay**를 먼저 완료한 뒤 다음 명령으로 명시적으로 publish한다. `$adminBase`와 `$adminHeaders`는 5절의 로그인 명령으로 준비한다. 시작 명령·installer를 갱신 명령으로 사용하거나 `.demo-runtime`·Compose volume을 삭제하지 않는다.

```powershell
Invoke-RestMethod -Method Post -Headers $adminHeaders -Uri "$adminBase/api/catalog-bundles/snapshot/publish"
```

브라우저는 launcher의 `FRONTEND_URL`로 열리며 TeamDemo 기본값과 `OAUTH_REDIRECT_BASE`는 모두 `http://127.0.0.1:5173`이다. 직접 설정한 두 base가 다르면 시작을 거절한다. `localhost` 창으로 바꾸어 같은 쿠키·OAuth 세션이라고 가정하지 않는다.

| 역할 | UI | API |
| --- | --- | --- |
| 공개 웹 | `http://127.0.0.1:5173` | `http://127.0.0.1:8000` |
| 크롤러 관리 | `http://127.0.0.1:5174` | `http://127.0.0.1:8001` |
| DB 관리 | `http://127.0.0.1:5175` | `http://127.0.0.1:8002` |

Web만 실행하려면 `-TeamDemo -Web`, 관리 프로그램만 실행하려면 `-TeamDemo -Admin`을 사용한다. `-DemoDataDir`로 독립 데이터 경로를 지정할 수 있다. 포트 충돌은 먼저 해당 프로세스를 확인하고 중단한다. `-ForcePorts`는 기존 프로세스를 종료해도 되는 경우에만 직접 선택한다.

DB 관리자 데모 계정은 `demo-admin@walletsaver.example` / `demo-local-admin-260-known-value`다. 크롤러 관리자 API-key 로그인에는 `walletsaver-public-team-demo-crawler-260-known-value`를 입력한다. Web 사용자 계정은 처음에는 비어 있으므로 로컬 회원가입으로 만든다. 이 값들은 누구나 아는 데모 값이며 실제 운영에는 별도 키·계정이 필요하다.

Windows 전체 실행은 이 Linux 환경에서 검증하지 않았다. Linux에서는 아래 별도 경로로 세 backend·세 UI를 시작하고 관리자 수동 인증 및 읽기 화면을 확인했다. 저장 원문 bundle replay·snapshot 61/62 소비, 기존 matching Import confirm/replay와 아래 실제 사용자·관리 화면은 확인됐다. 최신 4마트 live 갱신과 외부 인증/지도 등은 여전히 미확인으로 구분한다. 아래 Compose는 관리 UI/API를 실행하지 않는다.

## 2. Linux: 공개 소스의 전체 6-process 실행

기존 설치의 검토된 상품군 갱신 예: 이 후보의 `packages/shared/core/reviewed_catalog_groups.json`(492군/1191기존ID)과 `demo-data/manifest.json`의 source pins가 일치하는 코드를 먼저 사용한다. DB 자가 선언만으로 새 그룹을 신뢰하지 않는다. 코드에 없는 그룹·상호 불일치 그룹은 발행/원격 upload 전에 `catalog_group_source_incompatible`로 거절되며 기존 DB는 유지된다. 승인된 과거 member 부분집합은 호환된다. 다음 열 파일은 catalog90→91→92→93→94→95의 기존 상품군 metadata·리프 정정과95→96→97의 근거가 고정된 건전지 규격/행사역할·ID namespace 정정,97→98의 원문에 묶인6분류·3공통리프/키워드 및98→99의7분류·중립 식판 및99→100의27분류·8공통 형태 리프/키워드 구체화를 정식 적용·재적용 검증한 산출물이다. 더 오래되거나 별도로 수정한 DB를 전체 최신본으로 바꾼다고 주장하지 않으며, preview에서 실제 변경을 검토한다. 정상 재기동은 언제나 기존 계정·관리자 변경·이력을 보존한다.

```sh
# 이미 실행 중인 DB 관리자 API에 데모 계정으로 로그인한다.
WS_ADMIN_TOKEN=$(curl -fsS http://127.0.0.1:8002/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo-admin@walletsaver.example","password":"demo-local-admin-260-known-value"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
for WS_BUNDLE in demo-data/updates/catalog90-to91.json demo-data/updates/catalog91-to92.json demo-data/updates/catalog92-to93.json demo-data/updates/catalog93-to94.json demo-data/updates/catalog94-to95.json demo-data/updates/catalog95-to96.json demo-data/updates/catalog96-to97.json demo-data/updates/catalog97-to98.json demo-data/updates/catalog98-to99.json demo-data/updates/catalog99-to100.json demo-data/updates/catalog100-to101.json; do
  curl -fsS -H "Authorization: Bearer $WS_ADMIN_TOKEN" -F "file=@$WS_BUNDLE" http://127.0.0.1:8002/api/catalog-bundles/preview
  # preview의 변경이 의도한 경우에만 apply; 같은 파일 재적용은 idempotent이다.
  curl -fsS -H "Authorization: Bearer $WS_ADMIN_TOKEN" -F "file=@$WS_BUNDLE" http://127.0.0.1:8002/api/catalog-bundles/apply
done
curl -fsS -H "Authorization: Bearer $WS_ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{}' http://127.0.0.1:8002/api/catalog-bundles/snapshot/publish
```

Web 서버가 다른 경로/호스트이면 발행한 상품-only `public_snapshot.sqlite`를 기존 관리자 remote snapshot upload로 전달한다. 같은 source+등록 정의의 실제92 업로드 성공과 원 event/시점/계정 참조 보존을 확인했다. 외부 서비스 배포나 실제 Google 로그인 성공을 뜻하지 않는다.

```sh
# 아래 Linux 실행에서 설정한 실제 WS_DEMO_DIR와 demo.env의 공개 내부 데모 토큰 사용.
curl -fsS -X PUT \
  -H "X-WalletSavior-Admin-Token: $WALLETSAVIOR_REMOTE_ADMIN_TOKEN" \
  -H 'Content-Type: application/octet-stream' --data-binary "@$WS_DEMO_DIR/public_snapshot.sqlite" \
  http://127.0.0.1:28000/api/admin/remote/snapshots/catalog
```

이 환경의 실제 포트는 Web API `28000` / UI `27173`, 크롤러 API `8001` / UI `5174`, DB 관리자 API `8002` / UI `5175`였다. 아래는 같은 공개 소스·설치 helper·저장소 내부의 독립 `.demo-runtime`을 사용하는 명령이다. 검증 환경에서 재사용한 다른 checkout의 venv·비공개 디렉터리가 필요하지 않다. Python 3.11 이상과 Vite 8을 지원하는 Node.js(20.19 이상 또는 22.12 이상)가 필요하다.

저장소 루트에서 최초 의존성과 데이터를 준비한다. 기존 `.demo-runtime` 데이터는 지우지 않는다.

```sh
export WS_ROOT="$PWD"
export WS_DEMO_DIR="$WS_ROOT/.demo-runtime"
python3 -m venv .venv
export WS_PY="$WS_ROOT/.venv/bin/python"
"$WS_PY" -m pip install -r packages/web-api/backend/requirements.txt -r packages/db-admin/backend/requirements.txt -r packages/crawler-admin/requirements.txt
"$WS_PY" -m playwright install chromium
for ws_frontend in packages/web-frontend packages/crawler-admin/frontend packages/db-admin/frontend; do
  (cd "$ws_frontend" && npm ci) || exit 1
done
set -a
. ./demo.env
set +a
"$WS_PY" tools/install_demo_catalog.py --source demo-data --target "$WS_DEMO_DIR"
```

`pip install`은 Playwright Python 모듈만 설치하며 브라우저 실행 파일을 설치하지 않는다. Windows launcher는 Chromium 설치를 수행하지만 Linux에서는 위 명령을 별도로 실행해야 한다. 새 Debian/Ubuntu 호스트에 브라우저 시스템 라이브러리도 없다면 위 `install chromium` 대신 `"$WS_PY" -m playwright install --with-deps chromium`을 사용한다(시스템 패키지 설치 권한 필요). API를 실행하는 동일 사용자·venv에서 설치하여 그 사용자의 Playwright browser cache를 사용한다. 이 새 호스트 설치 명령은 이번 문서 수정에서 실행하지 않았다.

Web의 Naver 공개 장소 검색은 `playwright.chromium.launch(headless=True)`를 사용하므로 이 Chromium이 필요하고 Xvfb는 필요하지 않다. `CRAWLER_BROWSER_EXECUTABLE_PATH`는 크롤러 helper의 설정이며 Web Naver 검색 브라우저를 바꾸지 않는다. 설치와 사용자 opt-in은 서로 다른 단계다. 기존 실제 opt-in 한 번에서 5개 장소가 반환된 증거는 유지하며, 브라우저 미설치·응답 미확인은 검색 0건이나 Naver OAuth 실패로 표시하지 않는다.

이후 같은 shell에서 명시적인 저장 경로·내부 서비스 주소를 설정한다. `BACKUP_DIR`와 `WALLETSAVIOR_ORCHESTRATOR_DB`도 데모 경로에 묶어 다른 설치의 관리 저장소를 사용하지 않는다.

```sh
export PYTHONPATH="$WS_ROOT/packages/shared${PYTHONPATH:+:$PYTHONPATH}"
export DATABASE_URL="sqlite:///$WS_DEMO_DIR/admin.sqlite"
export DB_ADMIN_DATABASE_URL="$DATABASE_URL"
export WALLETSAVIOR_PUBLIC_DB="$WS_DEMO_DIR/public_snapshot.sqlite"
export WALLETSAVIOR_ACCOUNT_DB="$WS_DEMO_DIR/accounts.sqlite"
export WALLETSAVIOR_INTERACTION_DB="$WS_DEMO_DIR/interactions.sqlite"
export WALLETSAVIOR_BOARD_DB="$WS_DEMO_DIR/board.sqlite"
export WALLETSAVIOR_EXTERNAL_HOTDEAL_DB="$WS_DEMO_DIR/external_hotdeals.sqlite"
export WALLETSAVIOR_WEEKLY_STATE_DB="$WS_DEMO_DIR/weekly_state.sqlite"
export OPINET_DB_PATH="$WS_DEMO_DIR/opinet.sqlite"
export WALLETSAVIOR_ORCHESTRATOR_DB="$WS_DEMO_DIR/orchestrator.sqlite"
export BACKUP_DIR="$WS_DEMO_DIR/backups"
export DB_ADMIN_URL="http://127.0.0.1:8002"
export DB_ADMIN_API_URL="$DB_ADMIN_URL/api/prices/bulk"
export INGESTION_API_URL="$DB_ADMIN_URL/api/ingestions"
export WALLETSAVIOR_REMOTE_ADMIN_URL="http://127.0.0.1:28000"
export WALLETSAVIOR_REMOTE_SNAPSHOT_UPLOAD=false
export WALLETSAVIOR_AUTO_SNAPSHOT_PUBLISHER=false
export WALLETSAVIOR_CORS_ORIGINS="http://127.0.0.1:27173"
export FRONTEND_URL="http://127.0.0.1:27173"
export OAUTH_REDIRECT_BASE="$FRONTEND_URL"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:5175"
export CORS_ORIGINS="http://127.0.0.1:5174"
(cd packages/db-admin/backend && "$WS_PY" -m alembic upgrade head)
```

명시된 포트가 비어 있는지 확인한 후 여섯 프로세스를 시작한다. 각 UI는 기존 proxy 설정으로 대응하는 API에 연결되며 Web만 `VITE_API_PROXY_TARGET`을 지정한다.

```sh
(cd packages/web-api/backend && exec "$WS_PY" -m uvicorn main:app --host 127.0.0.1 --port 28000 --no-access-log) > "$WS_DEMO_DIR/web-api.log" 2>&1 &
(cd packages/crawler-admin/backend && exec "$WS_PY" -m uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8001 --no-access-log) > "$WS_DEMO_DIR/crawler-api.log" 2>&1 &
(cd packages/db-admin/backend && exec "$WS_PY" -m uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8002 --no-access-log) > "$WS_DEMO_DIR/db-api.log" 2>&1 &
(cd packages/web-frontend && VITE_API_PROXY_TARGET=http://127.0.0.1:28000 exec npm run dev -- --host 127.0.0.1 --port 27173 --strictPort) > "$WS_DEMO_DIR/web-ui.log" 2>&1 &
(cd packages/crawler-admin/frontend && exec npm run dev -- --host 127.0.0.1 --port 5174 --strictPort) > "$WS_DEMO_DIR/crawler-ui.log" 2>&1 &
(cd packages/db-admin/frontend && exec npm run dev -- --host 127.0.0.1 --port 5175 --strictPort) > "$WS_DEMO_DIR/db-ui.log" 2>&1 &
```

이마트 일반 화면 모드 수집은 `chrome` 채널의 안정판 Google Chrome을 사용한다. 위 Chromium 설치만으로 이 채널이 설치되지는 않는다. Chrome이 없는 지원 Linux 호스트에서는 다음 설치 명령을 사용하거나 공식 안정판 Chrome을 설치한다. `DISPLAY`도 없는 Debian/Ubuntu에서는 Xvfb가 필요하다(시스템 설치 권한 필요). 이미 준비된 호스트에서는 이 설치를 반복하지 않는다.

```sh
"$WS_PY" -m playwright install chrome
sudo apt-get update
sudo apt-get install -y xvfb
```

실제 설치한 안정판 Chrome의 실행 경로를 지정할 수도 있다. 아래 값은 예시 자리이며 자신의 설치 경로로 바꾼다. Chrome 채널의 기본 설치를 사용하면 경로 export는 생략한다. `DISPLAY`가 없는 Linux에서는 크롤러 API를 이미 실행한 뒤 중복으로 실행하지 말고, 위 크롤러 시작 명령을 `xvfb-run -a`로 감싸 화면 모드를 제공한다.

```sh
export CRAWLER_BROWSER_EXECUTABLE_PATH="/absolute/path/to/installed/google-chrome"
# DISPLAY가 없을 때 위 crawler-api 시작 명령 대신 사용
(cd packages/crawler-admin/backend && exec xvfb-run -a "$WS_PY" -m uvicorn api.app:create_app --factory --host 127.0.0.1 --port 8001 --no-access-log) > "$WS_DEMO_DIR/crawler-api.log" 2>&1 &
```

공용 크롤러 helper는 명시된 실행 경로가 있으면 Chrome 채널 대신 그 경로를 사용하고, 기존 `HTTP_PROXY`/`HTTPS_PROXY`·`NO_PROXY`를 따른다. 의존성 다운로드와 실제 브라우저 접속은 별개이므로 pip 설치 성공만으로 브라우저 proxy/TLS 접속까지 확인됐다고 보지 않는다. 다운로드 도구·OS·브라우저의 정상 CA 신뢰와 세션 proxy 설정을 유지하며 TLS 검증을 끄지 않는다. 현재 호스트에서 이 선행 조건이 확인된 사실은 중지된 이마트 공급자 요청을 재개해도 된다는 뜻이 아니다.

Web readiness는 `http://127.0.0.1:28000/api/health`, 관리 API health는 각각 `http://127.0.0.1:8001/health`, `http://127.0.0.1:8002/health`에서 확인한다. UI는 각각 `27173`, `5174`, `5175`를 연다. 실제 공개 소스 실행에서 관리자 수동 인증 2건과 읽기 화면 6건, 저장된 Costco 관측 1 HIT의 raw export와 동일 intake 재실행 보존이 확인됐다. 이전 249 검수 bundle의 preview·apply·replay에서 catalog graph와 사용자 참조가 유지됐고 snapshot 61 소비가 확인됐다. 현재 배포 압축 데이터와 별도 시험 탑재본은 revision92(전체9115/공개8803/pending312)이다. 같은 공개 소스에서 실제 장바구니·찜·알림 저장/재접속, 커뮤니티 CRUD·로그아웃, 지역 주유소 7개 선택과 알려진 matching UI confirm/replay가 확인됐다. 통합 leaf의 실제 키워드805 조회, 정규화 matching6371개 중 기존 Costco80 규격 확인, 관리 대시보드의 총6308/활성6152 상품·9112 보존 관측·1383 분류·1210 키워드 표시가 확인됐다. 미산출 품질 점수는 미확인으로 표시한다. 공식 키워드 활성 변경→목록/자동완성 제외→원값 복원→재등장을 확인했으며 graph/원 키워드는 동일하다. 이전 trial snapshot62와 복원 뒤 data_revision64(dirty)는 과거 검증 기록이며 현재 revision92 상태가 아니다. 이미 확인한 publish를 반복하지 않는다.

## 3. Docker Compose: 공개 Web/API만 실행

```sh
docker compose --env-file demo.env -f docker-compose.yml -f docker-compose.demo.yml up --build
```

`http://localhost:8080`을 연다. `catalog-init`이 배포 데이터를 별도의 `walletsaver-demo-data` 영속 볼륨에 설치한 뒤 API가 시작한다. 계정·게시판·상호작용 저장소는 별도로 초기화되며 원래 계정 데이터는 복사하지 않는다. 관리 프로그램은 이 Compose에 포함되지 않는다.

현재 환경에서는 빈 볼륨 최초 설치, 실제 상품·이력 조회, 동일 볼륨의 새 API 컨테이너에서 데이터·합성 계정 유지가 확인됐다. Windows, 다른 새 클라우드 호스트, 외부 공개 배포의 실행 검증은 별개다. 이미 설치한 데모를 다시 켤 때 `down -v`로 볼륨을 지우지 않는다.

## 4. 네 판매처의 실제 증거 범위

아래는 2026-10-05에 저장한 제한된 재수집과 정식 갱신 결과다. 현재의 실시간 결제 가격이나 전체 카테고리 수집 성공을 뜻하지 않는다. 과거 catalog가 포함돼 있다는 사실과 새 라이브 재수집의 성공도 구분한다.

| 판매처·대상 native | 실제 원문 캡처 | 상품 identity | 검수·export | 이력·공개 snapshot | 남은 조건 |
| --- | --- | --- | --- | --- | --- |
| 홈플러스 `059102628` | 실제 2L×6 원문, 관측 금액 2,190 | hit | 3건 export 중 1건, 정식 검수 완료 | 동일 event로 append·재실행 보존, revision 60 | 구매 최소 1·최대 2와 쿠폰 조건은 별도 원문이다. 관측 금액의 통화 필드·실제 쿠폰 적용·결제가는 미확인 |
| 롯데마트 `0000049320367` | 실제 140ml 원문, 3,900 KRW, “3개씩 골라 담으면, 그 중 1개는 무료” | hit | 3건 export 중 1건, 정식 검수 완료 | 동일 event로 append·재실행 보존, revision 60 | 선택 장바구니·무료 상품 가치·자격·실제 결제가는 미확인 |
| 코스트코 `649298` | 실제 80개입 원문, 40,990 KRW | hit | 3건 export 중 1건, 정식 검수 완료 | 동일 event로 append·재실행 보존, revision 60 | 회원 자격 및 일부 최대 주문 mode·기간 flag 값이 캡처에서 누락돼 미확인. 최소 1·최대 500은 구매 조건이며 내용물 수량이 아님 |
| 이마트 | 이 검증 구간의 새 캡처 없음: 기존 429 중지 유지 | 새 행 미검증 | 새 행 없음 | 기존 이마트 이력은 보존; 새 갱신 미검증 | 허용되는 다음 공급자 구간과 보이는 안정판 Chrome·6–7분(360–420초) 제한 필요. 현재 호스트의 공식 안정판 Chrome·화면 모드 Xvfb·proxy/TLS 선행 조건은 설치·확인됨. 공급자 새 요청은 0건이므로 라이브 성공 아님. 전략은 일반 Playwright이며 headless Chromium으로 대신하지 않음 |

세 새 관측은 quoted-price 이력으로 보존한다. 조건이 불명확한 event의 실제 payable·단위 비교 가격은 NULL로 유지한다. 0건 수집, SDK 문자열이 있는 HTTP 200, 상품 정보가 없는 shell을 성공 또는 WAF로 판정하지 않는다. 실제 403·429·로그인·CAPTCHA·challenge가 있으면 해당 공급자 요청을 중단하며 우회하지 않는다.

일반 롯데·이마트 수집도 상품 원문과 실제 응답 URL·body SHA·시간을 보존한다. HTML 카드만 있으면 전체 상품 JSON이 없다는 상태를 함께 남긴다. 저장 원문을 다시 파싱한 시각이나 관리자 접수 시각을 새 가격 관측 시각으로 사용하지 않는다. 원 관측 시각이 없는 자료는 매칭·검토할 수 있지만 가격이력 발행은 보류한다. 이 경계의 로컬 검증은 새 공급자 접근 성공이나 현재 결제가를 뜻하지 않는다.

정규화 Products/Prices 기본 탭은 상품·규격·판매처 ID와 날짜·출처별 전체 저장 관측을 읽기 전용으로 보여 준다. 별도 legacy 탭의 기존 편집 계약과 구분하며 이 화면만으로 정식 갱신 전체 완료를 주장하지 않는다. 원 관측 표시가, 행사 조건, 현재 결제 미확인을 분리하고 원문 행사기간의 시간대/경계가 없으면 날짜 문자열만 표시한다.

현재 동봉 데이터와 시험 탑재본은 revision67: 전체9114/공개8802/pending312이며 원래9112 이력·상품·매핑·계정 참조가 보존됐다. 10월6일 Costco/Lotte 새 실제 관측2건은 정식 intake→2단계 승인→원캡처 SHA·시각·URL/SKU/규격 결합 검토→동일 재적용→snapshot67을 통과했다. 회원·선택구성·실제 결제 미확인은 유지한다. 같은 날 Homeplus 정상 응답의 opt/prop을 저장하지 못한 내부 캡처 누락으로 새 행은 없다; 중지 공급자를 재요청하거나 누락을 no-option으로 추정하지 않는다. 보호 원 실행본 revision60·초기인증9098/98은 별개이며 잔여98은 보류다.

## 5. 갱신 경로: 수집에서 승인 snapshot까지

1. 허용되는 판매처·원본 범위만 저빈도로 실행하고 수집 0건·필수 필드·URL·native/spec·잘못된 행을 확인한다. 이마트는 위 Chrome·시간 제한을 따른다. 현재 중지된 공급자에 재시도하지 않는다.
2. 크롤러 결과를 검수한 뒤 raw batch를 export한다. 금액은 offer 관측값이며 상품 identity에 사용하지 않는다.
3. `walletsaver-raw-batch-v3` 원본과 matching 문맥을 유지해 분류·검토한다. 누락·충돌·미분류를 임의 기본값으로 채우지 않는다.
4. DB 관리자의 catalog bundle preview와 검수 보고서를 확인한 뒤 인증된 관리자 흐름으로 apply한다. 같은 bundle을 다시 적용해 별도 event를 만들지 않는다.
5. snapshot 검증 후 인증된 관리자 흐름으로 명시적으로 publish한다. 상태와 직전 승인본 rollback 가능 여부를 확인한다.

분류 결과 JSONL의 **matching-only import**는 기존 public mapping의 검수 정보 경로다. legacy 분류 행은 기존 `category_id` 검증을 유지한다. normalized 행은 기존 key와 실제 알려진 active product·unified leaf 계층·해당 product의 variant·명칭·수량이 일치할 때만 server가 참조를 검증하고 legacy category NULL을 허용한다. 임의 public ID·다른 variant·다른 수량이나 추정 legacy category를 입력하지 않는다. 현재 저장된 Costco mapping 한 건의 UI preview·confirm은 HTTP 200·변경없음 1건(신규/수정 0건)이 확인됐고, 같은 trace 재확인은 idempotent=true였다. 기존 graph·키워드·계정 참조는 보존됐다. 이는 새 상품 추가 성공이 아니다.

새 product·variant·normalized key 또는 분류 변경은 기존 원본 검수 **catalog bundle preview → apply → replay → snapshot** 경로로 처리한다. 이전 saved-bundle replay/snapshot 61 증거와 현재 배포·시험 데이터 revision67을 구분한다. 두 경로의 기능을 하나의 import 성공으로 합쳐 표시하지 않는다.

관리 UI의 인증된 실행을 기본으로 사용한다. 직접 API를 사용할 때도 `REQUIRE_AUTH=true`이므로 익명 POST/GET은 401을 반환한다. 다음 PowerShell 예시는 공개 데모 계정으로 로그인한 뒤 같은 설치의 관리자 API에 인증 헤더를 전달한다. JWT를 출력하거나 로그·Git에 저장하지 않는다.

```powershell
$adminBase = 'http://127.0.0.1:8002'
$loginBody = @{ email = 'demo-admin@walletsaver.example'; password = 'demo-local-admin-260-known-value' } | ConvertTo-Json
$adminLogin = Invoke-RestMethod -Method Post -Uri "$adminBase/api/auth/login" -ContentType 'application/json' -Body $loginBody
$adminHeaders = @{ Authorization = "Bearer $($adminLogin.access_token)" }
Invoke-RestMethod -Method Get -Headers $adminHeaders -Uri "$adminBase/api/catalog-bundles/snapshot/status"
# 검수·apply를 완료하고 publish하려는 경우에만 실행
Invoke-RestMethod -Method Post -Headers $adminHeaders -Uri "$adminBase/api/catalog-bundles/snapshot/publish"
# 직전 승인본으로 되돌리기로 결정한 경우에만 실행
Invoke-RestMethod -Method Post -Headers $adminHeaders -Uri "$adminBase/api/catalog-bundles/snapshot/rollback"
```

TeamDemo writable 위치는 `.demo-runtime`이며 개발 모드 `.walletsavior`와 혼용하지 않는다. 운영 설치에서는 공개 데모 계정 대신 해당 설치의 별도 관리자 인증을 사용한다.

## 6. 개발·운영 모드와 외부 설정

개발자가 배포 catalog 없이 시작할 때만 `start-all.bat` 또는 `start-all.ps1`의 `-TeamDemo` 없는 실행을 사용한다. 이 경로의 `.walletsavior`는 새 환경에서 빈 상태다. 공개 catalog가 아직 없으면 상품 API는 readiness 오류를 반환하며 샘플 상품으로 대체하지 않는다. 교수·팀 데모의 기본 실행으로 사용하지 않는다.

운영 Web/API는 `.env.docker.example`을 비공개 `.env.docker`로 복사하고 JWT·remote-admin 키를 서로 다른 운영용 값으로 설정한 뒤 base Compose를 사용한다. 새 볼륨은 catalog가 없으므로 인증된 `PUT /api/admin/remote/snapshots/catalog`로 승인된 snapshot을 설치한다. external-hotdeals와 opinet도 각각 별도의 승인된 SQLite 업로드 대상이며, 미확인 자료를 넣지 않는다. 계정·찜·알림·게시판 데이터는 catalog 교체와 분리한다.

| 외부 기능 | 필요한 설정·현재 한계 |
| --- | --- |
| Google OAuth | 비공개 `GOOGLE_CLIENT_ID`·`GOOGLE_CLIENT_SECRET` 또는 `GOOGLE_CLIENT_SECRET_FILE`이 가리키는 비공개 JSON의 `web`/`installed` client 설정. `OAUTH_REDIRECT_BASE`, `FRONTEND_URL`과 등록 callback의 일치 필요. 실제 공급자 로그인 미검증 |
| 로그인 범위 | 자체 이메일·비밀번호 회원가입/로그인과 Google만 활성화한다. Naver/Kakao/기타 로그인·가짜 소셜 데모 로그인은 제거했다. 기존 계정/연결 기록은 삭제하지 않는다. |
| Naver 장소 검색·지도 | 지역 화면에서 공개 브라우저 검색을 사용자가 명시적으로 선택한 요청에만 실행. 위 Playwright Chromium·공급자 접근이 필요하며 headless 검색에는 Xvfb가 필요하지 않음. 기존 opt-in 실제 응답의 5개 장소는 확인됐고, 외부 지도 링크 handoff는 별도 경로. 폐지된 Naver 로그인 설정은 이 공개 장소 검색에 필요하지 않음 |
| Opinet 공식 API | 사용자 요청으로 연기했다. `OPINET_API_KEY` 준비나 실제 API는 현재 제출 차단/필수 입력이 아니다. 수동 출처의 7개 주유소·14개 가격은 원래 갱신 날짜의 관측값이며 실시간 가격/좌표·거리 확정이 아님. |
| 연료 지도 좌표 | 공식 API의 `GIS_X_COOR`/`GIS_Y_COOR` KOTI-KATEC 변환과 수동 페이지 callback 위치필드는 구분한다. 수동 위치필드의 CRS는 미입증이므로 원문 XY만 보존하고 좌표는 NULL로 둔다. 배포 7개 좌표도 NULL이며 GPS 거리순 비교를 보장하지 않음. Naver 명칭·주소 연결만으로 x/y의 CRS를 확정하지 않음 |
| 핫딜 | 271 정상 공개 Ruliweb 목록·게시글과 Uniqlo 공식 상품 근거 → 정식 관리자 승인·중복 없는 저장·별도 external snapshot·실제 화면까지 확인했다. 루리웹 6개 원문 KRW 표시가와 유니클로 1개 APP회원 한정 59,900원/취소선79,900원·`2026/10/08 까지`를 제공한다. 결제·선택 사이즈·배송·회원 자격은 미확인, 명시 종료 게시물은 종료로 표시한다. Algumon/Musinsa403 경로는 중단 유지하며 해당 실패로 정상 출처를 비우지 않는다. |
| 이마트 라이브 | Playwright의 `chrome` 채널·화면 모드와 명시적 세션 proxy/CA 연결이 필요. 현재 호스트의 공식 Chrome 154.0.8037.97·Xvfb 화면 모드·로컬 DOM과 별도 공개 의존성의 proxy/TLS 확인은 완료됐다. 이마트 요청은 없었으며 기존 429 중지와 허용된 다음 공급자 구간·6–7분 제한을 지킨다. 로그인·challenge 우회 없음 |

TeamDemo의 외부 값은 기본적으로 공란이다. 현재 시험 Web/API와 crawler API의 Google 이름별 설정 및 Google file locator는 공란으로 확인했다. 이는 다른 경로에 개인 키 파일이 없다는 뜻이 아니며 공급자 로그인 성공을 뜻하지 않는다. 외부 기능을 설정할 때는 `demo.env`를 ignored `.env.demo.local`로 복사하고 그 비공개 파일만 편집한다.

```powershell
.\start-all.ps1 -TeamDemo -DemoEnvFile .env.demo.local
```

Compose에서는 named Google 설정에 `--env-file .env.demo.local`을 사용한다. Google JSON 파일 방식은 host 경로 문자열을 API에 그대로 넘기지 않는다. `.env.demo.local`의 `GOOGLE_CLIENT_SECRET_FILE`을 이미 존재하는 비공개 JSON의 host 절대경로로 설정한 뒤, ignored `.compose.oauth.local.yml`에 다음 read-only 연결을 넣는다. 컨테이너 안에서는 고정된 `/run/secrets/google-oauth.json`을 읽는다. `create_host_path: false`는 파일 경로가 없을 때 빈 디렉터리를 만들지 않게 한다. 외부 JSON·실제 값은 Git/배포 데이터에 포함하지 않는다.

```yaml
services:
  api:
    environment:
      GOOGLE_CLIENT_SECRET_FILE: /run/secrets/google-oauth.json
    volumes:
      - type: bind
        source: ${GOOGLE_CLIENT_SECRET_FILE:?Set an existing private Google JSON absolute path}
        target: /run/secrets/google-oauth.json
        read_only: true
        bind:
          create_host_path: false
```

```sh
docker compose --env-file .env.demo.local -f docker-compose.yml -f docker-compose.demo.yml -f .compose.oauth.local.yml up -d
```

파일은 읽을 수 있는 JSON이며 `web` 또는 `installed` 안에 `client_id`·`client_secret`을 가져야 한다. 일반 TeamDemo/Linux 직접 실행은 같은 변수의 host 파일을 직접 읽으며 Compose override가 필요 없다. 위 설정 전달·read-only 연결은 configuration으로 확인했고 실제 외부 OAuth 로그인은 미검증이다.

TeamDemo Google callback은 `http://127.0.0.1:5173/api/auth/oauth/google/callback`, Compose 기본 callback은 `http://localhost:8080/api/auth/oauth/google/callback`이다. 위 Linux 전체 실행의 callback은 `http://127.0.0.1:27173/api/auth/oauth/google/callback`이다. `localhost`와 `127.0.0.1`은 다른 cookie origin이므로 브라우저·origin·callback을 일치시킨다. 기본 TeamDemo loader가 외부 공란을 읽으므로 미리 설정한 shell 키가 자동으로 유지된다고 가정하지 않는다.

## 7. 검증 상태

이 문서는 저장된 실제 수집·정식 반영 및 현재 환경의 package 증거를 연결한다. 새 라이브 요청이나 전체 test suite를 실행하지 않았다. Linux 전체 6-process 시작, 관리자·읽기 동작, 저장된 공식 갱신 replay와 snapshot 61 소비는 확인됐다. matching-only import는 실제 UI preview/confirm 200·변동 없음 1행과 동일 입력 재적용 200/idempotent=true, 원 event·매칭·저장 참조 해시 보존까지 확인됐다. 동봉 일관된 배포는 revision98(전체9115/공개8803/pending312)이며 최초 설치/재기동 경로는 이전 같은 installer 증거를 재사용한다.269 정상 Homeplus059102628 실제 새 관측2190/2L×6 1건을 정식 intake/export/review/apply·재적용했고 기존9114 event·상품/매핑/계정참조는 보존됐다. 지급가격·통화·쿠폰 적격성은 미확인이며 새 단위가를 만들지 않았다. 일관된 SQLite backup 배포사본에서는 계정·세션·개인 상호작용을 제거하고 catalog/matching/승인·갱신 상태와 snapshot을 유지했다. 이전67은 복구본으로 보존했다. 위 61/62/64는 이전 검증 증거이며, 이 안내 수정은 새 라이브 수집이나 전체 품질 통과를 뜻하지 않는다. Windows·새 관리형 cloud·외부 OAuth·라이브 provider·좌표·OS 공유 동작도 전체 통과로 선언하지 않는다. 초기 미해결 98개 SKU 작업은 일시 중지된 별도 범위다.

The existing Crawler → Data review intake detail renders original nested purchase terms and role-specific interpretation notes. Inspect exact native/product/variant connections; missing listing/event IDs remain unknown, and approved source quotes are not confirmed checkout receipts. Collector provenance retains bounded business fields and actual HTTP receipt metadata without retaining private account/session branches. HTTP401/403/429 stops that supplier run, preserving any earlier rows as partial; do not bypass the stop with another same-host query.

Collector execution separates source completeness, validation, acknowledged pending-review storage, approval and publication. A partial source is processed once and remains partial even when every retained row is stored. A zero or missing diagnostic does not prove a successful collection; fixtures and saved-source replay remain separate from representative live retailer evidence. Naver253 opt-in five-place search/distance display is reusable for the unchanged consumer contract; it does not prove external OAuth, fuel CRS coordinates or Windows/new-cloud execution.

270의 동일 공개 앱에서 공유 URL을 새 익명 브라우저 세션으로 열어 선택한600g/homeplus/8980 관측과 exact variant/listing/offer 및2+1/min2 원문 조건을 복원했다. 행사 종료 후 거래총액·수령량은 계속 보류하며 다른 거래로 자동 변경하지 않는다. 불완전·변경된 공유 tuple은 재선택 안내로 보류한다. 공급자 URL과 앱 공유 URL은 별개이며 native OS 공유 선택기는 미검증이다. 소유 합성 계정의 프로필 수정→새로고침→새 세션 재로그인 유지, 가격 알림 현재 미충족·조건보류 조회→해제→새로고침도 확인했고 기존cart/wishlist는 보존됐다. 외부 발송/자동수집/OAuth 성공을 뜻하지 않는다. 데이터69와 계정 없는 동봉 gzip은 변경하지 않았다.

271 제출 후보 범위: 외부 알림 이메일/푸시는 범위 밖이며 규칙 저장·조회·현재 조건 상태·해제는 유지한다. 원문 표시 가격·통화·수량·입증된 조건 산술은 실제 결제 미시험만으로 없애지 않는다. Homeplus269는 원문2190/2L×6/최소1·최대2·쿠폰을 보존했고 통화 미명시와 고객 쿠폰 적용은 별도 미확인이다. 핫딜의 표시가 차이25%도 원문 두 가격의 산술이며 보편적인 결제 할인 보장이 아니다. `WALLETSAVIOR_OPTIONAL_CRAWLERS=ruliweb`은 정상 공개 단일 feed collector를 관리 화면에 등록한다; 자동수집 예약을 만들지 않는다.

현재 catalog89는 기존 원문/관측9115와 source별 상품6308 기록의 ID를 유지한다. 원문으로 검토한409 공통 상품군1001기존ID는 논리 탐색·상세에서 함께 보이고 용량/묶음/마트listing/시점offer는 별개로 선택한다. 신라면 툼바137g×4(3마트), 비요뜨 초코링138g×2(2마트), 짜파게티140g×5/20과 생레몬 category를 대표 동선으로 사용한다. 초콜릿우유 동의어는 활성 통합category 범위에서 검색하며 다른맛우유/초코과자와 혼동하지 않는다. keyword765를 정식API로 가역 수정→publish→검색 소비→원값 복원한 이후 revision72이며 임시 검색어는 동봉하지 않는다. HP127938195는 원문101G·6입으로101g×6 규격을 정정했고 원가격9600/2시점event·옛variantID는 보존했다. 옛101g×1 tuple은 재선택 보류하며 호환규격으로 자동전환하지 않는다. 우유19 공통군48기존ID는 브랜드·라인·맛·형태를 원문으로 검토했고 저지방/일반/멸균/커피/초코는 서로 합치지 않았다. Emart0000008847095의 명시1L2개는1000ml×2로 정정하며5480원/원event/시각은 보존했다. 옛×1 선택은 재선택 보류하고 정상×2 규격의 과거관측과 연결한다. 수량정정과 구분되는 신규관측은0이다. 음료16 공통군43기존ID는 일반/제로·라임/레몬/포도·탄산/물/스포츠음료 및 혼합맛/가방포함 구성을 구분했다. 펩시 일반5개 source상품/3마트와 게토레이 레몬3마트를 추가 대표로 탐색한다. 크기·묶음·마트별 시점관측은 별도이고, 불확정 맛·라인은 다른상품군에서 채우지 않는다. 선택 출처의 종료 행사/원조건은 요약에도 보존하며 화면에 연결되지 않은 기간이력을 전체이력 부재로 표시하지 않는다. 커피17 공통군46기존ID는 원문의 브랜드·라인·로스트·디카페인·맛·형태를 검토해 연결했다. 카누 미니 마일드는4마트7기존ID의 용량·판매개수를 별도 선택하며 다크·디카페인은 다른군이다. 명시된 제로윗 믹스22500개는 질량이 미확인이므로 다른포장의9.5g을 전이하거나 정확질량단가를 만들지 않는다. 170g리필은 stickmix와 형태동일성 근거가 없어 기존상품을 별도 유지했다. 주스·베이스·무알콜10군24ID와 스낵6군12ID를 추가 검토했다. 카프리썬 오렌지200ml×10과 오렌지망고는 다른군이며 썬업100%파인애플750ml의2마트는 선택출처별 이력을 보존한다. 핫고래밥 매콤양념56g은 HP의 명시 밀가루스낵 경로와 동일브랜드·라인·맛 근거로 Lotte의 넓은 곡물 fallback만 정정했다. 옛LotteID/990원/원시점은 같은56g선택과 이력으로 유지한다. 하이트제로6팩2개는 동일라인 탐색 metadata에 포함돼도 기존inactive/가격보류를 유지하며 공개offer로 승격하지 않는다. 원9196/431·최종초기9098/98 인증은 역사 기록이며 이 작업이 새 전체 인증/실제 결제/전체매칭 완료라는 주장은 아니다.

카테고리의 수는 현재 활성 source행의 합이 아니라 같은 목록 resolver로 묶은 상품군·품목 수다. 과일음료의 보존된 source상품34개는32개 목록/child/페이지 총수로 일치하며 상세의 원 관측·시점은 그대로 유지한다.

육가공·어묵 및 비스킷·시리얼61군136기존ID를 추가 연결했다. 에이스는 크래커의73/218/364g, 오레오오즈는 링시리얼의30g/500g/500g×3 및4마트, 크리치오는 초코시리얼의30/500g을 별도로 선택한다. 옛source ID와 원1000원/시각/조건은 해당 선택 이력에 남고 원문4.5만원↑5천원 조건은 현재 확정 결제액으로 표시하지 않는다.10leaf 정합성 변경과2역사offer category 이력 추가는 원 승인·원 가격·원문·수량·event ID를 바꾸지 않는다. maker만 있고 명시 line이 빠진4군은 합치지 않았다. 다른 flavour/브랜드/종류를 이름 정규화만으로 병합하지 않는다.

기존 스낵·음료·육수·소스19군47ID를 추가 연결했다. 카라멜콘·땅콩은72g/150g 및 출처별 원 행사조건을 별도 유지하고 Lotte의 넓은 옥수수 leaf만 혼합스낵으로 정정했다. 청정원 고소한 마요네즈300/500g과 백설 사골가득1분링80g은 입증된 source끼리 연결한다. LIGHT&JOY 하프마요네즈와 이름에 해당 line이 없는 HP 포장은 별도군이며 국내산 미확인 육수·제조사 근거 없는 비타500 포장의 정보는 다른 source에서 채우지 않는다. 새 초기적재/가격관측은0이고 원9115event·수량·계정참조는 보존한다.

기존 식용유·감미료·제분13군35ID를 추가 연결했다. 백설카놀라유500/900ml의3마트5기존ID는 선택별9200원 원시점·이력을 유지하며 행사기간 안 조건계산과 기간밖 지급가격 미확인은 별도로 표시한다. 백설이 빠진CJ통참깨 source는 근거 없는 subbrand 전이 없이 별도 유지한다. 공백 있는/없는 하프마요 검색은 두 별도상품군을 찾고, 초콜릿 우유는 활성 chocolate milk category에만 한정한다. 이 공통 후보검색 정규화는 동일상품군·규격 병합 근거가 아니다. 현재동봉83 source/data12pins와 원9115관측·계정없는배포를 함께 사용하며 이전같은코드여정·설치 증거를 재사용했다.

치즈·버터·요구르트37군82기존ID를 추가 검토했다. 덴마크2X체다의3마트와2X모짜렐라는 서로 다른군이고, 엔요100ml×5/10/15와280ml×2는 다른규격으로 선택한다. 선택한원2290원/시점/자기이력은 전체군이력과 구분한다. 그릭플레인·달지않은저지방, 떠먹는/마시는/짜먹는, 과일맛·혼합맛은 원문에 따라 별도군이다. 본가격은 관측가이며 종료행사 지급총액을 현재가격으로 만들지 않는다. 296기존문맥 검토·38실제GET 범위의 source/data80 증거이며 전체상품 자동병합/신규적재/현재결제 검증은 아니다.

피자·빵·만두14군35ID를 추가 연결하고 명시 딤섬2·동일 순수통새우만두1의 넓은분류만 근거에 따라 정정했다. 동원딤섬새우하가우는300g×2/420g/1200g×2의3마트, 리스토란테모짜렐라피자는355g×1/×7을 별도 선택한다. 원9990원·시점·자기규격이력 및 종료행사 지급가격 보류를 유지한다. 실제Hanseom원문교자/찐만두 경로충돌과 비비고가 빠진수제진한고기만두는 자동합치지 않았다. 163기존문맥·37변경범위GET와 source/data81 근거이며 초기98/새출처 작업 및 전체정상 판정은 별개다.

장류·간장·카레·찌개양념29군66기존ID를 원문 named line별로 연결했다. 샘표진간장금F3 860ml/1.7L과 해찬들사계절쌈장170g/500g/1kg/500g×8은 별도규격이며 Gold/501/701·100%국산/우리쌀·정통/차돌/해물·카레순한맛/약간매운맛은 별도군이다. 원문 가격·시점·모든9115 event 및 계정참조를 보존하고 동일bundle 재적용은 변동없음으로 처리했다. 새 가격관측·초기적재·리프변경은0이며 source/data82는 누적263군629옛ID와18원문 leaf정정을 포함한다. 관측가·조건계산은 현재 확정결제와 다르며 초기98/새출처/전체자동병합은 범위에 넣지 않았다.

캔·즉석밥·세탁제품27군67ID를 추가 연결했다. 고추참치90g×4/×10·135g×4·100g×12의3마트와 작은햇반흑미/잡곡/발아현미는 각 원문 line·규격으로 선택하며, 테크일반/드럼과 샤프란리필/용기는 별도 제품군 또는 규격이다. 기존HP070254404 스팸닭가슴살200g×3은 명시 닭가슴살캔 원문으로 닭고기통조림 leaf/검색별칭에 연결했으며 돼지햄 스팸군과 합치지 않았다. 스팸브랜드 검색에서도 같은 옛ID가 남고 원10990원·자기이력1건·기간종료 상태를 보존한다. source/data83에는 누적290군696oldID·25leaf정정, 통합category1384/keyword1211, 원9115관측·공개8803/pending312·계정없는배포가 포함된다. 209기존문맥·변경50GET 및 별도브랜드2GET 범위의 증거이며 새관측/초기적재/현재결제/전수자동통합을 뜻하지 않는다.

종이·계란·두부/유부·기저귀·스프레드32군86ID를 원문 maker/line/form/recipe/grade/sex/year에 따라 추가 연결했다. 수프림소프트27m30롤/37m30롤×2, CJ대란15/25구, 소가300g의Lotte/HP 및초당옥수수198/340g는 별도 규격·자기이력을 선택한다. 기저귀 밴드/팬티·남/여·2026/미표시군과 텔레토비 기획팩/일반잼은 별도다. 하기스 매직컴포트 검색은 존재하는2026일반/썸머 두군을 찾으며 명시2025/다른브랜드는 제외한다. 연도·공백 검색 개선은 후보용이고 상품군 병합이나 미확인 구매조건 승격 근거가 아니다. 기존52GET 및변경검색5GET/38focused+변경family11 근거, source/data84는 누적322군782oldID·25leaf정정/9115원관측을 유지한다. 신규관측/초기98분류/전수정상/현재결제 검증은0·별도 범위다.

주방·욕실 세제/견과/쌀17군36ID를 원문 maker·line·purpose·flavour로 추가 연결했다. 자연퐁 솔잎490/1600/3040ml·HBAF세맛·이맛쌀10/20kg·골든퀸3kg×3/8kg×2·스카트3P/8P는 별도 규격·출처별 이력과 조건을 유지한다. 변경42GET 범위이며 단위가/현재구매가 전수완료는 아니다. Sunkist509119의 기존25g×60 스칼라는 이미 확보된3레시피 벡터를 누락해 동질100g단가를 만들었으므로 정식reviewed delta로3레시피각25g×20입/전체1세트 벡터에 연결했다. 옛scalar ID는inactive·재선택보류로 유지하며41990원/원event/시각/원문은 그대로다.523645는 정상JSON Unicode표현과3레시피각400입의 기존규격·ID를 그대로 유지했다. 앞선invalid-vector 진단은 정정된 역사 기록이며 정상혼합벡터를 일괄차단하지 않는다. 공통matching은 등록구성 원문에 대한 누락·malformed 대상벡터 HIT를 거절하며, 실제미입증metadata만 review/reject로 보낸다. 기존201 공식라벨은 클래식/팝/재즈 각각25g20입을 명시하므로 새 근거 요청 없이 재사용한다. 원문 단위가 표시를 서로 다른 레시피의 동질단위가로 취급하지 않는다. 신규관측0, 원9115/계정없는 배포·원9196/431/초기98 보존; 제출 후보 검증은 계속된다.

현재87은 김치15군55ID·해조2군4ID를 추가 연결하고, 원문상 볶음/묵은 김치6상품을 기존 세부leaf로 정정했다. 상품/규격/마트/시점 원ID와9115관측·가격은 보존하며, 역사 승인offer1건은 분류 전후 근거lineage만 추가했다. 일반 신선육 이름만으로 생산자·컷·등급·산지·냉장/냉동이 다른 상품을 강제 통합하지 않는다.

321의16공통군35기존ID는 정확 제조사·라인·형태·레시피 근거로 연결했고 판매 규격·원9115관측·가격·시점·계정참조를 유지했다. 원문20L가 기기 사양인 LG3출처는 판매수량/단가/수령패키지를 미확인으로 유지한다. 저장용 기본1을 실제 수령량으로 표시하지 않으며, 명시된 구매조건의 수령 반복은 물리 패키지 수량과 구분한다. 이 변경은 관련40focused·화면7GET와 기존21GET 근거이며 전체 제출 품질통과 선언이 아니다.

330의37공통군89기존ID는 냉면·떡볶이·봉지/컵라면·볶음밥의 명시된 제조사·좁은 레시피·형태로 연결했다. 기존14등록군36ID는 재사용하고 새로운 병합 수에 포함하지 않았다. 김치사발면86g의1/6/24팩과 큰사발112g, 진짬뽕 봉지130g와 큰컵115g·굴진짬뽕, 볶음밥과컵반을 구분한다. 네 대표 실제 search→선택tuple→own/fullgroup 이력 및 옛 출처 URL3개 복원은28GET·쓰기0·외부요청0으로 확인했고 인분을 판매조각으로 바꾸지 않았다. 원9115관측·가격·시점·규격·사용자참조를 유지했다. 이 추가 검토는 모든6308상품의 전수동일성 확인이나 최종 제출 통과를 뜻하지 않는다.

340의355기등록 문맥에서8공통군16옛ID를 추가해 당시417군1017옛ID가 연결됐다. 홈스타 세탁조클리너450ml 단품/8팩은 실제 내용량 규격을 유지하고, 몰리스 프로발란스 어덜트3kg/8kg은 별도 규격이다. 별도로 휴지통3상품의10/20/24L를 공통 빈용기 용량 역할로 정정했다. 용량은 원문·spec에 보존하고 판매개수·수령량·ml단위가는 미확인으로 둔다. 옛 scalar 선택은 묵시 전환하지 않고 재선택 안내하며 원event/가격/시점은 유지한다. 정식apply/replay/snapshot90 및 실제31GET·쓰기0·외부요청0의 검색/선택/전체이력/옛URL 경계를 확인했고 원9115관측·계정참조를 보존했다. 원본98분류나 새 출처는 재개하지 않았고 전체 제출 완료 주장은 아니다.

355 누적: 새482기등록문맥과 재사용4문맥에서25군64옛ID를 연결해 당시442군1081옛ID를 유지한다. 색상·침대크기·팬직경·와이퍼폭은 별도 source variant이며 치수는 판매수량이 아니다. 판매1은 저장된 BC350 원 포장1x에만 적용되고 다른 물품NULL은 유지된다. 원9115 event/가격/시각/계정·FK를 정식91/92 apply/replay/publish 및 일치source의92 remote upload로 보존했고 배포계정은0이다. 변경실제18GET/쓰기0/외부요청0은 보리차 oldmember tuple·full5/own1·두HP규격이력, Harmony두색NULL, Bosch7폭,104커피의 최근순 두page20개씩·중복0, 대표Costco보다늦은HP group시각을 확인했다. 전체104순위 재구성·Windows 실행은 주장하지 않는다. 추가 실제 브라우저에서는 동일 소유 subject/공개demo서명으로 로컬 access 만료를 설정한 후 등록·댓글·수정·삭제의401→유효refresh200→쓰기200 각1회와 초안/coldread 보존을 확인했다. refresh도만료되면 재전송0·로그인안내·재로그인초안보존을 확인하고 생성 글을 정식UI로 삭제했다. 실제 자연만료 대기나 외부OAuth 확인은 아니다. 설치12·최근순9·비동기/공통refresh17·등록source snapshot7+2 집중 경계와Web build를 확인했다; 전체catalog 인증/초기98분류/새출처는 반복하지 않았다.

364의362기등록 문맥에서22군49옛ID를 추가해 catalog93/464군1130옛ID가 연결됐다. 티젠 콤부차 맛별군, CJ/오뚜기 명시 레시피·라인, 스카치 정사각 보수패치와롤타입을 구분했다. Costco 고메810g 냉동bulk는152g군과 동일 레시피/보관형태 bridge가 입증되지 않아 별도로 유지했다. 양·규격·리프·원9115event/시점/가격/계정참조는 바꾸지 않고 metadata만 정식apply/replay/publish로 반영했다. 실제23GET/쓰기0/외부요청0은 일반/쇠고기짜장 분리·옛Emart tuple/own2/전체5, 레몬150g/300g·own2/전체3, 정사각패치NULL과롤 별도규격/옛1m source history를 확인했다. 롤0.5/1m는 저장spec이며 검증된 판매목적·선형수령량·m단위가는NULL과명시보류를 유지한다. 초기98·새출처·전수동일성·최종제출완료를 주장하지 않는다.

378의536기등록 원문 문맥에서20군45옛ID와 기존 리프3건을 근거로 정정해 catalog94/484군1175옛ID가 연결됐다. 제스프리 골드·그린, 조미료 고유라인·레시피, 샌드과자 맛별·상하목장 밀크/초코, 명시 건강식품 라인을 구분한다. 강된장 원문과 롯데의 튜브아이스크림 세부 경로를 기존 자료에서 회수했으며 새 형태·수량을 추측하지 않았다. 정식apply/replay/publish94는 원9115event/관측가격/시각/규격/계정참조를 보존한다. 실제24GET/쓰기0/외부요청0에서 새 카테고리·마트군·옛ID별 전체이력과 골드1팩 내부수량 미확인·510ml와85ml×6 별도규격·선택3개/무료1개 결제보류·맛소금250g 두 마트의 표시조건 관측 단가를 확인했다. 표시조건 비교를 실제 결제 영수증이나 전상품 현재 최저가로 확대하지 않는다. 초기98·새출처·전수동일성·최종제출완료는 계속 주장하지 않는다.

Catalog95는 426개 기존 원문 문맥에서 입증된 8상품군·16기존 ID의 연결만 추가했다. 배터리 AA/AAA·기존 판매개수, 그릴 치수와 물품 NULL, 바나나 산지·라인, 밤 포장, 생크림 및 표고 선물 구성은 각 원 규격에 남는다. 기존 9115 관측·가격·시점·계정 참조를 보존했고 신규 관측은 없다.

현재97은 에너자이저 두10+10기획팩의 미입증 판매개수를 물품NULL로, 벡셀8+8입의 명시 포장구성을16입으로 정정했다. literal 규격·12900/8900원 관측·원event/시각/전체이력은 유지하며 bareN+N을 N팩구매+N팩증정으로 만들지 않는다. 판매묶음 행사역할/지급금액 미확인은 별도 보류다. 원래1개/8입 선택은 재선택 안내하고 기존 참조를 묵시적으로 새 규격에 옮기지 않는다. 두NULLID namespace 정정은 별도96→97 이력에 보존했다. 정상22/32입·내용량·혼합벡터는 기존 근거를 유지하며 신규관측·초기98분류·전체인증은 반복하지 않았다.

현재98은 신선채소 아래 같은4단계의 로메인·버터헤드·얼갈이 sibling 탐색을 연결하고 혼합채소/스낵1건을 원문 형태에 맞췄다. 원431 쌈채소 결정3건의 번호/hash와 넓은 용도 의미는 파생 정정이력으로 보존하며 원파일은 바꾸지 않았다. 원규격/혼합벡터·9115관측·시각/계정참조는 그대로다. Community 선택 투표는 검증된 계정 subject의 서버값만 cold 재조회에 복원하고 해제 후NULL을 유지한다. backend6/frontend4집중 경계와 실제 새 브라우저22HTTP/외부0·삭제후404를 확인했고,355의 만료refresh 단일쓰기 증거는 반복하지 않았다. 동봉98/source24pins·계정0이며 제출후보 검증은 계속된다.

현재99 동봉 데이터는492군/1191옛ID/41분류 정정이력과9115관측을 유지한다. 전기·숯 그릴4건, 고구마 건조스낵2건, 스텐 식판1건의 원문에 묶인 세부 탐색을 정정했다. 기기·식판의 물품NULL과 두 스낵의300g·80g×10 원규격, 가격·시점·계정참조는 바꾸지 않았다. 실제14GET의 변경 탐색·상세와3GET의 관측 설명을 확인했다. 검색은 관측 조건 비교금액이며 선택 상세는 해당 출처 표시가격·관측 시점으로 설명하고 현재 구매가로 단정하지 않는다. source24pins/배포계정0과9개 정식 갱신파일을 함께 제공하며 제출후보 검증은 계속된다.

현재101은23기존상품의 입증된 형태를7공통4단계 리프로 구체화하고,20건의 출처 단가 기준을 판매내용량으로 오독한 파생규격을 정정한다. 명시 티백·정·캡슐 개수8건은 개수규격으로, 판매내용량 미입증12건은 수량 미확인으로 유지한다. 캡슐mg을 총판매g으로 환산하지 않았고 독립라벨100g/100ml·명시80g은 유지한다. 출처 단가문구·원가격·원시각은 그대로 설명/이력에 표시하며 미확인 내용을 정확g·단가·수령1로 만들지 않는다. 41고유 원상품/20새규격과20옛inactive규격 이력,6458판매페이지/원9115event/계정참조 및492군1191옛ID를 보존한다.100→101 정식preview/apply/동일replay/snapshot101 및 변경15GET·실제matching/export60HIT80거절 근거가 있으며 신규 상품/관측 적재0이다. 배포계정0,91source-leaf reviews/26sourcepins. 초기98·새출처·전체인증은 중단 유지한다.
