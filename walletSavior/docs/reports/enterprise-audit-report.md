# WalletSavior 엔터프라이즈 배포 준비성 감사 보고서

> 감사일: 2026-04-15 | 감사 모델: GPT-5.4 | 대상: walletSavior 전체 monorepo

## 총평
- **현 상태는 엔터프라이즈 프로덕션 배포 불가**
- 특히 **비밀정보 커밋**, **관리자 인증 기본 비활성화**, **공유 SQLite 의존**, **깨진 Docker 배포 구성**이 치명적
- 일부 이미 구현된 항목: Alembic 마이그레이션, 헬스체크, graceful shutdown, 일부 retry/circuit breaker, GZip, DB 인덱스

---

## 1. 인프라 및 배포

### 🔴 Critical — 배포용 Docker Compose가 현재 저장소와 불일치
- `docker-compose.yml:37-39`, `56-58` → `./proj`, `./proj/frontend-react` 빌드 참조
- `docker-compose.yml:73-74` → `./nginx/default.conf` 마운트
- 실제 저장소에는 `proj/`, `nginx/`, 백엔드 `Dockerfile`이 없음
- **영향:** 현재 compose로는 재현 가능한 프로덕션 배포 불가

### 🔴 Critical — 기본 실행 경로가 공유 SQLite 파일에 강하게 결합
- `packages/website/backend/services/db.py:26`, `39-51`
- `packages/website/backend/api/app.py:130-145`
- `packages/db-admin/backend/config.py:7-12`
- `packages/website/backend/.env:4`
- **영향:** 단일 파일 DB에 website/db-admin/community가 결합. 다중 인스턴스/다중 writer/네트워크 스토리지 환경에 취약

### 🟡 Warning — WAL은 일부만 적용, 커뮤니티 경로는 우회
- WAL 적용: `packages/website/backend/services/db.py:54-60`, `packages/db-admin/backend/services/base.py:70-76`
- 우회: `packages/website/backend/api/routes/community.py:62-68`
- **영향:** SQLite 동시성 완화는 일부 경로만 보장

### 🔴 Critical — 수평 확장 사실상 불가
- SQLite 파일 공유 + 인메모리 상태:
  - `packages/website/backend/api/middleware/rate_limit.py:15,44-48`
  - `packages/website/backend/api/routes/hotdeals.py:23-39`
  - `packages/website/backend/services/oauth_service.py:73-106`
  - `packages/crawler-admin/backend/scheduler/job_tracker.py:24-33`
- **영향:** 멀티 인스턴스 시 레이트리밋, OAuth state, 작업 이력, 캐시 불일치

### 🟢 Info — 마이그레이션 시스템은 존재함
- `packages/db-admin/backend/alembic.ini:8`
- `packages/db-admin/backend/storage/migrations/versions/8018226a8e9e_initial_complete_schema.py`

### 🟢 Info — 헬스체크 엔드포인트 존재
- website: `packages/website/backend/api/app.py:219-279`
- db-admin: `packages/db-admin/backend/api/app.py:223-242`
- crawler-admin: `packages/crawler-admin/backend/api/app.py:119-181`

### 🟢 Info — graceful shutdown 구현됨
- website: `packages/website/backend/api/app.py:47-70`
- db-admin: `packages/db-admin/backend/api/app.py:29-85`
- crawler-admin: `packages/crawler-admin/backend/api/app.py:183-268`

### 🔴 Critical — 서비스 디스커버리/로드밸런싱/복제 전략 없음
- `docker-compose.yml:81-83` 단일 bridge network만 존재

### 🔴 Critical — 장애 시 website가 mock/빈 응답으로 숨김
- `packages/website/backend/api/app.py:151-153`, `210-217`
- **영향:** DB 장애가 사용자에게 "빈 데이터"처럼 보여 탐지 지연

---

## 2. 보안

### 🔴 Critical — 실 비밀정보가 저장소에 커밋됨
- `packages/website/backend/.env:15` → `JWT_SECRET_KEY=dev-secret-key-change-in-production`
- `packages/website/backend/.env:22-23` → Google OAuth client id/secret

### 🔴 Critical — db-admin 인증이 기본 비활성화이며 anonymous admin 허용
- `packages/db-admin/backend/config.py:37-38`
- `packages/db-admin/backend/api/auth.py:7-10`, `85-90`, `131-132`

### 🔴 Critical — crawler-admin도 인증 기본 비활성화
- `packages/crawler-admin/backend/.env.example:18-19`
- `packages/crawler-admin/backend/api/security/auth.py:29-31`, `47-49`

### 🔴 Critical — OAuth 토큰을 URL 쿼리스트링으로 프론트에 전달
- `packages/website/backend/api/routes/auth.py:199-204`
- `packages/website/frontend/src/pages/Auth/AuthCallback.jsx:15-28`
- **영향:** 브라우저 히스토리, 리퍼러, 프록시 로그로 토큰 유출 가능

