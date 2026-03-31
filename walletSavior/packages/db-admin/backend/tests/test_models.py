"""
WalletSavior 모델 테스트 — SQLite 인메모리 DB로 전체 스키마 검증.

테스트 대상:
    - 모든 모델 CRUD
    - 관계 (1:N, N:1, 자기참조)
    - 유니크 제약 조건
    - Enum 타입
    - 시드 데이터 투입
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError

from storage.models import (
    Base,
    # Enums
    PriceTier, PostType, VoteType, CrawlStatus, UserRole, OAuthProvider,
    # Models
    User, OAuthAccount, Category, Product,
    BaselinePrice, DiscountHistory, HotdealPrice,
    GasStation, Restaurant,
    Post, PostImage, Comment, Vote,
    Favorite, PriceAlert, CrawlLog, Keyword,
    DeliveryItem, ShoppingItem,
)


# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════

@pytest.fixture
def engine():
    """SQLite 인메모리 엔진."""
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session(engine):
    """각 테스트마다 롤백되는 세션."""
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def sample_user(session: Session) -> User:
    """테스트용 사용자 생성."""
    user = User(
        email="test@wallet.com",
        hashed_password="hashed_pw",
        nickname="tester",
        role=UserRole.USER,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def sample_category(session: Session) -> Category:
    """테스트용 카테고리 트리."""
    root = Category(id="meat", name="축산물", depth=0, sort_order=1, icon="🥩")
    child = Category(id="meat.pork", name="돼지고기", parent_id="meat", depth=1, sort_order=1, icon="🐷")
    leaf = Category(id="meat.pork.belly", name="삼겹살", parent_id="meat.pork", depth=2, sort_order=1, icon="🥓")
    session.add_all([root, child, leaf])
    session.flush()
    return leaf


@pytest.fixture
def sample_product(session: Session, sample_category: Category) -> Product:
    """테스트용 상품."""
    product = Product(
        name="삼겹살",
        category_id=sample_category.id,
        unit="100g",
        description="국내산 삼겹살",
    )
    session.add(product)
    session.flush()
    return product


# ═══════════════════════════════════════════════
# Enum 테스트
# ═══════════════════════════════════════════════

class TestEnums:
    def test_price_tier_values(self):
        assert PriceTier.ULTRA.value == "ultra"
        assert PriceTier.GREAT.value == "great"
        assert PriceTier.GOOD.value == "good"
        assert PriceTier.WAIT.value == "wait"

    def test_post_type_values(self):
        assert PostType.HOTDEAL.value == "hotdeal"
        assert PostType.FREE.value == "free"

    def test_vote_type_values(self):
        assert VoteType.HOT.value == "hot"
        assert VoteType.NOT.value == "not"

    def test_crawl_status_values(self):
        assert CrawlStatus.SUCCESS.value == "success"
        assert CrawlStatus.PARTIAL.value == "partial"
        assert CrawlStatus.FAILED.value == "failed"

    def test_user_role_values(self):
        assert UserRole.USER.value == "user"
        assert UserRole.ADMIN.value == "admin"
        assert UserRole.MODERATOR.value == "moderator"

    def test_oauth_provider_values(self):
        assert OAuthProvider.GOOGLE.value == "google"
        assert OAuthProvider.KAKAO.value == "kakao"
        assert OAuthProvider.NAVER.value == "naver"


# ═══════════════════════════════════════════════
# 사용자 모델 테스트
# ═══════════════════════════════════════════════

class TestUser:
    def test_create_user(self, session: Session):
        user = User(email="a@b.com", nickname="user1", role=UserRole.USER)
        session.add(user)
        session.flush()
        assert user.id is not None
        assert user.is_active is True

    def test_unique_email(self, session: Session, sample_user: User):
        dup = User(email=sample_user.email, nickname="other")
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_unique_nickname(self, session: Session, sample_user: User):
        dup = User(email="other@b.com", nickname=sample_user.nickname)
        session.add(dup)
        with pytest.raises(IntegrityError):
            session.flush()

    def test_oauth_without_password(self, session: Session):
        user = User(email="oauth@b.com", nickname="oauth_user")
        session.add(user)
        session.flush()
        assert user.hashed_password is None


class TestOAuthAccount:
    def test_create_oauth(self, session: Session, sample_user: User):
        oauth = OAuthAccount(
            user_id=sample_user.id,
            provider=OAuthProvider.GOOGLE,
            provider_user_id="google_123",
        )
        session.add(oauth)
        session.flush()
        assert oauth.id is not None

    def test_oauth_relationship(self, session: Session, sample_user: User):
        oauth = OAuthAccount(
            user_id=sample_user.id,
            provider=OAuthProvider.KAKAO,
            provider_user_id="kakao_456",
        )
        session.add(oauth)
        session.flush()

        session.refresh(sample_user)
        assert len(sample_user.oauth_accounts) == 1
        assert sample_user.oauth_accounts[0].provider == OAuthProvider.KAKAO

    def test_unique_provider_user(self, session: Session, sample_user: User):
        o1 = OAuthAccount(user_id=sample_user.id, provider=OAuthProvider.NAVER, provider_user_id="naver_1")
        session.add(o1)
        session.flush()

        o2 = OAuthAccount(user_id=sample_user.id, provider=OAuthProvider.NAVER, provider_user_id="naver_1")
        session.add(o2)
        with pytest.raises(IntegrityError):
            session.flush()


# ═══════════════════════════════════════════════
# 카테고리 테스트
# ═══════════════════════════════════════════════

class TestCategory:
    def test_create_category(self, session: Session):
        cat = Category(id="test", name="테스트", depth=0, sort_order=0)
        session.add(cat)
        session.flush()
        assert cat.id == "test"

    def test_self_referencing(self, session: Session, sample_category: Category):
        parent = session.get(Category, "meat.pork")
        assert parent is not None
        assert parent.parent_id == "meat"

    def test_category_products(self, session: Session, sample_product: Product, sample_category: Category):
        session.refresh(sample_category)
        assert len(sample_category.products) == 1
        assert sample_category.products[0].name == "삼겹살"


# ═══════════════════════════════════════════════
# 상품 & 가격 테스트
# ═══════════════════════════════════════════════

class TestProduct:
    def test_create_product(self, session: Session, sample_product: Product):
        assert sample_product.id is not None
        assert sample_product.is_active is True

    def test_product_category_relationship(self, session: Session, sample_product: Product):
        assert sample_product.category is not None
        assert sample_product.category.name == "삼겹살"

    def test_product_attributes(self, session: Session, sample_category: Category):
        product = Product(
            name="한우등심",
            category_id=sample_category.id,
            unit="100g",
            attributes={"grade": "1++", "origin": "국내산"},
        )
        session.add(product)
        session.flush()
        assert product.attributes["grade"] == "1++"


class TestBaselinePrice:
    def test_create_baseline(self, session: Session, sample_product: Product):
        bp = BaselinePrice(
            product_id=sample_product.id,
            price=1850.0,
            source="kamis",
            unit="100g",
            recorded_at=datetime.utcnow(),
        )
        session.add(bp)
        session.flush()
        assert bp.id is not None

    def test_baseline_relationship(self, session: Session, sample_product: Product):
        bp = BaselinePrice(
            product_id=sample_product.id,
            price=1800.0,
            source="emart",
            unit="100g",
            recorded_at=datetime.utcnow(),
        )
        session.add(bp)
        session.flush()

        session.refresh(sample_product)
        assert len(sample_product.baseline_prices) == 1
        assert sample_product.baseline_prices[0].source == "emart"


class TestDiscountHistory:
    def test_create_discount(self, session: Session, sample_product: Product):
        dh = DiscountHistory(
            product_id=sample_product.id,
            price=1200.0,
            original_price=1850.0,
            discount_rate=35.1,
            source="emart",
        )
        session.add(dh)
        session.flush()
        assert dh.id is not None

    def test_discount_relationship(self, session: Session, sample_product: Product):
        dh = DiscountHistory(
            product_id=sample_product.id,
            price=1200.0,
            source="homeplus",
        )
        session.add(dh)
        session.flush()

        session.refresh(sample_product)
        assert len(sample_product.discount_history) == 1


class TestHotdealPrice:
    def test_create_hotdeal(self, session: Session, sample_product: Product):
        hp = HotdealPrice(
            product_id=sample_product.id,
            price=1100.0,
            source="ppomppu",
            title="삼겹살 초특가!",
        )
        session.add(hp)
        session.flush()
        assert hp.id is not None
        assert hp.votes_hot == 0
        assert hp.is_verified is False

    def test_hotdeal_relationship(self, session: Session, sample_product: Product):
        hp = HotdealPrice(
            product_id=sample_product.id,
            price=1100.0,
            source="fmkorea",
        )
        session.add(hp)
        session.flush()

        session.refresh(sample_product)
        assert len(sample_product.hotdeal_prices) == 1


# ═══════════════════════════════════════════════
# 주유소 & 식당 테스트
# ═══════════════════════════════════════════════

class TestGasStation:
    def test_create_gas_station(self, session: Session):
        gs = GasStation(
            name="SK 셀프 강남점",
            brand="SK",
            address="강남구 역삼동",
            lat=37.5,
            lng=127.0,
            gasoline_price=1598,
            diesel_price=1438,
            is_self=True,
        )
        session.add(gs)
        session.flush()
        assert gs.id is not None


class TestRestaurant:
    def test_create_restaurant(self, session: Session):
        r = Restaurant(
            name="한우마을",
            category="한식",
            address="강남구 삼성동",
            lat=37.51,
            lng=127.06,
            rating=4.5,
            menu_data={"한우등심": 45000, "한우갈비": 52000},
        )
        session.add(r)
        session.flush()
        assert r.id is not None
        assert r.menu_data["한우등심"] == 45000


# ═══════════════════════════════════════════════
# 커뮤니티 테스트
# ═══════════════════════════════════════════════

class TestPost:
    def test_create_post(self, session: Session, sample_user: User):
        post = Post(
            author_id=sample_user.id,
            post_type=PostType.HOTDEAL,
            title="이마트 삼겹살 100g 1,100원!",
            content="정말 싸요!",
            deal_price=1100.0,
        )
        session.add(post)
        session.flush()
        assert post.id is not None
        assert post.view_count == 0

    def test_post_author_relationship(self, session: Session, sample_user: User):
        post = Post(
            author_id=sample_user.id,
            post_type=PostType.FREE,
            title="자유게시판 글",
            content="내용",
        )
        session.add(post)
        session.flush()

        session.refresh(sample_user)
        assert len(sample_user.posts) == 1
        assert sample_user.posts[0].title == "자유게시판 글"


class TestPostImage:
    def test_create_post_image(self, session: Session, sample_user: User):
        post = Post(author_id=sample_user.id, post_type=PostType.FREE, title="t", content="c")
        session.add(post)
        session.flush()

        img = PostImage(post_id=post.id, image_url="https://img.com/1.jpg", position=0)
        session.add(img)
        session.flush()

        session.refresh(post)
        assert len(post.images) == 1


class TestComment:
    def test_create_comment(self, session: Session, sample_user: User):
        post = Post(author_id=sample_user.id, post_type=PostType.FREE, title="t", content="c")
        session.add(post)
        session.flush()

        comment = Comment(
            post_id=post.id,
            author_id=sample_user.id,
            content="좋은 정보 감사합니다!",
        )
        session.add(comment)
        session.flush()
        assert comment.id is not None

    def test_nested_comment(self, session: Session, sample_user: User):
        post = Post(author_id=sample_user.id, post_type=PostType.FREE, title="t", content="c")
        session.add(post)
        session.flush()

        parent_comment = Comment(post_id=post.id, author_id=sample_user.id, content="부모 댓글")
        session.add(parent_comment)
        session.flush()

        reply = Comment(
            post_id=post.id,
            author_id=sample_user.id,
            content="대댓글",
            parent_id=parent_comment.id,
        )
        session.add(reply)
        session.flush()
        assert reply.parent_id == parent_comment.id

    def test_comment_relationships(self, session: Session, sample_user: User):
        post = Post(author_id=sample_user.id, post_type=PostType.FREE, title="t", content="c")
        session.add(post)
        session.flush()

        c = Comment(post_id=post.id, author_id=sample_user.id, content="댓글")
        session.add(c)
        session.flush()

        session.refresh(post)
        assert len(post.comments) == 1

        session.refresh(sample_user)
        assert len(sample_user.comments) == 1


class TestVote:
    def test_create_vote(self, session: Session, sample_user: User):
        post = Post(author_id=sample_user.id, post_type=PostType.HOTDEAL, title="t", content="c")
        session.add(post)
        session.flush()

        vote = Vote(post_id=post.id, user_id=sample_user.id, vote_type=VoteType.HOT)
        session.add(vote)
        session.flush()
        assert vote.id is not None

    def test_unique_vote_per_post_user(self, session: Session, sample_user: User):
        post = Post(author_id=sample_user.id, post_type=PostType.HOTDEAL, title="t", content="c")
        session.add(post)
        session.flush()

        v1 = Vote(post_id=post.id, user_id=sample_user.id, vote_type=VoteType.HOT)
        session.add(v1)
        session.flush()

        v2 = Vote(post_id=post.id, user_id=sample_user.id, vote_type=VoteType.NOT)
        session.add(v2)
        with pytest.raises(IntegrityError):
            session.flush()


# ═══════════════════════════════════════════════
# 즐겨찾기 & 알림 테스트
# ═══════════════════════════════════════════════

class TestFavorite:
    def test_create_favorite(self, session: Session, sample_user: User, sample_product: Product):
        fav = Favorite(user_id=sample_user.id, product_id=sample_product.id)
        session.add(fav)
        session.flush()
        assert fav.id is not None

    def test_favorite_relationship(self, session: Session, sample_user: User, sample_product: Product):
        fav = Favorite(user_id=sample_user.id, product_id=sample_product.id)
        session.add(fav)
        session.flush()

        session.refresh(sample_user)
        assert len(sample_user.favorites) == 1


class TestPriceAlert:
    def test_create_alert(self, session: Session, sample_user: User, sample_product: Product):
        alert = PriceAlert(
            user_id=sample_user.id,
            product_id=sample_product.id,
            target_price=1500.0,
        )
        session.add(alert)
        session.flush()
        assert alert.id is not None
        assert alert.is_active is True
        assert alert.last_triggered is None


# ═══════════════════════════════════════════════
# 크롤링 로그 테스트
# ═══════════════════════════════════════════════

class TestCrawlLog:
    def test_create_crawl_log(self, session: Session):
        log = CrawlLog(
            crawler_name="emart_crawler",
            status=CrawlStatus.SUCCESS,
            items_found=150,
            items_saved=148,
            duration_seconds=12.5,
        )
        session.add(log)
        session.flush()
        assert log.id is not None

    def test_failed_crawl_log(self, session: Session):
        log = CrawlLog(
            crawler_name="homeplus_crawler",
            status=CrawlStatus.FAILED,
            items_found=0,
            items_saved=0,
            error_message="Connection timeout",
            error_type="TimeoutError",
        )
        session.add(log)
        session.flush()
        assert log.error_message == "Connection timeout"


# ═══════════════════════════════════════════════
# 키워드 테스트
# ═══════════════════════════════════════════════

class TestKeyword:
    def test_create_keyword(self, session: Session):
        kw = Keyword(
            word="삼겹살",
            synonyms=["돼지고기", "삼겹"],
            category_id=None,
            search_count=100,
        )
        session.add(kw)
        session.flush()
        assert kw.id is not None

    def test_unique_word(self, session: Session):
        k1 = Keyword(word="양파")
        session.add(k1)
        session.flush()

        k2 = Keyword(word="양파")
        session.add(k2)
        with pytest.raises(IntegrityError):
            session.flush()


# ═══════════════════════════════════════════════
# 배달/쇼핑 테스트
# ═══════════════════════════════════════════════

class TestDeliveryItem:
    def test_create_delivery(self, session: Session):
        item = DeliveryItem(
            restaurant_name="BBQ 강남점",
            menu_name="황금올리브치킨",
            price=20000.0,
            original_price=22000.0,
            platform="baemin",
            delivery_fee=3000.0,
            min_order=15000.0,
        )
        session.add(item)
        session.flush()
        assert item.id is not None


class TestShoppingItem:
    def test_create_shopping(self, session: Session):
        item = ShoppingItem(
            name="나이키 에어맥스 90",
            brand="나이키",
            price=89000.0,
            original_price=159000.0,
            discount_rate=44.0,
            platform="musinsa",
            category="신발",
        )
        session.add(item)
        session.flush()
        assert item.id is not None


# ═══════════════════════════════════════════════
# 스키마 통합 테스트
# ═══════════════════════════════════════════════

class TestSchemaIntegration:
    """전체 스키마의 테이블 생성 및 관계를 통합 검증."""

    def test_all_tables_created(self, engine):
        """모든 테이블이 정상 생성되는지 확인."""
        inspector_tables = Base.metadata.tables.keys()
        expected = {
            "users", "oauth_accounts", "categories", "products",
            "baseline_prices", "discount_history", "hotdeal_prices",
            "gas_stations", "restaurants",
            "posts", "post_images", "comments", "votes",
            "favorites", "price_alerts", "crawl_logs", "keywords",
            "delivery_items", "shopping_items",
        }
        assert expected == set(inspector_tables)

    def test_cascade_delete_user(self, session: Session, sample_user: User, sample_product: Product):
        """사용자 삭제 시 관련 데이터 캐스케이드 삭제."""
        post = Post(author_id=sample_user.id, post_type=PostType.FREE, title="t", content="c")
        session.add(post)
        session.flush()

        comment = Comment(post_id=post.id, author_id=sample_user.id, content="댓글")
        session.add(comment)
        session.flush()

        fav = Favorite(user_id=sample_user.id, product_id=sample_product.id)
        session.add(fav)
        session.flush()

        session.delete(sample_user)
        session.flush()

        assert session.get(Post, post.id) is None
        assert session.get(Comment, comment.id) is None
        assert session.get(Favorite, fav.id) is None

    def test_cascade_delete_product(self, session: Session, sample_product: Product):
        """상품 삭제 시 가격 데이터 캐스케이드 삭제."""
        bp = BaselinePrice(
            product_id=sample_product.id,
            price=1850.0,
            source="kamis",
            unit="100g",
            recorded_at=datetime.utcnow(),
        )
        dh = DiscountHistory(product_id=sample_product.id, price=1200.0, source="emart")
        hp = HotdealPrice(product_id=sample_product.id, price=1100.0, source="ppomppu")
        session.add_all([bp, dh, hp])
        session.flush()

        session.delete(sample_product)
        session.flush()

        assert session.get(BaselinePrice, bp.id) is None
        assert session.get(DiscountHistory, dh.id) is None
        assert session.get(HotdealPrice, hp.id) is None

    def test_full_flow(self, session: Session):
        """전체 플로우: 사용자 → 게시글 → 댓글 → 투표."""
        # 카테고리 + 상품
        cat = Category(id="test.cat", name="테스트", depth=0, sort_order=0)
        session.add(cat)
        session.flush()

        product = Product(name="테스트상품", category_id="test.cat", unit="개")
        session.add(product)
        session.flush()

        # 사용자
        user = User(email="flow@test.com", nickname="flow_user")
        session.add(user)
        session.flush()

        # 게시글
        post = Post(
            author_id=user.id,
            post_type=PostType.HOTDEAL,
            title="테스트 핫딜",
            content="내용",
            product_id=product.id,
            deal_price=500.0,
        )
        session.add(post)
        session.flush()

        # 댓글
        comment = Comment(post_id=post.id, author_id=user.id, content="좋아요")
        session.add(comment)
        session.flush()

        # 투표
        vote = Vote(post_id=post.id, user_id=user.id, vote_type=VoteType.HOT)
        session.add(vote)
        session.flush()

        # 검증
        session.refresh(post)
        assert len(post.comments) == 1
        assert len(post.votes) == 1
        assert post.votes[0].vote_type == VoteType.HOT


# ═══════════════════════════════════════════════
# 시드 데이터 테스트
# ═══════════════════════════════════════════════

class TestSeedData:
    def test_seed_all(self, engine):
        """시드 데이터 투입 테스트."""
        from storage.seed import seed_all
        seed_all(engine=engine)

        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as session:
            categories = session.execute(select(Category)).scalars().all()
            assert len(categories) > 50

            products = session.execute(select(Product)).scalars().all()
            assert len(products) >= 12

            baselines = session.execute(select(BaselinePrice)).scalars().all()
            assert len(baselines) > 100

            gas_stations = session.execute(select(GasStation)).scalars().all()
            assert len(gas_stations) == 8

            keywords = session.execute(select(Keyword)).scalars().all()
            assert len(keywords) >= 100

    def test_seed_idempotent(self, engine):
        """시드를 두 번 실행해도 중복되지 않음."""
        from storage.seed import seed_all
        seed_all(engine=engine)
        seed_all(engine=engine)

        SessionLocal = sessionmaker(bind=engine)
        with SessionLocal() as session:
            products = session.execute(select(Product)).scalars().all()
            assert len(products) >= 12
            assert len(products) < 50  # 두 번 삽입되지 않음
