from __future__ import annotations

from sqlalchemy import text

from services.account_database import AccountDatabase
from services.runtime_storage import RuntimeStorage


class _Catalog:
    def product_exists(self, product_id):
        return str(product_id) == "prod-choco"

    def has_normalized_catalog(self):
        return True

    def get_normalized_product_detail(self, product_id):
        if str(product_id) != "prod-choco":
            return None
        return {"id": "prod-choco", "name": "초코에몽", "cur": 4_900}


def _storage(tmp_path):
    accounts = AccountDatabase(tmp_path / "accounts.sqlite")
    accounts.initialize()
    storage = RuntimeStorage.__new__(RuntimeStorage)
    storage.accounts = accounts
    storage.SessionLocal = accounts.SessionLocal
    storage.catalog = _Catalog()
    return storage, accounts


def test_normalized_product_price_alert_is_persistent_idempotent_and_removable(tmp_path):
    storage, accounts = _storage(tmp_path)
    try:
        with storage.SessionLocal() as session:
            session.execute(
                text(
                    "INSERT INTO users (email, nickname, role, is_active, created_at) "
                    "VALUES ('alert@example.test', '알림사용자', 'user', 1, CURRENT_TIMESTAMP)"
                )
            )
            session.commit()
            user_id = session.execute(
                text("SELECT id FROM users WHERE email='alert@example.test'")
            ).scalar_one()

        first = storage.add_price_alert(user_id, "prod-choco", 5_000)
        second = storage.add_price_alert(user_id, "prod-choco", 4_000)
        assert first["id"] == second["id"]

        rows = storage.get_user_alerts(user_id)
        assert len(rows) == 1
        assert rows[0]["product_id"] == "prod-choco"
        assert rows[0]["current_price"] == 4_900
        assert rows[0]["target_price"] == 4_000
        assert rows[0]["is_triggered"] is False

        assert storage.remove_price_alert(user_id, rows[0]["id"])["status"] == "removed"
        assert storage.get_user_alerts(user_id) == []
    finally:
        accounts.close()
