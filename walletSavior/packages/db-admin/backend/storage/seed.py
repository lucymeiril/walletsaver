"""
시드 데이터 — DB 초기 품목 + 샘플 가격 투입.

왜 존재하는가:
    DB를 초기화한 뒤 빈 테이블만 있으면 API가 빈 배열만 반환한다.
    프론트엔드 mockData.js와 동일한 12개 품목 + 샘플 가격을 넣어서
    DB 연결 직후부터 의미 있는 데이터가 표시되도록 한다.
어디서 쓰이는가:
    python -c "from storage.seed import seed_all; seed_all()"
    또는 main.py의 init-db 명령에서 호출.
"""

import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from storage.models import (
    Base, Product, BaselinePrice, DiscountHistory,
    HotdealPost, GasStation,
)


# ──────────────────────────────────────────────
# 품목 마스터 데이터 (mockData.js와 동일한 12개)
# ──────────────────────────────────────────────

SEED_PRODUCTS = [
    {"name": "양파",    "category": "채소류 > 근채류",   "unit": "1kg",  "icon": "🧅", "avg": 2350,  "stores": {"이마트": 2280, "홈플러스": 2380, "롯데마트": 2490, "코스트코": 2190}},
    {"name": "삼겹살",  "category": "축산물 > 돼지고기", "unit": "100g", "icon": "🥩", "avg": 1850,  "stores": {"이마트": 1680, "홈플러스": 1790, "롯데마트": 1650, "코스트코": 1520}},
    {"name": "계란",    "category": "축산물 > 란류",     "unit": "30구", "icon": "🥚", "avg": 6200,  "stores": {"이마트": 5980, "홈플러스": 6290, "롯데마트": 6100, "코스트코": 5490}},
    {"name": "사과",    "category": "과일류 > 사과",     "unit": "1kg",  "icon": "🍎", "avg": 4800,  "stores": {"이마트": 5100, "홈플러스": 5300, "롯데마트": 5200, "코스트코": 4800}},
    {"name": "우유",    "category": "유제품 > 우유",     "unit": "1L",   "icon": "🥛", "avg": 2650,  "stores": {"이마트": 2590, "홈플러스": 2680, "롯데마트": 2620, "코스트코": 2390}},
    {"name": "쌀",      "category": "곡류 > 쌀",        "unit": "10kg", "icon": "🍚", "avg": 28500, "stores": {"이마트": 27900, "홈플러스": 28200, "롯데마트": 28500, "코스트코": 26500}},
    {"name": "배추",    "category": "채소류 > 엽경채류", "unit": "1포기", "icon": "🥬", "avg": 3200, "stores": {"이마트": 2800, "홈플러스": 2950, "롯데마트": 2900, "코스트코": 2600}},
    {"name": "감자",    "category": "채소류 > 근채류",   "unit": "1kg",  "icon": "🥔", "avg": 2800,  "stores": {"이마트": 3100, "홈플러스": 2900, "롯데마트": 3050, "코스트코": 2700}},
    {"name": "닭가슴살", "category": "축산물 > 닭고기",  "unit": "1kg",  "icon": "🍗", "avg": 8500,  "stores": {"이마트": 7900, "홈플러스": 8200, "롯데마트": 8000, "코스트코": 7200}},
    {"name": "두부",    "category": "가공식품 > 두부",   "unit": "1모",  "icon": "🧊", "avg": 1800,  "stores": {"이마트": 1650, "홈플러스": 1700, "롯데마트": 1650, "코스트코": 1500}},
    {"name": "식용유",  "category": "조미료 > 유지류",   "unit": "1.8L", "icon": "🫒", "avg": 5800,  "stores": {"이마트": 5500, "홈플러스": 5700, "롯데마트": 5600, "코스트코": 4900}},
    {"name": "라면",    "category": "가공식품 > 면류",   "unit": "5입",  "icon": "🍜", "avg": 3900,  "stores": {"이마트": 3500, "홈플러스": 3600, "롯데마트": 3450, "코스트코": 3200}},
]

