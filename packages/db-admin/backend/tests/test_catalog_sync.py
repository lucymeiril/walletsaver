"""Catalog Sync Phase 1 테스트 — export + dry-run validate + log + 라우터.

DB는 in-memory SQLite. db_fingerprint는 alembic_version 테이블이 없으면 None을 쓰지만
export/validate가 같은 세션을 보므로 same_database 판정은 signature 일치로 동작한다.
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.catalog_sync import apply as apply_svc
from services.catalog_sync import export as export_svc
from services.catalog_sync import recategorize as recat_svc
from services.catalog_sync import validate as validate_svc
from storage.models import Base, CatalogSyncLog, Product, ProductMatchRule, UnifiedCategory


def _seed():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session.begin() as s:
        s.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))
        s.add(UnifiedCategory(id="food.rice", parent_id="food", slug="rice", name_ko="쌀/밥", level=1))
        s.add(UnifiedCategory(id="food.snack", parent_id="food", slug="snack", name_ko="과자", level=1))
        s.add(Product(name="CJ 햇반 210g", unit="개", unified_category_id="food.rice",
                      categorization_method="heuristic_leaf"))
        s.add(Product(name="농심 새우깡", unit="개", unified_category_id="food.snack",
                      categorization_method="manual"))
        s.add(Product(name="미분류품", unit="개"))
        s.flush()
        pid = s.execute(select(Product.id).where(Product.name == "CJ 햇반 210g")).scalar_one()
        s.add(ProductMatchRule(pattern_type="normalized", pattern_value="cj 햇반 210g",
                               canonical_category_id="food.rice", canonical_product_id=pid,
                               trust=2, created_by="tester"))
    return engine, Session


def test_export_then_roundtrip_validate_is_unchanged(tmp_path):
    engine, Session = _seed()
    with Session() as s:
        res = export_svc.export_catalog(tmp_path, s, entities=["categories", "match_rules", "products"])
    assert res.counts == {"categories": 3, "match_rules": 1, "products": 3}
    assert res.database_fingerprint["signature"]

    with Session() as s:
        rep = validate_svc.validate_import(s, tmp_path, mode="upsert")
    assert rep.ok is True
    assert rep.same_database is True
    assert rep.diff["categories"].unchanged == 3
    assert rep.diff["match_rules"].unchanged == 1
    assert rep.diff["products"].unchanged == 3


def test_validate_detects_product_update_and_human_protection(tmp_path):
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["products"])

    import json
    pfile = tmp_path / "products.jsonl"
    lines = pfile.read_text(encoding="utf-8").splitlines()
    edited = []
    for line in lines:
        r = json.loads(line)
        if r["categorization_method"] == "heuristic_leaf":
            r["unified_category_id"] = "food.snack"     # 일반 상품 → update
        elif r["categorization_method"] == "manual":
            r["unified_category_id"] = "food.rice"       # 보호 상품 → protected
        edited.append(json.dumps(r, ensure_ascii=False, sort_keys=True))
    pfile.write_text("\n".join(edited) + "\n", encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["products"]["sha256"] = validate_svc._file_sha256(pfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        rep = validate_svc.validate_import(s, tmp_path, mode="upsert", force=False)
    assert rep.diff["products"].update == 1
    assert rep.diff["products"].protected == 1

    with Session() as s:
        rep_f = validate_svc.validate_import(s, tmp_path, mode="upsert", force=True)
    assert rep_f.diff["products"].update == 2
    assert rep_f.diff["products"].protected == 0


def test_validate_flags_missing_product_as_skipped(tmp_path):
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["products"])
    import json
    pfile = tmp_path / "products.jsonl"
    lines = pfile.read_text(encoding="utf-8").splitlines()
    ghost = json.loads(lines[0]); ghost["id"] = 999999
    lines.append(json.dumps(ghost, ensure_ascii=False, sort_keys=True))
    pfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["products"]["sha256"] = validate_svc._file_sha256(pfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        rep = validate_svc.validate_import(s, tmp_path, mode="upsert")
    assert rep.diff["products"].skipped == 1   # 생성 금지 → skipped


def test_router_export_validate_logs(tmp_path, monkeypatch):
    engine, Session = _seed()

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        sess = Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    import api.routes.catalog_sync as routes
    monkeypatch.setattr(routes, "get_session", get_test_session)
    monkeypatch.setattr(routes, "managed_session", managed_test_session)
    monkeypatch.setattr(routes, "ARTIFACT_ROOT", tmp_path / "artifacts")

    from config import settings
    settings.REQUIRE_AUTH = False
    from api.app import create_app
    client = TestClient(create_app())

    # export
    r = client.post("/api/admin/catalog-sync/export",
                    json={"entities": ["categories", "match_rules", "products"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["manifest"]["counts"] == {"categories": 3, "match_rules": 1, "products": 3}
    out_dir = body["out_dir"]

    # validate by uploading the exported files back
    import os
    files = []
    for fn in os.listdir(out_dir):
        files.append(("files", (fn, open(os.path.join(out_dir, fn), "rb"), "application/octet-stream")))
    rv = client.post("/api/admin/catalog-sync/validate", files=files)
    assert rv.status_code == 200, rv.text
    vbody = rv.json()
    assert vbody["ok"] is True
    assert vbody["same_database"] is True

    # logs should record export + validate
    rl = client.get("/api/admin/catalog-sync/logs")
    assert rl.status_code == 200
    ops = [row["operation"] for row in rl.json()["logs"]]
    assert "export" in ops and "validate" in ops


def test_router_export_download_returns_zip(tmp_path, monkeypatch):
    engine, Session = _seed()

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        sess = Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    import api.routes.catalog_sync as routes
    monkeypatch.setattr(routes, "get_session", get_test_session)
    monkeypatch.setattr(routes, "managed_session", managed_test_session)
    monkeypatch.setattr(routes, "ARTIFACT_ROOT", tmp_path / "artifacts")

    from config import settings
    settings.REQUIRE_AUTH = False
    from api.app import create_app
    client = TestClient(create_app())

    r = client.post("/api/admin/catalog-sync/export", json={"entities": ["categories"]})
    assert r.status_code == 200, r.text
    name = r.json()["name"]

    rd = client.get(f"/api/admin/catalog-sync/export/download?name={name}")
    assert rd.status_code == 200, rd.text
    assert rd.headers["content-type"] == "application/zip"

    import io, zipfile
    zf = zipfile.ZipFile(io.BytesIO(rd.content))
    names = set(zf.namelist())
    assert "manifest.json" in names
    assert "categories.jsonl" in names

    # 경로 탈출 방지
    bad = client.get("/api/admin/catalog-sync/export/download?name=../../etc")
    assert bad.status_code == 404


def test_apply_upsert_updates_product_and_creates_category(tmp_path):
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["categories", "products"])

    import json
    # add a brand-new category + flip a non-human product
    cfile = tmp_path / "categories.jsonl"
    clines = cfile.read_text(encoding="utf-8").splitlines()
    clines.append(json.dumps({"id": "food.drink", "parent_id": "food", "slug": "drink",
                              "name_ko": "음료", "level": 1, "sort_order": 9,
                              "source_origin": "import"}, ensure_ascii=False, sort_keys=True))
    cfile.write_text("\n".join(clines) + "\n", encoding="utf-8")

    pfile = tmp_path / "products.jsonl"
    plines = pfile.read_text(encoding="utf-8").splitlines()
    target = None
    for i, l in enumerate(plines):
        r = json.loads(l)
        if r["categorization_method"] == "heuristic_leaf":
            r["unified_category_id"] = "food.drink"
            plines[i] = json.dumps(r, ensure_ascii=False, sort_keys=True)
            target = r["id"]
            break
    pfile.write_text("\n".join(plines) + "\n", encoding="utf-8")

    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["categories"]["sha256"] = validate_svc._file_sha256(cfile)
    man["files"]["products"]["sha256"] = validate_svc._file_sha256(pfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        res = apply_svc.apply_import(s, tmp_path, mode="upsert",
                                     database_url="sqlite://", make_snapshot=False)
    assert res.ok is True
    assert res.counts["categories"]["created"] == 1
    assert res.counts["products"]["updated"] == 1

    with Session() as s:
        assert s.get(UnifiedCategory, "food.drink") is not None
        assert s.get(Product, target).unified_category_id == "food.drink"


def test_apply_refuses_on_validation_error_without_mutation(tmp_path):
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["products"])
    import json
    pfile = tmp_path / "products.jsonl"
    lines = pfile.read_text(encoding="utf-8").splitlines()
    r0 = json.loads(lines[0]); before = r0["unified_category_id"]
    r0["unified_category_id"] = "does.not.exist"     # invalid FK
    lines[0] = json.dumps(r0, ensure_ascii=False, sort_keys=True)
    pfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["products"]["sha256"] = validate_svc._file_sha256(pfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        res = apply_svc.apply_import(s, tmp_path, mode="upsert",
                                     database_url="sqlite://", make_snapshot=False)
    assert res.ok is False
    assert res.counts == {}                          # 아무것도 적용 안 됨
    with Session() as s:                             # DB 그대로
        assert s.get(Product, json.loads(lines[0])["id"]).unified_category_id == before


def test_apply_rejects_invalid_mode(tmp_path):
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["categories"])
    import pytest
    with Session() as s:
        with pytest.raises(ValueError):
            apply_svc.apply_import(s, tmp_path, mode="nonsense",
                                   database_url="sqlite://", make_snapshot=False)


def test_replace_all_rejects_products(tmp_path):
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["products"])
    with Session() as s:
        res = apply_svc.apply_import(s, tmp_path, mode="replace_all",
                                     database_url="sqlite://", make_snapshot=False)
    assert res.ok is False
    assert "products" in (res.error_message or "")
    assert res.counts == {}


def test_append_only_skips_existing_update(tmp_path):
    import json
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["match_rules"])
    rfile = tmp_path / "match_rules.jsonl"
    lines = rfile.read_text(encoding="utf-8").splitlines()
    r = json.loads(lines[0]); r["canonical_category_id"] = "food.snack"   # existing → update
    lines[0] = json.dumps(r, ensure_ascii=False, sort_keys=True)
    lines.append(json.dumps({"pattern_type": "exact", "pattern_value": "신규규칙",
                             "canonical_category_id": "food.snack", "trust": 1},
                            ensure_ascii=False, sort_keys=True))   # brand new → create
    rfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["match_rules"]["sha256"] = validate_svc._file_sha256(rfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        res = apply_svc.apply_import(s, tmp_path, mode="append_only",
                                     database_url="sqlite://", make_snapshot=False)
    assert res.ok is True
    assert res.counts["match_rules"]["created"] == 1
    assert res.counts["match_rules"]["updated"] == 0
    assert res.counts["match_rules"]["skipped_mode"] == 1


def test_patch_skips_new_rows(tmp_path):
    import json
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["match_rules"])
    rfile = tmp_path / "match_rules.jsonl"
    lines = rfile.read_text(encoding="utf-8").splitlines()
    lines.append(json.dumps({"pattern_type": "exact", "pattern_value": "신규규칙",
                             "canonical_category_id": "food.snack", "trust": 1},
                            ensure_ascii=False, sort_keys=True))
    rfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["match_rules"]["sha256"] = validate_svc._file_sha256(rfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        res = apply_svc.apply_import(s, tmp_path, mode="patch",
                                     database_url="sqlite://", make_snapshot=False)
    assert res.ok is True
    assert res.counts["match_rules"]["created"] == 0
    assert res.counts["match_rules"]["skipped_mode"] == 1


def test_replace_all_deletes_missing_match_rules(tmp_path):
    import json
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["match_rules"])
    # 파일을 새 규칙 하나만 담도록 바꿔 기존 규칙은 삭제 대상으로 만든다
    rfile = tmp_path / "match_rules.jsonl"
    only = json.dumps({"pattern_type": "exact", "pattern_value": "오직이것",
                       "canonical_category_id": "food.snack", "trust": 1},
                      ensure_ascii=False, sort_keys=True)
    rfile.write_text(only + "\n", encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["match_rules"]["sha256"] = validate_svc._file_sha256(rfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        res = apply_svc.apply_import(s, tmp_path, mode="replace_all",
                                     database_url="sqlite://", make_snapshot=False)
    assert res.ok is True
    assert res.counts["match_rules"]["created"] == 1
    assert res.counts["match_rules"]["deleted"] == 1
    with Session() as s:
        remaining = {(r.pattern_type, r.pattern_value)
                     for r in s.scalars(select(ProductMatchRule)).all()}
    assert remaining == {("exact", "오직이것")}


def test_replace_all_categories_blocked_when_referenced(tmp_path):
    import json
    engine, Session = _seed()
    with Session() as s:
        export_svc.export_catalog(tmp_path, s, entities=["categories"])
    # food.snack 을 파일에서 제거 → 삭제 대상. 그런데 '농심 새우깡'이 참조 중 → 차단
    cfile = tmp_path / "categories.jsonl"
    kept = [l for l in cfile.read_text(encoding="utf-8").splitlines()
            if json.loads(l)["id"] != "food.snack"]
    cfile.write_text("\n".join(kept) + "\n", encoding="utf-8")
    man = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["categories"]["sha256"] = validate_svc._file_sha256(cfile)
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    with Session() as s:
        res = apply_svc.apply_import(s, tmp_path, mode="replace_all",
                                     database_url="sqlite://", make_snapshot=False)
    assert res.ok is False
    assert "차단" in (res.error_message or "")
    with Session() as s:  # 아무것도 삭제되지 않음
        assert s.get(UnifiedCategory, "food.snack") is not None


def test_restore_snapshot_roundtrip(tmp_path, monkeypatch):
    """파일 SQLite에서 백업 생성 → 데이터 변경 → 복원 시 원복되는지 검증."""
    import services.backup as backup_mod
    from pathlib import Path
    from services.base import reset_engine
    import services.base as base_mod

    db_file = tmp_path / "live.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setenv("DATABASE_URL", db_url)
    from config import settings
    monkeypatch.setattr(settings, "DATABASE_URL", db_url)

    reset_engine()
    eng = base_mod.get_engine(db_url)
    Base.metadata.create_all(eng)
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=eng)
    with SessionLocal.begin() as s:
        s.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))

    snap = backup_mod.create_backup(db_url, reason="catalog-sync-apply")

    # 데이터 변경(카테고리 추가)
    reset_engine()
    eng = base_mod.get_engine(db_url)
    SessionLocal = sessionmaker(bind=eng)
    with SessionLocal.begin() as s:
        s.add(UnifiedCategory(id="extra", slug="extra", name_ko="추가", level=0))

    from services.catalog_sync import restore as restore_svc2
    monkeypatch.setattr(restore_svc2, "BACKUP_DIR", tmp_path / "backups")
    info = restore_svc2.restore_snapshot(Path(snap).name, db_url)
    assert info["ok"] is True

    reset_engine()
    eng = base_mod.get_engine(db_url)
    SessionLocal = sessionmaker(bind=eng)
    with SessionLocal() as s:
        assert s.get(UnifiedCategory, "extra") is None      # 변경분 사라짐
        assert s.get(UnifiedCategory, "food") is not None   # 원본 유지
    reset_engine()


def test_restore_rejects_path_traversal(tmp_path, monkeypatch):
    import services.catalog_sync.restore as restore_svc2
    import pytest
    monkeypatch.setattr(restore_svc2, "BACKUP_DIR", tmp_path / "backups")
    (tmp_path / "backups").mkdir()
    with pytest.raises(ValueError):
        restore_svc2.restore_snapshot("../evil.db", f"sqlite:///{(tmp_path/'x.db').as_posix()}")


def test_router_apply_endpoint(tmp_path, monkeypatch):
    engine, Session = _seed()

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        sess = Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    import api.routes.catalog_sync as routes
    monkeypatch.setattr(routes, "get_session", get_test_session)
    monkeypatch.setattr(routes, "managed_session", managed_test_session)
    monkeypatch.setattr(routes, "ARTIFACT_ROOT", tmp_path / "artifacts")
    monkeypatch.setattr(routes.settings, "DATABASE_URL", "sqlite://")
    monkeypatch.setattr(apply_svc, "create_backup", lambda url, reason="": str(tmp_path / "snap.db"))

    from config import settings
    settings.REQUIRE_AUTH = False
    from api.app import create_app
    client = TestClient(create_app())

    out = tmp_path / "exp"
    with Session() as s:
        export_svc.export_catalog(out, s, entities=["products"])
    import os, json
    pfile = out / "products.jsonl"
    lines = pfile.read_text(encoding="utf-8").splitlines()
    for i, l in enumerate(lines):
        r = json.loads(l)
        if r["categorization_method"] == "heuristic_leaf":
            r["unified_category_id"] = "food.snack"
            lines[i] = json.dumps(r, ensure_ascii=False, sort_keys=True)
            break
    pfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["products"]["sha256"] = validate_svc._file_sha256(pfile)
    (out / "manifest.json").write_text(json.dumps(man), encoding="utf-8")

    files = [("files", (fn, open(out / fn, "rb"), "application/octet-stream"))
             for fn in os.listdir(out)]
    ra = client.post("/api/admin/catalog-sync/apply", files=files)
    assert ra.status_code == 200, ra.text
    body = ra.json()
    assert body["ok"] is True
    assert body["counts"]["products"]["updated"] == 1
    assert body["snapshot_path"]
    # apply 로그 기록 확인
    ops = [row["operation"] for row in client.get("/api/admin/catalog-sync/logs").json()["logs"]]
    assert "apply" in ops


def _seed_for_recat():
    """재분류용 시드: 규칙이 상품을 다른 카테고리로 옮기도록 구성."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session.begin() as s:
        s.add(UnifiedCategory(id="food", slug="food", name_ko="식품", level=0))
        s.add(UnifiedCategory(id="food.rice", parent_id="food", slug="rice", name_ko="쌀/밥", level=1))
        s.add(UnifiedCategory(id="food.snack", parent_id="food", slug="snack", name_ko="과자", level=1))
        # A: 규칙이 food.snack로 옮김 (food.rice -> food.snack) → reclassified
        s.add(Product(name="새우깡", unit="개", unified_category_id="food.rice",
                      categorization_method="heuristic_leaf"))
        # B: 미분류 → 규칙이 food.rice (None -> food.rice) → newly_classified
        s.add(Product(name="햇반", unit="개", categorization_method=None))
        # C: human(manual) 상품, 규칙은 food.snack로 옮기려 함 → 보호
        s.add(Product(name="꼬깔콘", unit="개", unified_category_id="food.rice",
                      categorization_method="manual"))
        # D: 규칙 없음 → no_rule_match, 변경 안 됨
        s.add(Product(name="정체불명상품", unit="개", unified_category_id="food.rice",
                      categorization_method="heuristic_leaf"))
        s.add_all([
            ProductMatchRule(pattern_type="normalized", pattern_value="새우깡",
                             canonical_category_id="food.snack", trust=2, created_by="t"),
            ProductMatchRule(pattern_type="normalized", pattern_value="햇반",
                             canonical_category_id="food.rice", trust=2, created_by="t"),
            ProductMatchRule(pattern_type="normalized", pattern_value="꼬깔콘",
                             canonical_category_id="food.snack", trust=2, created_by="t"),
        ])
    return engine, Session


