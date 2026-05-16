from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.local_db_admin_submit_proof import LocalProofArgs, run_local_proof


def _source_rows() -> list[dict]:
    return [
        {
            "name": "친환경 대추방울토마토 600g/팩",
            "store": "이마트",
            "sale_price": 4110,
            "original_price": 5480,
            "discount_percent": 25,
            "unit": "600g",
            "detail_url": "https://emart.example/item/tomato",
            "source": "emart",
            "image_url": "https://emart.example/item/tomato.jpg",
        },
        {
            "name": "농심 신라면 120G*5입",
            "store": "홈플러스",
            "sale_price": 4150,
            "unit": "120g×5",
            "detail_url": "https://homeplus.example/item/ramen",
            "source": "homeplus",
            "image_url": "https://homeplus.example/item/ramen.jpg",
        },
        {
            "name": "source url missing row",
            "store": "롯데마트",
            "sale_price": 1000,
            "source": "lottemart",
            "image_url": "https://lottemart.example/item/missing-url.jpg",
        },
    ]


def test_local_db_admin_submit_proof_publishes_multiple_safe_price_observations(tmp_path: Path) -> None:
    source = tmp_path / "source-artifact.json"
    source.write_text(json.dumps(_source_rows(), ensure_ascii=False), encoding="utf-8")

    artifact = run_local_proof(
        LocalProofArgs(
            input_json=source,
            artifact_dir=tmp_path / "artifacts",
            max_items=3,
            allow_db_admin_submit=True,
            source_name="integration-source",
        )
    )

    assert artifact["accepted"] is True
    assert artifact["source"]["selected_rows"] == 3
    assert artifact["provider"]["provider_calls"] == 0
    assert artifact["db_admin_submit_plan"]["submit_allowed_rows"] == 2
    assert artifact["db_admin_submit_plan"]["held_for_review_count"] == 1
    assert artifact["db_admin_submit_plan"]["held_reason_counts"] == {"missing_source_url": 1}
    result = artifact["db_admin_submit_result"]
    assert result["submitted_to_db_admin"] == 2
    assert result["ai_safe_final_approved"] == 2
    assert result["public_db_verified"] == 2
    assert result["rollback_re_review_supported"] == 2
    assert artifact["local_db"]["counts"]["discount_history"] == 2
    assert all(
        row["ai_safe_final_approve"]["public_db_verification"]["verified"]
        for row in result["results"]
    )


def test_local_db_admin_submit_proof_requires_explicit_submit_flag(tmp_path: Path) -> None:
    source = tmp_path / "source-artifact.json"
    source.write_text(json.dumps(_source_rows()[:1], ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="--allow-db-admin-submit"):
        run_local_proof(
            LocalProofArgs(
                input_json=source,
                artifact_dir=tmp_path / "artifacts",
                allow_db_admin_submit=False,
            )
        )
