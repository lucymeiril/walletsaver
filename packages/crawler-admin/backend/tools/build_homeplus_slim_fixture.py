"""Build slim homeplus fixture covering BOTH branches:
- 3 rows where dcPrice is populated (sale_price = dcPrice, original_price = salePrice)
- 2 rows where dcPrice is null (sale_price = salePrice, original_price = None)

Source: live capture tests/fixtures/live_probe/homeplus_dc_행사.json
        (mfront keyword=행사, returnStatus:200, 30 rows, 9 dc-populated).
"""
from __future__ import annotations

import json
import pathlib

SRC = pathlib.Path("tests/fixtures/live_probe/homeplus_dc_행사.json")
OUT = pathlib.Path("tests/fixtures/homeplus/sale_listing_5items_dc_mixed.json")
OUT.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    env = json.loads(SRC.read_text(encoding="utf-8"))
    dl = env["data"]["dataList"]
    populated = [r for r in dl if r.get("dcPrice") is not None][:3]
    nulls = [r for r in dl if r.get("dcPrice") is None][:2]
    rows = populated + nulls
    assert len(populated) >= 3 and len(nulls) >= 2

    slim_env = {
        "returnStatus": 200,
        "returnCode": env.get("returnCode", "SUCCESS"),
        "returnMessage": "",
        "data": {"dataList": rows},
    }
    text = json.dumps(slim_env, ensure_ascii=False, indent=2)
    OUT.write_text(text, encoding="utf-8")
    print("wrote", OUT, "bytes=", len(text), "populated=", len(populated), "nulls=", len(nulls))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
