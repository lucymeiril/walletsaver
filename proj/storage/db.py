"""
DB 저장소 구현 — StorageContract의 구체 구현체.

왜 존재하는가:
    core/contracts/storage.py의 인터페이스를 실제 SQLAlchemy로 구현한다.
    다른 모듈은 StorageContract만 알고, 이 구체 클래스는 container.py에서만 import.
어디서 쓰이는가:
    container.py → DBStorage() 생성 → app.state.storage로 주입 → API 라우터에서 사용.
동기 vs 비동기:
    초기 단계에서는 동기 SQLAlchemy 사용. FastAPI는 sync 함수를 threadpool에서 실행하므로
    성능 문제 없음. 트래픽 증가 시 async SQLAlchemy로 마이그레이션 가능.
"""

import os
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import create_engine, select, func, desc
from sqlalchemy.orm import Session, sessionmaker

from storage.models import (
    Base, Product, BaselinePrice, DiscountHistory,
    HotdealPost, GasStation, CrawlLog, UserFavorite, PriceAlert,
)
from core.contracts.storage import StorageContract


class DBStorage(StorageContract):
    """
    SQLAlchemy 기반 저장소 — SQLite(개발) / PostgreSQL(운영) 자동 전환.

    왜 동기 세션인가:
        async session은 모든 관계 로딩에 await가 필요하고 디버깅이 어렵다.
        FastAPI가 sync 함수를 자동으로 threadpool에서 실행하므로 blocking 문제 없음.
    """

    def __init__(self, database_url: str | None = None):
        if database_url is None:
            database_url = os.getenv(
                "DATABASE_URL",
                "sqlite:///walletguardian.db",
            )
        # SQLite 전용 설정 — check_same_thread=False로 멀티스레드 접근 허용
        connect_args = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        self.engine = create_engine(
            database_url, echo=False, connect_args=connect_args
        )
        self.SessionLocal = sessionmaker(bind=self.engine)

    def init_db(self) -> None:
        """모든 테이블을 생성한다. 이미 존재하면 스킵."""
        Base.metadata.create_all(self.engine)

    # ──────────────────────────────────────────
    # StorageContract 필수 구현
    # ──────────────────────────────────────────

    async def save_crawl_log(
        self,
        crawler_name: str,
        status: str,
        items_count: int,
        started_at: datetime,
        finished_at: datetime,
        error_msg: Optional[str] = None,
        diagnosis: Optional[dict] = None,
    ) -> int:
        """크롤링 실행 로그 저장 — 엔진이 크롤 완료 후 호출."""
        with self.SessionLocal() as session:
            log = CrawlLog(
                crawler_name=crawler_name,
                status=status,
                items_count=items_count,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
                error_msg=error_msg,
                diagnosis=diagnosis,
            )
            session.add(log)
            session.commit()
            session.refresh(log)
            return log.id

    async def save_collected_data(
        self,
        crawler_name: str,
        data_type: str,
        items: list[dict],
    ) -> int:
        """
        수집 데이터를 data_type에 따라 적절한 테이블에 분기 저장.

        data_type 분기:
            "discount" → DiscountHistory (마트 할인가)
            "hotdeal"  → HotdealPost (커뮤니티 핫딜)
            "price"    → BaselinePrice (정가/공식가)
            "gas"      → GasStation (주유소)
        """
        if data_type == "discount":
            return self._save_discount_items(items)
        elif data_type == "hotdeal":
            return self._save_hotdeal_posts(items)
        elif data_type == "price":
            return self._save_baseline_prices(items)
        elif data_type == "gas":
            return self._save_gas_stations(items)
        return 0

    async def get_crawl_logs(
        self,
        crawler_name: Optional[str] = None,
        status: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """크롤링 로그 조회 — 대시보드 크롤러 상태 표시용."""
        with self.SessionLocal() as session:
            stmt = select(CrawlLog).order_by(desc(CrawlLog.started_at))
            if crawler_name:
                stmt = stmt.where(CrawlLog.crawler_name == crawler_name)
            if status:
                stmt = stmt.where(CrawlLog.status == status)
            if since:
                stmt = stmt.where(CrawlLog.started_at >= since)
            stmt = stmt.limit(limit)

            logs = session.execute(stmt).scalars().all()
            return [
                {
                    "id": log.id,
                    "crawler_name": log.crawler_name,
                    "status": log.status,
                    "strategy_used": log.strategy_used,
                    "items_count": log.items_count,
                    "started_at": log.started_at.isoformat() if log.started_at else None,
                    "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                    "duration_seconds": log.duration_seconds,
                    "error_msg": log.error_msg,
                }
                for log in logs
            ]

    async def get_collected_data(
        self,
        data_type: Optional[str] = None,
        crawler_name: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict]:
        """수집된 데이터 조회 — data_type별 분기."""
        if data_type == "discount":
            return self._query_discounts(limit=limit, since=since)
        elif data_type == "hotdeal":
            return self._query_hotdeals(limit=limit, since=since)
        elif data_type == "gas":
            return self._query_gas_stations()
        # 기본: baseline prices
        return self._query_baseline_prices(limit=limit, since=since)

    # ──────────────────────────────────────────
    # 프론트엔드 API 전용 메서드
    # ──────────────────────────────────────────

    def get_products(self) -> list[dict]:
        """
        전체 상품 목록 + 현재가/평균/최저/최고/매장별 가격.

        프론트엔드 PRODUCTS 배열과 동일한 shape을 반환한다.
        shape: {id, name, icon, cat, unit, avg, cur, low, high, stores, stats}
        """
        with self.SessionLocal() as session:
            products = session.execute(
                select(Product).where(Product.is_active == True)
            ).scalars().all()

            result = []
            for p in products:
                price_stats = self._compute_product_stats(session, p.id)
                store_prices = self._get_store_prices(session, p.id)
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "icon": p.icon,
                    "cat": p.category,
                    "unit": p.unit,
                    "avg": price_stats["avg"],
                    "cur": price_stats["cur"],
                    "low": price_stats["low"],
                    "high": price_stats["high"],
                    "img": "",
                    "stores": store_prices,
                    "stats": {
                        "dataDays": price_stats["data_days"],
                        "records": price_stats["records"],
                        "confidence": [price_stats["low"], price_stats["high"]],
                        "outliers": 0,
                        "avgDiscount": price_stats["avg_discount"],
                        "discFreq": price_stats["disc_freq"],
                    },
                })
            return result

    def get_product_detail(self, product_id: int) -> dict | None:
        """단일 상품 상세 — get_products()와 동일 shape + 추가 메타."""
        with self.SessionLocal() as session:
            p = session.get(Product, product_id)
            if not p:
                return None
            price_stats = self._compute_product_stats(session, p.id)
            store_prices = self._get_store_prices(session, p.id)
            return {
                "id": p.id,
                "name": p.name,
                "icon": p.icon,
                "cat": p.category,
                "unit": p.unit,
                "avg": price_stats["avg"],
                "cur": price_stats["cur"],
                "low": price_stats["low"],
                "high": price_stats["high"],
                "img": "",
                "stores": store_prices,
                "stats": {
                    "dataDays": price_stats["data_days"],
                    "records": price_stats["records"],
                    "confidence": [price_stats["low"], price_stats["high"]],
                    "outliers": 0,
                    "avgDiscount": price_stats["avg_discount"],
                    "discFreq": price_stats["disc_freq"],
                },
                "attributes": p.attributes or {},
            }

    def get_hotdeals(
        self,
        category: str | None = None,
        sort: str = "time",
        limit: int = 20,
    ) -> list[dict]:
        """
        핫딜 목록 — 프론트엔드 HOTDEALS 배열과 동일 shape.

        shape: {id, title, source, price, origPrice, time, cat, views, comments, thumb}
        """
        with self.SessionLocal() as session:
            stmt = select(HotdealPost)
            if category and category != "all":
                stmt = stmt.where(HotdealPost.category == category)

            if sort == "time":
                stmt = stmt.order_by(desc(HotdealPost.crawled_at))
            elif sort == "views":
                stmt = stmt.order_by(desc(HotdealPost.views))
            elif sort == "comments":
                stmt = stmt.order_by(desc(HotdealPost.comments_count))

            stmt = stmt.limit(limit)
            posts = session.execute(stmt).scalars().all()

            return [
                {
                    "id": post.id,
                    "title": post.title,
                    "source": post.source_community,
                    "price": post.price,
                    "origPrice": post.original_price,
                    "time": self._relative_time(post.crawled_at),
                    "cat": post.category,
                    "views": post.views,
                    "comments": post.comments_count,
                    "thumb": post.thumbnail_url,
                }
                for post in posts
            ]

    def get_mart_deals(self, store: str | None = None, limit: int = 50) -> dict:
        """
        마트별 할인 정보 — 프론트엔드 MART_DATA와 동일 shape.

        shape: {storeName: {name, color, period, flyerImg, items: [{name, orig, sale, disc, event, img}]}}
        """
        # 마트 메타 정보
        mart_meta = {
            "이마트": {"key": "emart", "color": "#FFD700"},
            "홈플러스": {"key": "homeplus", "color": "#FF6B35"},
            "롯데마트": {"key": "lotte", "color": "#E4002B"},
            "코스트코": {"key": "costco", "color": "#E31837"},
        }

        with self.SessionLocal() as session:
            stmt = select(DiscountHistory).order_by(desc(DiscountHistory.crawled_at))
            if store:
                stmt = stmt.where(DiscountHistory.store == store)
            stmt = stmt.limit(limit)

            items = session.execute(stmt).scalars().all()

            # 매장별 그룹핑
            grouped: dict[str, list] = {}
            for item in items:
                store_name = item.store
                if store_name not in grouped:
                    grouped[store_name] = []
                grouped[store_name].append({
                    "name": self._get_product_name(session, item.product_id) or "",
                    "orig": item.original_price,
                    "sale": item.sale_price,
                    "disc": round(item.discount_percent) if item.discount_percent else 0,
                    "event": item.event_name,
                    "img": item.image_url,
                })

            result = {}
            for store_name, deal_items in grouped.items():
                meta = mart_meta.get(store_name, {"key": store_name, "color": "#666"})
                result[meta["key"]] = {
                    "name": store_name,
                    "color": meta["color"],
                    "period": "",
                    "flyerImg": "",
                    "items": deal_items,
                }
            return result

    def get_gas_prices(self, fuel_type: str = "gasoline", sort_by: str = "price") -> list[dict]:
        """
        주유소 목록 — 프론트엔드 GAS_STATIONS와 동일 shape.

        shape: {name, addr, gasoline, diesel, lpg, brand}
        """
        with self.SessionLocal() as session:
            stmt = select(GasStation)

            # 연료 종류별 정렬
            price_col = {
                "gasoline": GasStation.gasoline_price,
                "diesel": GasStation.diesel_price,
                "lpg": GasStation.lpg_price,
            }.get(fuel_type, GasStation.gasoline_price)

            if sort_by == "price":
                stmt = stmt.order_by(price_col.asc().nullslast())
            else:
                stmt = stmt.order_by(GasStation.name)

            stations = session.execute(stmt).scalars().all()

            return [
                {
                    "name": s.name,
                    "addr": s.address,
                    "gasoline": s.gasoline_price,
                    "diesel": s.diesel_price,
                    "lpg": s.lpg_price,
                    "brand": s.brand,
                }
                for s in stations
            ]

    def get_price_history(self, product_id: int, days: int = 30) -> list[dict]:
        """
        가격 추이 데이터 — 프론트엔드 genPriceHistory()와 동일 shape.

        shape: [{date: "MM-DD", price: int}]
        """
        since = datetime.now() - timedelta(days=days)
        with self.SessionLocal() as session:
            stmt = (
                select(
                    func.strftime("%m-%d", BaselinePrice.recorded_date).label("date"),
                    func.avg(BaselinePrice.price).label("price"),
                )
                .where(
                    BaselinePrice.product_id == product_id,
                    BaselinePrice.recorded_date >= since,
                )
                .group_by(func.strftime("%m-%d", BaselinePrice.recorded_date))
                .order_by(BaselinePrice.recorded_date)
            )
            rows = session.execute(stmt).all()
            return [{"date": row.date, "price": round(row.price)} for row in rows]

    def search_products(self, query: str) -> list[dict]:
        """품목 검색 — 이름 또는 카테고리에 query가 포함된 상품."""
        with self.SessionLocal() as session:
            stmt = (
                select(Product)
                .where(
                    Product.is_active == True,
                    (Product.name.contains(query)) | (Product.category.contains(query)),
                )
            )
            products = session.execute(stmt).scalars().all()
            result = []
            for p in products:
                price_stats = self._compute_product_stats(session, p.id)
                store_prices = self._get_store_prices(session, p.id)
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "icon": p.icon,
                    "cat": p.category,
                    "unit": p.unit,
                    "avg": price_stats["avg"],
                    "cur": price_stats["cur"],
                    "low": price_stats["low"],
                    "high": price_stats["high"],
                    "img": "",
                    "stores": store_prices,
                    "stats": {
                        "dataDays": price_stats["data_days"],
                        "records": price_stats["records"],
                        "confidence": [price_stats["low"], price_stats["high"]],
                        "outliers": 0,
                        "avgDiscount": price_stats["avg_discount"],
                        "discFreq": price_stats["disc_freq"],
                    },
                })
            return result

    # ──────────────────────────────────────────
    # 사용자 기능 — 즐겨찾기 / 알림
    # ──────────────────────────────────────────

    def get_user_favorites(self, user_id: str) -> list[dict]:
        """사용자 즐겨찾기 목록 조회."""
        with self.SessionLocal() as session:
            stmt = (
                select(UserFavorite, Product)
                .join(Product, UserFavorite.product_id == Product.id)
                .where(UserFavorite.user_id == user_id)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    "product_id": fav.product_id,
                    "name": prod.name,
                    "icon": prod.icon,
                    "cat": prod.category,
                    "unit": prod.unit,
                    "added_at": fav.created_at.isoformat() if fav.created_at else None,
                }
                for fav, prod in rows
            ]

    def add_user_favorite(self, user_id: str, product_id: int) -> dict:
        """즐겨찾기 추가."""
        with self.SessionLocal() as session:
            fav = UserFavorite(user_id=user_id, product_id=product_id)
            session.add(fav)
            session.commit()
            return {"user_id": user_id, "product_id": product_id, "status": "added"}

    def remove_user_favorite(self, user_id: str, product_id: int) -> dict:
        """즐겨찾기 제거."""
        with self.SessionLocal() as session:
            stmt = select(UserFavorite).where(
                UserFavorite.user_id == user_id,
                UserFavorite.product_id == product_id,
            )
            fav = session.execute(stmt).scalar_one_or_none()
            if fav:
                session.delete(fav)
                session.commit()
                return {"status": "removed"}
            return {"status": "not_found"}

    def add_price_alert(self, user_id: str, product_id: int, target_price: int) -> dict:
        """가격 알림 설정."""
        with self.SessionLocal() as session:
            alert = PriceAlert(
                user_id=user_id,
                product_id=product_id,
                target_price=target_price,
            )
            session.add(alert)
            session.commit()
            session.refresh(alert)
            return {
                "id": alert.id,
                "product_id": product_id,
                "target_price": target_price,
                "status": "active",
            }

    def get_user_alerts(self, user_id: str) -> list[dict]:
        """사용자 가격 알림 목록."""
        with self.SessionLocal() as session:
            stmt = (
                select(PriceAlert, Product)
                .join(Product, PriceAlert.product_id == Product.id)
                .where(PriceAlert.user_id == user_id, PriceAlert.is_active == True)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    "id": alert.id,
                    "product_id": alert.product_id,
                    "product_name": prod.name,
                    "target_price": alert.target_price,
                    "is_active": alert.is_active,
                    "created_at": alert.created_at.isoformat() if alert.created_at else None,
                }
                for alert, prod in rows
            ]

    # ──────────────────────────────────────────
    # 배치 저장 (크롤러 출력 → DB)
    # ──────────────────────────────────────────

    def _save_discount_items(self, items: list[dict]) -> int:
        """마트 할인 데이터 배치 저장."""
        with self.SessionLocal() as session:
            count = 0
            for item in items:
                product_id = self._resolve_product_id(session, item.get("product_name", ""))
                if not product_id:
                    continue
                record = DiscountHistory(
                    product_id=product_id,
                    store=item.get("store", ""),
                    original_price=item.get("original_price"),
                    sale_price=item.get("sale_price", 0),
                    discount_percent=item.get("discount_percent"),
                    event_name=item.get("event_name", ""),
                    valid_from=item.get("valid_from"),
                    valid_until=item.get("valid_until"),
                    image_url=item.get("image_url", ""),
                )
                session.add(record)
                count += 1
            session.commit()
            return count

    def _save_hotdeal_posts(self, items: list[dict]) -> int:
        """핫딜 게시글 배치 저장 — URL 중복 시 스킵."""
        with self.SessionLocal() as session:
            count = 0
            for item in items:
                url = item.get("url", "")
                existing = session.execute(
                    select(HotdealPost).where(HotdealPost.url == url)
                ).scalar_one_or_none()
                if existing:
                    continue
                post = HotdealPost(
                    title=item.get("title", ""),
                    url=url,
                    source_community=item.get("source_community", ""),
                    price=item.get("price"),
                    original_price=item.get("original_price"),
                    category=item.get("category", ""),
                    views=item.get("views", 0),
                    comments_count=item.get("comments_count", 0),
                    thumbnail_url=item.get("thumbnail_url", ""),
                )
                session.add(post)
                count += 1
            session.commit()
            return count

    def _save_baseline_prices(self, items: list[dict]) -> int:
        """기준 가격 배치 저장."""
        with self.SessionLocal() as session:
            count = 0
            for item in items:
                product_id = self._resolve_product_id(session, item.get("product_name", ""))
                if not product_id:
                    continue
                record = BaselinePrice(
                    product_id=product_id,
                    source=item.get("source", ""),
                    source_type=item.get("source_type", "government"),
                    price=item.get("price", 0),
                    unit=item.get("unit", ""),
                    recorded_date=item.get("recorded_date", datetime.now()),
                )
                session.add(record)
                count += 1
            session.commit()
            return count

    def _save_gas_stations(self, items: list[dict]) -> int:
        """주유소 데이터 배치 저장/갱신."""
        with self.SessionLocal() as session:
            count = 0
            for item in items:
                name = item.get("name", "")
                existing = session.execute(
                    select(GasStation).where(GasStation.name == name)
                ).scalar_one_or_none()
                if existing:
                    existing.gasoline_price = item.get("gasoline_price")
                    existing.diesel_price = item.get("diesel_price")
                    existing.lpg_price = item.get("lpg_price")
                    existing.updated_at = datetime.now()
                else:
                    station = GasStation(
                        name=name,
                        brand=item.get("brand", ""),
                        address=item.get("address", ""),
                        lat=item.get("lat"),
                        lng=item.get("lng"),
                        gasoline_price=item.get("gasoline_price"),
                        diesel_price=item.get("diesel_price"),
                        lpg_price=item.get("lpg_price"),
                    )
                    session.add(station)
                count += 1
            session.commit()
            return count

    # ──────────────────────────────────────────
    # 내부 헬퍼
    # ──────────────────────────────────────────

    def _resolve_product_id(self, session: Session, product_name: str) -> int | None:
        """품목명으로 product_id 조회 — 없으면 None."""
        if not product_name:
            return None
        product = session.execute(
            select(Product).where(Product.name == product_name)
        ).scalar_one_or_none()
        return product.id if product else None

    def _get_product_name(self, session: Session, product_id: int | None) -> str | None:
        """product_id로 품목명 조회."""
        if not product_id:
            return None
        product = session.get(Product, product_id)
        return product.name if product else None

    def _compute_product_stats(self, session: Session, product_id: int) -> dict:
        """
        상품의 가격 통계 계산 — avg, cur(최신), low, high, 레코드 수 등.

        baseline_prices 테이블만 사용하여 왜곡 없는 통계를 보장.
        """
        stats = session.execute(
            select(
                func.avg(BaselinePrice.price).label("avg"),
                func.min(BaselinePrice.price).label("low"),
                func.max(BaselinePrice.price).label("high"),
                func.count(BaselinePrice.id).label("records"),
            ).where(BaselinePrice.product_id == product_id)
        ).one()

        # 최신 가격 (가장 최근 recorded_date의 평균)
        latest = session.execute(
            select(func.avg(BaselinePrice.price))
            .where(BaselinePrice.product_id == product_id)
            .order_by(desc(BaselinePrice.recorded_date))
            .limit(4)  # 최근 4개 소스의 평균
        ).scalar()

        # 할인 통계
        disc_count = session.execute(
            select(func.count(DiscountHistory.id))
            .where(DiscountHistory.product_id == product_id)
        ).scalar() or 0

        disc_avg = session.execute(
            select(func.avg(DiscountHistory.discount_percent))
            .where(DiscountHistory.product_id == product_id)
        ).scalar()

        return {
            "avg": round(stats.avg) if stats.avg else 0,
            "cur": round(latest) if latest else 0,
            "low": stats.low or 0,
            "high": stats.high or 0,
            "records": stats.records or 0,
            "data_days": 180,
            "avg_discount": round(disc_avg, 1) if disc_avg else 0.0,
            "disc_freq": round(disc_count / 26, 1) if disc_count else 0.0,  # ~6개월 기준 주간 빈도
        }

    def _get_store_prices(self, session: Session, product_id: int) -> dict:
        """매장별 최신 가격 조회 — stores: {emart: 2280, homeplus: 2380, ...}."""
        store_key_map = {
            "이마트": "emart",
            "홈플러스": "homeplus",
            "롯데마트": "lotte",
            "코스트코": "costco",
        }

        result = {}
        for store_name, key in store_key_map.items():
            price = session.execute(
                select(BaselinePrice.price)
                .where(
                    BaselinePrice.product_id == product_id,
                    BaselinePrice.source == store_name,
                )
                .order_by(desc(BaselinePrice.recorded_date))
                .limit(1)
            ).scalar()
            if price is not None:
                result[key] = price

        return result

    def _query_discounts(self, limit: int = 100, since: datetime | None = None) -> list[dict]:
        """할인 이력 조회."""
        with self.SessionLocal() as session:
            stmt = select(DiscountHistory).order_by(desc(DiscountHistory.crawled_at))
            if since:
                stmt = stmt.where(DiscountHistory.crawled_at >= since)
            stmt = stmt.limit(limit)
            items = session.execute(stmt).scalars().all()
            return [
                {
                    "store": i.store,
                    "sale_price": i.sale_price,
                    "original_price": i.original_price,
                    "discount_percent": i.discount_percent,
                    "event_name": i.event_name,
                }
                for i in items
            ]

    def _query_hotdeals(self, limit: int = 100, since: datetime | None = None) -> list[dict]:
        """핫딜 조회."""
        with self.SessionLocal() as session:
            stmt = select(HotdealPost).order_by(desc(HotdealPost.crawled_at))
            if since:
                stmt = stmt.where(HotdealPost.crawled_at >= since)
            stmt = stmt.limit(limit)
            posts = session.execute(stmt).scalars().all()
            return [
                {
                    "title": p.title,
                    "url": p.url,
                    "source": p.source_community,
                    "price": p.price,
                    "category": p.category,
                }
                for p in posts
            ]

    def _query_baseline_prices(self, limit: int = 100, since: datetime | None = None) -> list[dict]:
        """기준 가격 조회."""
        with self.SessionLocal() as session:
            stmt = select(BaselinePrice).order_by(desc(BaselinePrice.recorded_date))
            if since:
                stmt = stmt.where(BaselinePrice.recorded_date >= since)
            stmt = stmt.limit(limit)
            prices = session.execute(stmt).scalars().all()
            return [
                {
                    "source": p.source,
                    "price": p.price,
                    "recorded_date": p.recorded_date.isoformat() if p.recorded_date else None,
                }
                for p in prices
            ]

    def _query_gas_stations(self) -> list[dict]:
        """주유소 전체 조회."""
        return self.get_gas_prices()

    @staticmethod
    def _relative_time(dt: datetime | None) -> str:
        """datetime을 "3분 전", "2시간 전" 형태로 변환."""
        if not dt:
            return ""
        diff = datetime.now() - dt
        minutes = int(diff.total_seconds() / 60)
        if minutes < 1:
            return "방금 전"
        if minutes < 60:
            return f"{minutes}분 전"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}시간 전"
        days = hours // 24
        return f"{days}일 전"
