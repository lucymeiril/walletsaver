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

import json
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import create_engine, select, func, desc
from sqlalchemy.orm import Session, sessionmaker

from storage.models import (
    Base, Product, BaselinePrice, DiscountHistory,
    HotdealPrice, GasStation, CrawlLog, Favorite, PriceAlert,
    CrawlStatus, Category, Keyword, PendingCategorization, CategoryCorrection,
)

try:
    from services.auto_categorize import auto_categorize
except ImportError:
    auto_categorize = None

try:
    from core.contracts.storage import StorageContract
except ImportError:
    # 독립 실행 시 계약 없이도 동작
    class StorageContract:  # type: ignore[no-redef]
        pass


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
            try:
                crawl_status = CrawlStatus(status)
            except ValueError:
                crawl_status = CrawlStatus.FAILED
            log = CrawlLog(
                crawler_name=crawler_name,
                status=crawl_status,
                items_found=items_count,
                items_saved=items_count,
                started_at=started_at,
                finished_at=finished_at,
                duration_seconds=(finished_at - started_at).total_seconds(),
                error_message=error_msg,
                raw_log=diagnosis,
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
            return self._save_hotdeal_prices(items)
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
                try:
                    crawl_status = CrawlStatus(status)
                    stmt = stmt.where(CrawlLog.status == crawl_status)
                except ValueError:
                    pass
            if since:
                stmt = stmt.where(CrawlLog.started_at >= since)
            stmt = stmt.limit(limit)

            logs = session.execute(stmt).scalars().all()
            return [
                {
                    "id": log.id,
                    "crawler_name": log.crawler_name,
                    "status": log.status.value if log.status else None,
                    "strategy_used": log.strategy_used,
                    "items_found": log.items_found,
                    "items_saved": log.items_saved,
                    "started_at": log.started_at.isoformat() if log.started_at else None,
                    "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                    "duration_seconds": log.duration_seconds,
                    "error_message": log.error_message,
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
                cat = p.category
                avg = price_stats["avg"]
                cur = price_stats["cur"]
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "icon": cat.icon if cat else "",
                    "cat": cat.name if cat else "",
                    "unit": p.unit,
                    "avg": avg,
                    "cur": cur,
                    "low": price_stats["low"],
                    "high": price_stats["high"],
                    "price_tier": self._compute_price_tier(cur, avg),
                    "img": p.image_url or "",
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
            cat = p.category
            avg = price_stats["avg"]
            cur = price_stats["cur"]
            return {
                "id": p.id,
                "name": p.name,
                "icon": cat.icon if cat else "",
                "cat": cat.name if cat else "",
                "unit": p.unit,
                "avg": avg,
                "cur": cur,
                "low": price_stats["low"],
                "high": price_stats["high"],
                "price_tier": self._compute_price_tier(cur, avg),
                "img": p.image_url or "",
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
        source: str | None = None,
        sort: str = "recent",
        page: int = 1,
        per_page: int = 20,
        limit: int | None = None,
    ) -> list[dict]:
        """
        핫딜 목록 — 프론트엔드 HOTDEALS 배열과 동일 shape.

        shape: {id, title, source, price, origPrice, time, cat, views, comments, thumb}
        """
        with self.SessionLocal() as session:
            stmt = select(HotdealPrice)

            if sort in ("recent", "time"):
                stmt = stmt.order_by(desc(HotdealPrice.crawled_at))
            elif sort in ("popular", "votes"):
                stmt = stmt.order_by(desc(HotdealPrice.votes_hot))
            elif sort == "price_asc":
                stmt = stmt.order_by(HotdealPrice.price.asc())
            elif sort == "discount":
                stmt = stmt.order_by(desc(HotdealPrice.crawled_at))

            if source:
                stmt = stmt.where(HotdealPrice.source == source)

            if limit is not None:
                stmt = stmt.limit(limit)
            else:
                offset = (page - 1) * per_page
                stmt = stmt.offset(offset).limit(per_page)

            prices = session.execute(stmt).scalars().all()

            results = []
            for hp in prices:
                product = session.get(Product, hp.product_id) if hp.product_id else None
                cat_name = ""
                if product and product.category:
                    cat_name = product.category.name
                results.append({
                    "id": hp.id,
                    "title": hp.title or "",
                    "source": hp.source,
                    "price": hp.price,
                    "origPrice": None,
                    "time": self._relative_time(hp.crawled_at),
                    "cat": cat_name,
                    "views": 0,
                    "comments": 0,
                    "thumb": None,
                    "votes_hot": hp.votes_hot,
                    "votes_not": hp.votes_not,
                    "is_verified": hp.is_verified,
                })

            if category and category != "all":
                results = [r for r in results if category in r["cat"]]

            return results

    def get_mart_deals(self, store: str | None = None, limit: int = 50) -> dict:
        """
        마트별 할인 정보 — 프론트엔드 MART_DATA와 동일 shape.
        """
        mart_meta = {
            "emart": {"name": "이마트", "color": "#FFD700"},
            "homeplus": {"name": "홈플러스", "color": "#FF6B35"},
            "lottemart": {"name": "롯데마트", "color": "#E4002B"},
            "costco": {"name": "코스트코", "color": "#E31837"},
        }

        with self.SessionLocal() as session:
            stmt = select(DiscountHistory).order_by(desc(DiscountHistory.crawled_at))
            if store:
                stmt = stmt.where(DiscountHistory.source == store)
            stmt = stmt.limit(limit)

            items = session.execute(stmt).scalars().all()

            grouped: dict[str, list] = {}
            latest_crawled: dict[str, datetime] = {}
            for item in items:
                source = item.source
                if source not in grouped:
                    grouped[source] = []
                raw = item.raw_data or {}
                # product_name 결정: Product 테이블 우선, raw_data 백업
                product_name = self._get_product_name(session, item.product_id) or raw.get("product_name", "")
                grouped[source].append({
                    "name": product_name,
                    "orig": item.original_price,
                    "sale": item.price,
                    "disc": round(item.discount_rate) if item.discount_rate else 0,
                    "source_url": item.source_url or "",
                    "image_url": raw.get("image_url", ""),
                    "event_name": raw.get("event_name", ""),
                    "unit": raw.get("unit", ""),
                    "category": raw.get("category", ""),
                    "crawled_at": item.crawled_at.isoformat() if item.crawled_at else "",
                })
                # 마트별 최신 크롤 시각 추적
                if source not in latest_crawled or (item.crawled_at and item.crawled_at > latest_crawled[source]):
                    latest_crawled[source] = item.crawled_at

            result = {}
            for source_key, deal_items in grouped.items():
                meta = mart_meta.get(source_key, {"name": source_key, "color": "#666"})
                lc = latest_crawled.get(source_key)
                result[source_key] = {
                    "name": meta["name"],
                    "color": meta["color"],
                    "items": deal_items,
                    "last_crawled_at": lc.isoformat() if lc else "",
                }
            return result

    def get_gas_prices(
        self,
        fuel_type: str = "gasoline",
        sort_by: str = "price",
        lat: float | None = None,
        lng: float | None = None,
        radius: int | None = None,
        **kwargs,
    ) -> list[dict]:
        """
        주유소 목록 — 프론트엔드 GAS_STATIONS와 동일 shape.

        shape: {id, name, addr, lat, lng, gasoline, diesel, lpg, brand, distance}
        """
        import math

        def _haversine(lat1, lng1, lat2, lng2):
            R = 6371000
            dlat = math.radians(lat2 - lat1)
            dlng = math.radians(lng2 - lng1)
            a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
            return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        with self.SessionLocal() as session:
            stmt = select(GasStation)

            # 연료 종류별 정렬
            price_col = {
                "gasoline": GasStation.gasoline_price,
                "diesel": GasStation.diesel_price,
                "lpg": GasStation.lpg_price,
            }.get(fuel_type, GasStation.gasoline_price)

            if sort_by in ("price", "price_asc"):
                stmt = stmt.order_by(price_col.asc().nullslast())
            else:
                stmt = stmt.order_by(GasStation.name)

            stations = session.execute(stmt).scalars().all()

            results = []
            for s in stations:
                entry = {
                    "id": s.id,
                    "name": s.name,
                    "addr": s.address,
                    "lat": s.lat,
                    "lng": s.lng,
                    "gasoline": s.gasoline_price,
                    "diesel": s.diesel_price,
                    "lpg": s.lpg_price,
                    "brand": s.brand,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                if lat is not None and lng is not None and s.lat and s.lng:
                    dist = _haversine(lat, lng, s.lat, s.lng)
                    if radius and dist > radius:
                        continue
                    entry["distance"] = round(dist)
                results.append(entry)

            if lat is not None and lng is not None and sort_by == "distance":
                results.sort(key=lambda x: x.get("distance", float("inf")))

            return results

    def get_price_history(self, product_id: int, days: int = 30) -> list[dict]:
        """
        가격 추이 데이터.

        shape: [{date: "MM-DD", price: int}]
        """
        since = datetime.now() - timedelta(days=days)
        with self.SessionLocal() as session:
            stmt = (
                select(
                    func.strftime("%m-%d", BaselinePrice.recorded_at).label("date"),
                    func.avg(BaselinePrice.price).label("price"),
                )
                .where(
                    BaselinePrice.product_id == product_id,
                    BaselinePrice.recorded_at >= since,
                )
                .group_by(func.strftime("%m-%d", BaselinePrice.recorded_at))
                .order_by(BaselinePrice.recorded_at)
            )
            rows = session.execute(stmt).all()
            return [{"date": row.date, "price": round(row.price)} for row in rows]

    def search_products(
        self,
        query: str,
        category: str | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> list[dict]:
        """품목 검색 — 이름/카테고리에 검색어가 포함된 상품 (페이지네이션 지원)."""
        with self.SessionLocal() as session:
            stmt = select(Product).where(Product.is_active == True)
            if query:
                stmt = stmt.where(Product.name.contains(query))
            if category:
                from storage.models import Category
                stmt = stmt.join(Category, Product.category_id == Category.id).where(
                    Category.name.contains(category)
                )
            offset = (page - 1) * per_page
            stmt = stmt.offset(offset).limit(per_page)
            products = session.execute(stmt).scalars().all()
            result = []
            for p in products:
                price_stats = self._compute_product_stats(session, p.id)
                store_prices = self._get_store_prices(session, p.id)
                cat = p.category
                avg = price_stats["avg"]
                cur = price_stats["cur"]
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "icon": cat.icon if cat else "",
                    "cat": cat.name if cat else "",
                    "unit": p.unit,
                    "avg": avg,
                    "cur": cur,
                    "low": price_stats["low"],
                    "high": price_stats["high"],
                    "price_tier": self._compute_price_tier(cur, avg),
                    "img": p.image_url or "",
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

    def get_price_compare(self, product_id: int) -> list[dict]:
        """출처별 가격 비교 — 프론트엔드 price-compare 탭용."""
        with self.SessionLocal() as session:
            p = session.get(Product, product_id)
            if not p:
                return []
            price_stats = self._compute_product_stats(session, p.id)
            store_prices = self._get_store_prices(session, p.id)
            avg = price_stats["avg"]
            compare = []
            for source, price in store_prices.items():
                disc = round((1 - price / avg) * 100, 1) if avg else None
                compare.append({
                    "source": source,
                    "price": price,
                    "original_price": avg,
                    "discount_rate": disc,
                    "url": None,
                })
            compare.sort(key=lambda x: x["price"])
            return compare

    def get_hotdeal_detail(self, hotdeal_id: int) -> dict | None:
        """핫딜 상세."""
        with self.SessionLocal() as session:
            hp = session.get(HotdealPrice, hotdeal_id)
            if not hp:
                return None
            product = session.get(Product, hp.product_id) if hp.product_id else None
            cat_name = ""
            if product and product.category:
                cat_name = product.category.name
            return {
                "id": hp.id,
                "title": hp.title or "",
                "source": hp.source,
                "price": hp.price,
                "origPrice": None,
                "time": self._relative_time(hp.crawled_at),
                "cat": cat_name,
                "views": 0,
                "comments": 0,
                "thumb": None,
                "votes_hot": hp.votes_hot,
                "votes_not": hp.votes_not,
                "is_verified": hp.is_verified,
            }

    # ──────────────────────────────────────────
    # 사용자 기능 — 즐겨찾기 / 알림
    # ──────────────────────────────────────────

    def get_user_favorites(self, user_id: str) -> list[dict]:
        """사용자 즐겨찾기 목록 조회."""
        with self.SessionLocal() as session:
            stmt = (
                select(Favorite, Product)
                .join(Product, Favorite.product_id == Product.id)
                .where(Favorite.user_id == int(user_id) if user_id.isdigit() else False)
            )
            rows = session.execute(stmt).all()
            return [
                {
                    "product_id": fav.product_id,
                    "name": prod.name,
                    "cat": prod.category.name if prod.category else "",
                    "unit": prod.unit,
                    "added_at": fav.created_at.isoformat() if fav.created_at else None,
                }
                for fav, prod in rows
            ]

    def add_user_favorite(self, user_id: str, product_id: int) -> dict:
        """즐겨찾기 추가."""
        with self.SessionLocal() as session:
            fav = Favorite(user_id=int(user_id), product_id=product_id)
            session.add(fav)
            session.commit()
            return {"user_id": user_id, "product_id": product_id, "status": "added"}

    def remove_user_favorite(self, user_id: str, product_id: int) -> dict:
        """즐겨찾기 제거."""
        with self.SessionLocal() as session:
            stmt = select(Favorite).where(
                Favorite.user_id == int(user_id),
                Favorite.product_id == product_id,
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
                user_id=int(user_id),
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
                .where(PriceAlert.user_id == int(user_id), PriceAlert.is_active == True)
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
                    source=item.get("source", item.get("store", "")),
                    original_price=item.get("original_price"),
                    price=item.get("sale_price", item.get("price", 0)),
                    discount_rate=item.get("discount_rate", item.get("discount_percent")),
                    valid_from=item.get("valid_from"),
                    valid_to=item.get("valid_to", item.get("valid_until")),
                    source_url=item.get("source_url", ""),
                    raw_data={
                        "image_url": item.get("image_url", ""),
                        "event_name": item.get("event_name", ""),
                        "unit": item.get("unit", ""),
                        "category": item.get("category", ""),
                    },
                )
                session.add(record)
                count += 1
            session.commit()
            return count

    def _save_hotdeal_prices(self, items: list[dict]) -> int:
        """핫딜 가격 배치 저장."""
        with self.SessionLocal() as session:
            count = 0
            for item in items:
                product_id = self._resolve_product_id(session, item.get("product_name", ""))
                if not product_id:
                    continue
                hp = HotdealPrice(
                    product_id=product_id,
                    price=item.get("price", 0),
                    source=item.get("source", item.get("source_community", "")),
                    source_url=item.get("source_url", item.get("url", "")),
                    title=item.get("title", ""),
                )
                session.add(hp)
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
                    price=item.get("price", 0),
                    unit=item.get("unit", ""),
                    recorded_at=item.get("recorded_at", item.get("recorded_date", datetime.now())),
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

        # 최신 가격 (가장 최근 recorded_at의 평균)
        latest = session.execute(
            select(func.avg(BaselinePrice.price))
            .where(BaselinePrice.product_id == product_id)
            .order_by(desc(BaselinePrice.recorded_at))
            .limit(4)
        ).scalar()

        # 할인 통계
        disc_count = session.execute(
            select(func.count(DiscountHistory.id))
            .where(DiscountHistory.product_id == product_id)
        ).scalar() or 0

        disc_avg = session.execute(
            select(func.avg(DiscountHistory.discount_rate))
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
        store_keys = ["emart", "homeplus", "lottemart", "costco"]

        result = {}
        for key in store_keys:
            price = session.execute(
                select(BaselinePrice.price)
                .where(
                    BaselinePrice.product_id == product_id,
                    BaselinePrice.source == key,
                )
                .order_by(desc(BaselinePrice.recorded_at))
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
                    "source": i.source,
                    "price": i.price,
                    "original_price": i.original_price,
                    "discount_rate": i.discount_rate,
                }
                for i in items
            ]

    def _query_hotdeals(self, limit: int = 100, since: datetime | None = None) -> list[dict]:
        """핫딜 조회."""
        with self.SessionLocal() as session:
            stmt = select(HotdealPrice).order_by(desc(HotdealPrice.crawled_at))
            if since:
                stmt = stmt.where(HotdealPrice.crawled_at >= since)
            stmt = stmt.limit(limit)
            prices = session.execute(stmt).scalars().all()
            return [
                {
                    "title": hp.title,
                    "source": hp.source,
                    "source_url": hp.source_url,
                    "price": hp.price,
                }
                for hp in prices
            ]

    def _query_baseline_prices(self, limit: int = 100, since: datetime | None = None) -> list[dict]:
        """기준 가격 조회."""
        with self.SessionLocal() as session:
            stmt = select(BaselinePrice).order_by(desc(BaselinePrice.recorded_at))
            if since:
                stmt = stmt.where(BaselinePrice.recorded_at >= since)
            stmt = stmt.limit(limit)
            prices = session.execute(stmt).scalars().all()
            return [
                {
                    "source": p.source,
                    "price": p.price,
                    "recorded_at": p.recorded_at.isoformat() if p.recorded_at else None,
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

    @staticmethod
    def _compute_price_tier(cur: float, avg: float) -> str:
        """현재가와 평균가를 비교해 가격 등급을 반환."""
        if not avg or avg == 0:
            return "good"
        ratio = cur / avg
        if ratio >= 1.0:
            return "wait"
        if ratio >= 0.85:
            return "good"
        if ratio >= 0.7:
            return "great"
        return "ultra"

    # ──────────────────────────────────────────
    # 키워드 자동완성 / 인기검색어
    # ──────────────────────────────────────────

    def _build_category_path(self, session: Session, category_id: str | None) -> str:
        """카테고리 경로를 구성한다. 예: '축산 > 돼지고기 > 삼겹살'"""
        if not category_id:
            return ""
        parts: list[str] = []
        current_id = category_id
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            cat = session.get(Category, current_id)
            if not cat:
                break
            parts.append(cat.name)
            current_id = cat.parent_id
        parts.reverse()
        return " > ".join(parts)

    def search_autocomplete(self, query: str, limit: int = 10) -> dict:
        """4단계 키워드 자동완성 파이프라인.

        Returns {"keywords": [...], "products": [...],
                 "total_keyword_count": N, "total_product_count": N}
        """
        keyword_limit = 3
        product_limit = 5

        with self.SessionLocal() as session:
            found_keyword_ids: set[int] = set()
            keyword_results: list[dict] = []

            def _add_keyword(kw: Keyword, match_type: str, matched_synonym: str = ""):
                if kw.id in found_keyword_ids:
                    return
                found_keyword_ids.add(kw.id)
                cat = session.get(Category, kw.category_id) if kw.category_id else None

                # Determine suggested_action and action_url for keyword
                if kw.category_id:
                    kw_action = "category_page"
                    kw_action_url = f"/price/category/{kw.category_id}"
                else:
                    kw_action = "search_page"
                    kw_action_url = None

                keyword_results.append({
                    "type": "keyword",
                    "match_type": match_type,
                    "id": kw.id,
                    "word": kw.word,
                    "category_id": kw.category_id,
                    "category_name": cat.name if cat else "",
                    "category_path": self._build_category_path(session, kw.category_id),
                    "search_count": kw.search_count or 0,
                    "matched_synonym": matched_synonym,
                    "icon": cat.icon if cat else "",
                    "suggested_action": kw_action,
                    "action_url": kw_action_url,
                })

            # Stage 1: 키워드 직접 매칭 (prefix)
            stage1 = (
                session.execute(
                    select(Keyword)
                    .where(Keyword.is_active == True, Keyword.word.like(f"{query}%"))
                    .order_by(desc(Keyword.search_count))
                )
                .scalars()
                .all()
            )
            for kw in stage1:
                _add_keyword(kw, "keyword_direct")

            # Stage 2: 동의어 매칭
            all_active = (
                session.execute(
                    select(Keyword).where(Keyword.is_active == True)
                )
                .scalars()
                .all()
            )
            for kw in all_active:
                if kw.id in found_keyword_ids:
                    continue
                synonyms_raw = kw.synonyms
                if not synonyms_raw:
                    continue
                # JSON 필드가 문자열로 저장될 수 있음
                if isinstance(synonyms_raw, str):
                    try:
                        synonyms_raw = json.loads(synonyms_raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                if not isinstance(synonyms_raw, list):
                    continue
                for syn in synonyms_raw:
                    if isinstance(syn, str) and syn.startswith(query):
                        _add_keyword(kw, "synonym", matched_synonym=syn)
                        break

            # Stage 3: 카테고리 이름 매칭
            cat_keywords = (
                session.execute(
                    select(Keyword)
                    .join(Category, Keyword.category_id == Category.id)
                    .where(
                        Keyword.is_active == True,
                        Category.name.contains(query),
                    )
                    .order_by(desc(Keyword.search_count))
                )
                .scalars()
                .all()
            )
            for kw in cat_keywords:
                _add_keyword(kw, "category_match")

            total_keyword_count = len(keyword_results)

            # Stage 4: 상품 이름 매칭
            product_stmt = (
                select(Product)
                .where(Product.is_active == True, Product.name.contains(query))
            )
            total_product_count = session.execute(
                select(func.count()).select_from(product_stmt.subquery())
            ).scalar() or 0

            products = (
                session.execute(product_stmt.limit(product_limit))
                .scalars()
                .all()
            )
            product_results: list[dict] = []
            for p in products:
                cat = p.category
                price_stats = self._compute_product_stats(session, p.id)

                # Check has_baseline
                has_baseline = session.execute(
                    select(func.count(BaselinePrice.id))
                    .where(BaselinePrice.product_id == p.id)
                ).scalar() > 0

                # Get current/original price from DiscountHistory if available
                latest_discount = session.execute(
                    select(DiscountHistory)
                    .where(DiscountHistory.product_id == p.id)
                    .order_by(desc(DiscountHistory.crawled_at))
                    .limit(1)
                ).scalar_one_or_none()

                if latest_discount:
                    current_price = latest_discount.price
                    original_price = latest_discount.original_price
                elif has_baseline:
                    current_price = price_stats["cur"]
                    original_price = None
                else:
                    current_price = price_stats["cur"]
                    original_price = None

                # Calculate discount percentage
                discount_pct = None
                if current_price and original_price and original_price > 0:
                    discount_pct = round((1 - current_price / original_price) * 100)

                # Determine source_type
                source_type = getattr(p, "source_type", None) or "unknown"

                # Determine suggested_action
                if source_type == "mart_crawl":
                    suggested_action = "mart_modal"
                elif source_type == "community_deal":
                    suggested_action = "hotdeal_modal"
                elif source_type == "baseline" or has_baseline:
                    suggested_action = "price_page"
                else:
                    suggested_action = "product_modal"

                product_results.append({
                    "type": "product",
                    "match_type": "product_name",
                    "id": p.id,
                    "name": p.name,
                    "category_id": p.category_id,
                    "unit": p.unit,
                    "icon": cat.icon if cat else "",
                    "current_price": current_price,
                    "original_price": original_price,
                    "discount_pct": discount_pct,
                    "source_type": source_type,
                    "has_baseline": has_baseline,
                    "suggested_action": suggested_action,
                })

            return {
                "keywords": keyword_results[:keyword_limit],
                "products": product_results,
                "total_keyword_count": total_keyword_count,
                "total_product_count": total_product_count,
            }

    def get_trending_keywords(self, limit: int = 8) -> list[dict]:
        """실제 search_count 기반 인기 검색어."""
        with self.SessionLocal() as session:
            keywords = (
                session.execute(
                    select(Keyword)
                    .where(Keyword.is_active == True)
                    .order_by(desc(Keyword.search_count))
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            results = []
            for kw in keywords:
                cat = session.get(Category, kw.category_id) if kw.category_id else None
                results.append({
                    "word": kw.word,
                    "search_count": kw.search_count or 0,
                    "category_id": kw.category_id,
                    "icon": cat.icon if cat else "",
                })
            return results

    def increment_keyword_count(self, keyword_id: int) -> None:
        """키워드 검색 횟수 증가."""
        with self.SessionLocal() as session:
            kw = session.get(Keyword, keyword_id)
            if kw:
                kw.search_count = (kw.search_count or 0) + 1
                session.commit()

    # ──────────────────────────────────────────
    # 카테고리 비교 / 자동 분류
    # ──────────────────────────────────────────

    def _get_descendant_category_ids(self, session: Session, category_id: str) -> list[str]:
        """주어진 카테고리와 그 하위 카테고리 ID를 모두 반환."""
        ids = [category_id]
        children = session.execute(
            select(Category.id).where(Category.parent_id == category_id)
        ).scalars().all()
        for child_id in children:
            ids.extend(self._get_descendant_category_ids(session, child_id))
        return ids

    def get_category_comparison(
        self,
        category_id: str,
        filters: dict | None = None,
        sort: str = "price_asc",
        page: int = 1,
        per_page: int = 20,
    ) -> dict:
        """카테고리별 상품 비교 — 정규화 가격, 가격 등급, 필터, 정렬."""
        filters = filters or {}
        with self.SessionLocal() as session:
            # Resolve category + descendants
            cat = session.get(Category, category_id)
            if not cat:
                return {"summary": {}, "products": [], "total": 0, "page": page, "per_page": per_page}

            all_cat_ids = self._get_descendant_category_ids(session, category_id)

            # Base query: products in these categories
            stmt = select(Product).where(
                Product.is_active == True,
                Product.category_id.in_(all_cat_ids),
            )

            # Apply attribute-based filters
            products_raw = session.execute(stmt).scalars().all()

            # Enrich products with price data and apply filters
            enriched = []
            for p in products_raw:
                attrs = p.attributes or {}

                # Filter by storage
                if filters.get("storage") and attrs.get("storage") != filters["storage"]:
                    continue
                # Filter by origin
                if filters.get("origin") and attrs.get("origin") != filters["origin"]:
                    continue
                # Filter by usage
                if filters.get("usage") and attrs.get("usage") != filters["usage"]:
                    continue
                # Filter by source
                source_type = getattr(p, "source_type", None) or "unknown"
                if filters.get("source") and source_type != filters["source"]:
                    continue

                # Latest price (from DiscountHistory or BaselinePrice)
                latest_discount = session.execute(
                    select(DiscountHistory)
                    .where(DiscountHistory.product_id == p.id)
                    .order_by(desc(DiscountHistory.crawled_at))
                    .limit(1)
                ).scalar_one_or_none()

                latest_baseline = session.execute(
                    select(BaselinePrice)
                    .where(BaselinePrice.product_id == p.id)
                    .order_by(desc(BaselinePrice.recorded_at))
                    .limit(1)
                ).scalar_one_or_none()

                if latest_discount:
                    current_price = latest_discount.price
                    original_price = latest_discount.original_price
                    source = latest_discount.source
                elif latest_baseline:
                    current_price = latest_baseline.price
                    original_price = None
                    source = latest_baseline.source
                else:
                    current_price = None
                    original_price = None
                    source = None

                # Normalized price (per 100g)
                weight_g = attrs.get("weight_g") or attrs.get("weight", 0)
                if isinstance(weight_g, str):
                    try:
                        weight_g = float(weight_g)
                    except (ValueError, TypeError):
                        weight_g = 0
                per_100g = round(current_price / weight_g * 100) if current_price and weight_g > 0 else None

                enriched.append({
                    "id": p.id,
                    "name": p.name,
                    "category_id": p.category_id,
                    "source_type": source_type,
                    "source": source,
                    "current_price": current_price,
                    "original_price": original_price,
                    "per_100g": per_100g,
                    "weight_g": weight_g if weight_g else None,
                    "attributes": attrs,
                    "image_url": p.image_url,
                })

            # Compute price tiers
            prices_for_tier = [e["per_100g"] for e in enriched if e["per_100g"] is not None]
            prices_for_tier.sort()
            for item in enriched:
                if item["per_100g"] is not None and len(prices_for_tier) >= 5:
                    # Percentile-based tiers
                    rank = prices_for_tier.index(item["per_100g"])
                    pct = rank / len(prices_for_tier)
                    if pct <= 0.25:
                        item["price_tier"] = "ultra"
                    elif pct <= 0.50:
                        item["price_tier"] = "great"
                    elif pct <= 0.75:
                        item["price_tier"] = "good"
                    else:
                        item["price_tier"] = "wait"
                elif item["per_100g"] is not None and len(prices_for_tier) >= 2:
                    # Range-based tiers
                    low, high = prices_for_tier[0], prices_for_tier[-1]
                    mid = (low + high) / 2
                    if item["per_100g"] <= low + (mid - low) * 0.5:
                        item["price_tier"] = "great"
                    elif item["per_100g"] <= mid:
                        item["price_tier"] = "good"
                    else:
                        item["price_tier"] = "wait"
                else:
                    item["price_tier"] = "good"

            # Sort
            if sort == "price_asc":
                enriched.sort(key=lambda x: x["per_100g"] if x["per_100g"] is not None else float("inf"))
            elif sort == "price_desc":
                enriched.sort(key=lambda x: x["per_100g"] if x["per_100g"] is not None else 0, reverse=True)
            elif sort == "name":
                enriched.sort(key=lambda x: x["name"])

            total = len(enriched)
            start = (page - 1) * per_page
            page_items = enriched[start:start + per_page]

            # Summary
            summary = {
                "category_id": category_id,
                "category_name": cat.name,
                "category_path": self._build_category_path(session, category_id),
                "total_products": total,
                "avg_per_100g": round(sum(prices_for_tier) / len(prices_for_tier)) if prices_for_tier else None,
                "min_per_100g": prices_for_tier[0] if prices_for_tier else None,
                "max_per_100g": prices_for_tier[-1] if prices_for_tier else None,
            }

            return {
                "summary": summary,
                "products": page_items,
                "total": total,
                "page": page,
                "per_page": per_page,
            }

    def categorize_product(self, product_id: int, source: str | None = None) -> None:
        """자동 카테고리 분류 — 실패해도 상품 저장에 영향 없음."""
        if auto_categorize is None:
            return

        try:
            with self.SessionLocal() as session:
                product = session.get(Product, product_id)
                if not product:
                    return

                result = auto_categorize(product.name, source)
                if result is None:
                    return

                confidence = getattr(result, "confidence", 0.0)
                cat_id = getattr(result, "category_id", None)
                candidates = getattr(result, "candidates", [])
                parsed_kw = getattr(result, "parsed_keywords", [])
                parsed_attrs = getattr(result, "attributes", {})

                product.categorization_confidence = confidence

                if confidence >= 0.85:
                    # Auto-assign
                    if cat_id:
                        product.category_id = cat_id
                    product.categorization_method = "auto"
                elif confidence >= 0.50:
                    # Tentative assignment + pending review
                    if cat_id:
                        product.category_id = cat_id
                    product.categorization_method = "suggested"
                    pending = PendingCategorization(
                        product_id=product_id,
                        suggested_category_id=cat_id,
                        confidence=confidence,
                        candidates_json=[{"category_id": c[0], "score": c[1]} for c in candidates[:5]] if candidates else None,
                        parsed_keywords=parsed_kw if parsed_kw else None,
                        parsed_attributes=parsed_attrs if parsed_attrs else None,
                        status="pending",
                    )
                    session.add(pending)
                else:
                    # Low confidence — leave category_id unchanged, create pending
                    product.categorization_method = "suggested"
                    pending = PendingCategorization(
                        product_id=product_id,
                        suggested_category_id=cat_id,
                        confidence=confidence,
                        candidates_json=[{"category_id": c[0], "score": c[1]} for c in candidates[:5]] if candidates else None,
                        parsed_keywords=parsed_kw if parsed_kw else None,
                        parsed_attributes=parsed_attrs if parsed_attrs else None,
                        status="pending",
                    )
                    session.add(pending)

                session.commit()
        except Exception:
            # Categorization failure must NEVER block data storage
            pass
