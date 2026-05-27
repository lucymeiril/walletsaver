"""외부 경량 AI 분류 사이클용 export 서비스."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from services.unmatched_isolation import CASE_RECOMMENDATIONS, isolate_unmatched_products
from storage.models import Keyword, Product, UnifiedCategory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[2]
CATEGORY_TREE_PATH = REPO_ROOT / "packages" / "shared" / "data" / "category_tree.yaml"
PROMPT_PATH = REPO_ROOT / "packages" / "ai-admin" / "backend" / "prompts" / "external_classify_instructions_v1.md"


@dataclass(frozen=True)
class ExportFile:
    """번들 내 단일 파일 메타데이터."""

    name: str
    path: str
    rows: int | None = None
    description: str = ""


@dataclass(frozen=True)
class ExportManifest:
    """외부 AI 분류 export manifest."""

    schema_version: str
    created_at: str
    out_dir: str
    files: dict[str, ExportFile] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    recommendations: dict[str, str] = field(default_factory=dict)
    source_prompt: str = str(PROMPT_PATH)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["files"] = {key: asdict(value) for key, value in self.files.items()}
        return data


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _product_row(product: Product) -> dict[str, Any]:
    attrs = product.attributes if isinstance(product.attributes, dict) else {}
    return {
        "canon_hash": product.canon_hash,
        "mart": product.mart,
        "mart_native_code": product.mart_native_code,
        "raw_name": product.name,
        "normalized_name": product.display_name or product.name_core or product.name,
        "brand": product.brand,
        "pack_qty": product.pack_qty,
        "pack_unit": product.pack_unit or product.unit,
        "pack_count": attrs.get("pack_count"),
        "mart_native_category_id": product.mart_native_category_id,
        "mart_native_category_path": product.mart_native_category_path,
        "canonical_url": product.canonical_url,
    }


def _load_unclassified_rows(session: Session | None) -> list[dict[str, Any]]:
    if session is None:
        return []
    products = session.scalars(
        select(Product)
        .where(Product.unified_category_id.is_(None), Product.canon_hash.is_not(None))
        .order_by(Product.id)
    ).all()
    return [_product_row(product) for product in products]


def _write_category_list(path: Path, session: Session | None) -> int | None:
    if session is None:
        if CATEGORY_TREE_PATH.exists():
            shutil.copyfile(CATEGORY_TREE_PATH, path)
            return None
        path.write_text("nodes: []\n", encoding="utf-8")
        return 0

    categories = session.scalars(select(UnifiedCategory).order_by(UnifiedCategory.level, UnifiedCategory.sort_order, UnifiedCategory.id)).all()
    nodes = [
        {
            "id": category.id,
            "name_kr": category.name_ko,
            "name_en": None,
            "parent_id": category.parent_id,
            "display_order": category.sort_order,
            "default_unit_kind": "EACH",
        }
        for category in categories
    ]
    path.write_text(yaml.safe_dump({"nodes": nodes}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return len(nodes)


def _table_exists(session: Session, table_name: str) -> bool:
    return inspect(session.get_bind()).has_table(table_name)


def _write_keyword_list(path: Path, session: Session | None) -> int:
    if session is None:
        path.write_text(yaml.safe_dump({"keywords": []}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return 0
    if not _table_exists(session, "keywords"):
        path.write_text("# keywords 테이블이 없어 빈 목록을 내보냅니다.\nkeywords: []\n", encoding="utf-8")
        return 0
    keywords = session.scalars(select(Keyword).order_by(Keyword.word)).all()
    rows = [
        {"keyword": kw.word, "category_id": kw.category_id, "synonyms": kw.synonyms or []}
        for kw in keywords
        if kw.is_active
    ]
    path.write_text(yaml.safe_dump({"keywords": rows}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return len(rows)


def _write_instructions(path: Path) -> None:
    header = f"# instructions.md\n\n공용 지침 원본: `{PROMPT_PATH}`\n\n---\n\n"
    if PROMPT_PATH.exists():
        path.write_text(header + PROMPT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        return
    path.write_text(header + "원본 지침 파일을 찾을 수 없습니다.\n", encoding="utf-8")


def export_unclassified_bundle(out_dir: Path, session: Session | None = None) -> ExportManifest:
    """미분류 상품 분류용 번들을 생성한다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    unclassified_path = out_dir / "unclassified.jsonl"
    category_path = out_dir / "category_list.yaml"
    keyword_path = out_dir / "keyword_list.yaml"
    instructions_path = out_dir / "instructions.md"
    manifest_path = out_dir / "manifest.json"

    rows = _load_unclassified_rows(session)
    _write_jsonl(unclassified_path, rows)
    isolation = isolate_unmatched_products(session) if session is not None else None
    case_files: dict[str, ExportFile] = {}
    if isolation is not None:
        for case_key, case in isolation.cases.items():
            case_path = out_dir / f"{case_key}.jsonl"
            _write_jsonl(case_path, case.items)
            case_files[case_key] = ExportFile(
                case_path.name,
                str(case_path),
                rows=case.count,
                description=case.recommendation,
            )
    category_count = _write_category_list(category_path, session)
    keyword_count = _write_keyword_list(keyword_path, session)
    _write_instructions(instructions_path)

    counts = {"unclassified": len(rows), "keywords": keyword_count}
    if isolation is not None:
        counts.update(isolation.counts)
    if category_count is not None:
        counts["categories"] = category_count

    manifest = ExportManifest(
        schema_version="external-ai-classify-v1",
        created_at=datetime.now(timezone.utc).isoformat(),
        out_dir=str(out_dir),
        files={
            "unclassified": ExportFile("unclassified.jsonl", str(unclassified_path), rows=len(rows), description="분류 대상 상품 JSONL"),
            "category_list": ExportFile("category_list.yaml", str(category_path), rows=category_count, description="통합 카테고리 목록"),
            "keyword_list": ExportFile("keyword_list.yaml", str(keyword_path), rows=keyword_count, description="기존 키워드 목록"),
            "instructions": ExportFile("instructions.md", str(instructions_path), description="외부 AI 공용 지침"),
            **case_files,
        },
        counts=counts,
        recommendations=CASE_RECOMMENDATIONS if isolation is not None else {},
    )
    manifest_path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