def test_recategorize_preview_buckets():
    engine, Session = _seed_for_recat()
    with Session() as s:
        pv = recat_svc.preview_recategorization(s, scope={"mode": "all"}, force=False)
    assert pv.total_considered == 4
    assert pv.reclassified == 1          # 새우깡
    assert pv.newly_classified == 1      # 햇반
    assert pv.protected_skipped == 1     # 꼬깔콘(manual)
    assert pv.no_rule_match == 1         # 정체불명상품
    assert pv.will_change == 2
    # 미리보기는 DB를 바꾸지 않는다
    with Session() as s:
        assert s.execute(select(Product.unified_category_id).where(Product.name == "새우깡")).scalar() == "food.rice"


def test_recategorize_preview_force_unlocks_protected():
    engine, Session = _seed_for_recat()
    with Session() as s:
        pv = recat_svc.preview_recategorization(s, scope={"mode": "all"}, force=True)
    assert pv.protected_skipped == 0
    assert pv.reclassified == 2          # 새우깡 + 꼬깔콘
    assert pv.newly_classified == 1


def test_recategorize_apply_changes_and_protects_and_is_idempotent():
    engine, Session = _seed_for_recat()
    with Session() as s:
        res = recat_svc.apply_recategorization(
            s, scope={"mode": "all"}, force=False,
            database_url="sqlite://", make_snapshot=False)
    assert res.ok is True
    assert res.changed == 2
    assert res.protected_skipped == 1
    with Session() as s:
        assert s.execute(select(Product.unified_category_id).where(Product.name == "새우깡")).scalar() == "food.snack"
        assert s.execute(select(Product.unified_category_id).where(Product.name == "햇반")).scalar() == "food.rice"
        # manual 보호: 변경 안 됨
        assert s.execute(select(Product.unified_category_id).where(Product.name == "꼬깔콘")).scalar() == "food.rice"
        # 적용된 상품 method는 match_rule
        assert s.execute(select(Product.categorization_method).where(Product.name == "새우깡")).scalar() == "match_rule"
    # 재적용 → 변경 0건(멱등)
    with Session() as s:
        res2 = recat_svc.apply_recategorization(
            s, scope={"mode": "all"}, force=False,
            database_url="sqlite://", make_snapshot=False)
    assert res2.changed == 0