# 주유소 데이터
SEED_GAS_STATIONS = [
    {"name": "현대 셀프 강남점",    "brand": "현대",  "address": "강남구 역삼동 123",  "gasoline": 1598, "diesel": 1438, "lpg": 989},
    {"name": "SK 에너지 서초점",    "brand": "SK",    "address": "서초구 서초동 456",  "gasoline": 1612, "diesel": 1452, "lpg": 995},
    {"name": "GS 셀프 잠실점",      "brand": "GS",    "address": "송파구 잠실동 789",  "gasoline": 1605, "diesel": 1445, "lpg": 992},
    {"name": "S-OIL 방배점",        "brand": "S-OIL", "address": "서초구 방배동 234",  "gasoline": 1625, "diesel": 1468, "lpg": 1002},
    {"name": "알뜰 셀프 대치점",    "brand": "알뜰",  "address": "강남구 대치동 567",  "gasoline": 1578, "diesel": 1418, "lpg": 975},
    {"name": "현대 오일뱅크 삼성점", "brand": "현대",  "address": "강남구 삼성동 890",  "gasoline": 1632, "diesel": 1472, "lpg": None},
    {"name": "SK 셀프 논현점",       "brand": "SK",    "address": "강남구 논현동 345",  "gasoline": 1589, "diesel": 1429, "lpg": 985},
    {"name": "알뜰 주유소 개포점",   "brand": "알뜰",  "address": "강남구 개포동 211",  "gasoline": 1570, "diesel": 1410, "lpg": 970},
]


