# Round R G5-b 핫딜 파이프라인 보고

## 산출물
- 핫딜 전용 ORM: `packages\db-admin\backend\storage\models.py`에 `HotdealPost`, `HotdealCommentSnapshot`, `HotdealSourceSite` 추가.
- Alembic placeholder: `packages\db-admin\backend\storage\migrations\versions\g5b0hotdeal_round_r_g5b_hotdeal_posts.py`.
- 알구몬 fixture 크롤러: `packages\crawler-admin\backend\crawlers\hotdeals\algumon\crawler.py`.
- entrypoint: `packages\crawler-admin\backend\crawlers\hotdeals\algumon\entrypoints.py`.
- fixture/test: `packages\crawler-admin\backend\tests\fixtures\algumon\sample_list.html`, `packages\crawler-admin\backend\tests\test_algumon_crawler.py`.

## 모델 결정
- 마트 `Product` 테이블은 수정하지 않고 핫딜 원문을 `hotdeal_posts`로 분리했다.
- 댓글/추천 수는 주간 누적 가능한 `hotdeal_comment_snapshots`로 분리했다.
- `hash_dedup`은 source/native id 또는 정규화 URL 기반 SHA-256으로 안정화했다.

## 알려진 한계
- 실제 algumon.com 라이브 HTML 정찰은 아직 미완료다.
- 현재 selector는 placeholder fixture 전용이며 라이브 HTTP 호출을 하지 않는다.
- Alembic `down_revision`은 의도적으로 `None` placeholder다. 메인이 G2-mapping 완료 후 head를 reconcile해야 한다.

## 다음 단계
- 메인 세션이 Playwright MCP로 알구몬 목록 DOM을 정찰한다.
- 정찰 결과로 fixture와 selector를 교체하고 마이그레이션 chain을 확정한다.