def test_router_recategorize_preview_and_apply(tmp_path, monkeypatch):
    engine, Session = _seed_for_recat()

    def get_test_session():
        return Session()

    @contextmanager
    def managed_test_session():
        sess = Session()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    import api.routes.catalog_sync as routes
    monkeypatch.setattr(routes, "get_session", get_test_session)
    monkeypatch.setattr(routes, "managed_session", managed_test_session)
    monkeypatch.setattr(routes.settings, "DATABASE_URL", "sqlite://")
    monkeypatch.setattr(recat_svc, "create_backup", lambda url, reason="": str(tmp_path / "snap.db"))

    from config import settings
    settings.REQUIRE_AUTH = False
    from api.app import create_app
    client = TestClient(create_app())

    rp = client.post("/api/admin/catalog-sync/recategorize/preview", json={"scope": {"mode": "all"}})
    assert rp.status_code == 200, rp.text
    assert rp.json()["will_change"] == 2

    ra = client.post("/api/admin/catalog-sync/recategorize/apply", json={"scope": {"mode": "all"}})
    assert ra.status_code == 200, ra.text
    body = ra.json()
    assert body["ok"] is True and body["changed"] == 2
    assert body["snapshot_path"]
    ops = [row["operation"] for row in client.get("/api/admin/catalog-sync/logs").json()["logs"]]
    assert "recategorize" in ops