### 🔴 Critical — 토큰을 sessionStorage에 저장
- `packages/website/frontend/src/services/api.js:69-80`, `214-229`
- **영향:** XSS 발생 시 탈취 가능. httpOnly cookie 부재

### 🟡 Warning — OAuth access/refresh token을 DB 평문 저장
- `packages/db-admin/backend/storage/models.py:103-104`

### 🟡 Warning — CORS 기본값이 localhost 중심
- website: `packages/website/backend/api/app.py:109-119`

### 🟡 Warning — 레이트리밋 저장소 기본값이 메모리
- website: `packages/website/backend/api/middleware/rate_limit.py:15`

### 🔴 Critical — HTTPS/TLS 구성이 저장소에 없음
- nginx/default.conf 부재, TLS 종단 구성 불명확

### 🟢 Info — XSS 방어는 커뮤니티 경로에 적용됨
- `packages/website/backend/api/utils/sanitize.py:37-52`
- `packages/website/frontend/src/utils/sanitize.js:31-34`

### 🟢 Info — SQL Injection 위험은 주 API 경로에서 낮음
- ORM/select/filter 사용 확인

---

## 3. 가용성 및 복원력

### 🟢 Info — 일부 retry/circuit breaker 존재
- `packages/website/backend/api/utils/storage_proxy.py:14-16`
- `packages/crawler-admin/backend/pipeline/circuit_breaker.py:28-116`

### 🟡 Warning — 외부 호출 정책이 서비스별로 일관되지 않음
- OAuth `httpx.AsyncClient()`에 timeout/retry 부재: `oauth_service.py:133-145`

### 🟡 Warning — 내구성 있는 큐 시스템 없음
- APScheduler 기반, 이력은 인메모리: `scheduler/job_tracker.py:24-33`

### 🟡 Warning — 백업은 수동, 자동화/복구 절차 없음

### 🟡 Warning — 모니터링/알림/메트릭 수집 부재

### 🟡 Warning — 인메모리 상태 성장 리스크
- OAuth state dict, flyer cache, hotdeal rate limit dict

---

## 4. 성능

### 🟡 Warning — Redis/공유 캐시 미활용
- 로컬 TTL cache만 존재, 다중 인스턴스 공유 불가

### 🟡 Warning — 일부 엔드포인트 메모리 슬라이싱 (DB 페이지네이션 미사용)
- `packages/website/backend/api/routes/products.py:183-186`
- `packages/website/backend/api/routes/search.py:56-58`

### 🟢 Info — 응답 압축 (GZip) 구현됨

### 🟢 Info — DB 인덱스 전략은 잘 구성됨
- `packages/db-admin/backend/storage/models.py:171-177`, `199-203`

### 🟡 Warning — CDN/정적 자산 배포 전략 없음

---

## 5. 운영

### 🔴 Critical — CI/CD 파이프라인 없음 (`.github/workflows/` 부재)

### 🟡 Warning — 환경별 설정은 있으나 수작업 의존

### 🟡 Warning — feature flag / A/B test / analytics 부재

### 🟡 Warning — 배포 문서는 로컬 실행 중심

---

## 6. 규정 준수 / 법적 리스크

### 🔴 Critical — 개인정보/약관 링크가 placeholder
- `packages/website/frontend/src/components/layout/Footer.jsx:13-15`

### 🔴 Critical — 개인정보 + OAuth 토큰 보관 정책 부재

### 🟡 Warning — 쿠키/동의 배너 없음

### 🔴 Critical — 크롤링 법적 리스크: robots/TOS 준수 코드 부재 + anti-bot 우회 명시
- `packages/crawler-admin/backend/engine/anti_detect.py:2-12`, `75-85`

---

## 우선순위 권고

### 즉시 조치 (P0)
1. 저장소에서 `.env` 제거 및 모든 노출 secret 전면 교체
2. db-admin/crawler-admin `REQUIRE_AUTH=true` 강제
3. OAuth 토큰 URL 전달 중단, httpOnly secure cookie로 변경
4. 공유 SQLite 운영 중지, PostgreSQL 단일 권위 DB로 전환
5. 깨진 `docker-compose.yml` 교체 및 실제 Dockerfile/nginx/TLS 구성 추가

### 단기 (P1)
1. Redis 기반 rate limit / shared cache
2. 정기 백업 + 복원 리허설
3. Prometheus/Grafana/Sentry/OpenTelemetry 도입
4. 운영 런북, 배포 절차, 롤백 절차 문서화
5. robots/TOS 준수 검토 및 크롤링 법무 검토

### 중기 (P2)
1. CI/CD 구축
2. feature flag / analytics
3. 분산 작업 큐(Celery/RQ/Arq 등) 도입
4. 개인정보 보존/삭제 정책 및 약관/개인정보처리방침 정식 반영