def seed_all(engine=None, database_url: str | None = None) -> None:
    """전체 시드 데이터 투입 — DB 초기화 후 호출."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    if engine is None:
        import os
        url = database_url or os.getenv("DATABASE_URL", "sqlite:///walletguardian.db")
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        engine = create_engine(url, echo=False, connect_args=connect_args)

    # 테이블 생성 (없으면)
    Base.metadata.create_all(engine)

    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        # 이미 시드가 있으면 스킵
        existing = session.query(Product).count()
        if existing > 0:
            print(f"이미 {existing}개 품목이 존재합니다. 시드 스킵.")
            return

        print("시드 데이터 투입 시작...")

        # 1. 품목 마스터 등록
        products = _seed_products(session)
        print(f"  품목 {len(products)}개 등록")

        # 2. 매장별 기준 가격 (최근 30일 시뮬레이션)
        price_count = _seed_baseline_prices(session, products)
        print(f"  기준 가격 {price_count}건 등록")

        # 3. 할인 이력 샘플
        disc_count = _seed_discounts(session, products)
        print(f"  할인 이력 {disc_count}건 등록")

        # 4. 핫딜 게시글 샘플
        hotdeal_count = _seed_hotdeals(session, products)
        print(f"  핫딜 {hotdeal_count}건 등록")

        # 5. 주유소
        gas_count = _seed_gas_stations(session)
        print(f"  주유소 {gas_count}개 등록")

        session.commit()
        print("시드 데이터 투입 완료!")


def _seed_products(session: Session) -> list[Product]:
    """품목 마스터 등록."""
    products = []
    for data in SEED_PRODUCTS:
        p = Product(
            name=data["name"],
            category=data["category"],
            unit=data["unit"],
            icon=data["icon"],
        )
        session.add(p)
        session.flush()  # id 할당
        products.append(p)
    return products


def _seed_baseline_prices(session: Session, products: list[Product]) -> int:
    """최근 30일간의 매장별 기준 가격 시뮬레이션."""
    count = 0
    for idx, p in enumerate(products):
        seed_data = SEED_PRODUCTS[idx]
        for store_name, base_price in seed_data["stores"].items():
            for day_offset in range(30, -1, -1):
                date = datetime.now() - timedelta(days=day_offset)
                # 약간의 변동 추가 (±5%)
                variation = random.uniform(-0.05, 0.05)
                price = round(base_price * (1 + variation))
                record = BaselinePrice(
                    product_id=p.id,
                    source=store_name,
                    source_type="mart_regular",
                    price=price,
                    unit=p.unit,
                    recorded_date=date,
                )
                session.add(record)
                count += 1

        # KAMIS 공식 가격도 추가
        for day_offset in range(30, -1, -1):
            date = datetime.now() - timedelta(days=day_offset)
            variation = random.uniform(-0.03, 0.03)
            price = round(seed_data["avg"] * (1 + variation))
            record = BaselinePrice(
                product_id=p.id,
                source="KAMIS",
                source_type="government",
                price=price,
                unit=p.unit,
                recorded_date=date,
            )
            session.add(record)
            count += 1

    return count


def _seed_discounts(session: Session, products: list[Product]) -> int:
    """할인 이력 샘플 — 각 품목당 2~3건."""
    events = ["주간특가", "1+1", "반값행사", "위크딜", "축산대전", "가공식품 SALE"]
    stores = ["이마트", "홈플러스", "롯데마트", "코스트코"]
    count = 0

    for idx, p in enumerate(products):
        seed_data = SEED_PRODUCTS[idx]
        n_discounts = random.randint(2, 4)
        for _ in range(n_discounts):
            store = random.choice(stores)
            base_price = seed_data["stores"].get(store, seed_data["avg"])
            discount_pct = random.uniform(15, 40)
            sale_price = round(base_price * (1 - discount_pct / 100))
            days_ago = random.randint(1, 60)

            record = DiscountHistory(
                product_id=p.id,
                store=store,
                original_price=base_price,
                sale_price=sale_price,
                discount_percent=round(discount_pct, 1),
                event_name=random.choice(events),
                valid_from=datetime.now() - timedelta(days=days_ago),
                valid_until=datetime.now() - timedelta(days=max(0, days_ago - 7)),
            )
            session.add(record)
            count += 1

    return count


def _seed_hotdeals(session: Session, products: list[Product]) -> int:
    """핫딜 게시글 샘플."""
    communities = ["뽐뿌", "어미새", "루리웹", "에펨코리아"]
    hotdeals = [
        {"title": "이마트 삼겹살 100g 1,100원 시작!", "price": 1100, "orig": 1850, "cat": "food"},
        {"title": "코스트코 양배추 1kg 5,190원", "price": 5190, "orig": 6590, "cat": "food"},
        {"title": "홈플러스 계란 30구 4,980원 역대급", "price": 4980, "orig": 6200, "cat": "food"},
        {"title": "이마트 GAP 양파 1.5kg 2,480원 주간특가", "price": 2480, "orig": 3980, "cat": "food"},
        {"title": "쿠팡 롯데 우유 1L 2,190원 로켓배송", "price": 2190, "orig": 2650, "cat": "food"},
        {"title": "LG 울트라기어 27인치 모니터 297,000원", "price": 297000, "orig": 399000, "cat": "electronics"},
        {"title": "다이슨 에어랩 리퍼 39만원", "price": 390000, "orig": 690000, "cat": "living"},
        {"title": "에어팟 프로 2 USB-C 199,000원", "price": 199000, "orig": 329000, "cat": "electronics"},
    ]

    count = 0
    for i, deal in enumerate(hotdeals):
        hours_ago = random.randint(0, 24)
        post = HotdealPost(
            title=deal["title"],
            url=f"https://example.com/hotdeal/{i + 1}",
            source_community=random.choice(communities),
            price=deal["price"],
            original_price=deal["orig"],
            category=deal["cat"],
            views=random.randint(100, 3000),
            comments_count=random.randint(5, 100),
            crawled_at=datetime.now() - timedelta(hours=hours_ago),
        )
        session.add(post)
        count += 1

    return count


def _seed_gas_stations(session: Session) -> int:
    """주유소 데이터 등록."""
    count = 0
    for data in SEED_GAS_STATIONS:
        station = GasStation(
            name=data["name"],
            brand=data["brand"],
            address=data["address"],
            gasoline_price=data["gasoline"],
            diesel_price=data["diesel"],
            lpg_price=data["lpg"],
        )
        session.add(station)
        count += 1
    return count


if __name__ == "__main__":
    seed_all()
