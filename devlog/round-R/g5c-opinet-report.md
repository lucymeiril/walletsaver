# Round R G5-c 오피넷 주유소 가격 스켈레톤 보고

## 변경 파일
- `packages\crawler-admin\backend\crawlers\opinet\crawler.py`: `crawl_region(sido)` fixture-only 스켈레톤, 브랜드/유종/가격 정규화 dataclass 추가.
- `packages\crawler-admin\backend\crawlers\opinet\plugin.yaml`, `entrypoints.py`: 오피넷 플러그인/진입점 등록.
- `packages\db-admin\backend\storage\opinet_models.py`: mart Product와 분리된 오피넷 전용 `GasStation`, `GasStationPrice` 모델 추가.
- `packages\db-admin\backend\storage\migrations\versions\r_g5c_opinet.py`: 오피넷 전용 테이블 마이그레이션 추가. `down_revision`은 TODO 유지.
- `packages\web-frontend\src\App.tsx`, `components\NavBar.tsx`, `pages\FuelStationsPage.tsx`: `/fuels` 주유소 가격 탭 연결 및 지역/연료/가격 정렬 옵션 준비.
- `tests\fixtures\opinet\sample_seoul.json`, `tests\test_opinet_crawler.py`: JSON fixture와 파싱/정규화 테스트 추가.

## 범위
- 라이브 HTTP/API 호출 없음.
- 실제 오피넷 API/마크업 구조는 추측하지 않고 fixture 구조만 정의.
- 4사 mart Product/price_history는 변경하지 않음.

## 미해결
- Alembic `down_revision` head reconcile은 메인 작업에서 실제 head로 교체 필요.
- 실제 오피넷 API/마크업 정찰 및 운영 수집 활성화는 후속 작업 필요.
