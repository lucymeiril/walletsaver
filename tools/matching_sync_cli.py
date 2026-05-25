#!/usr/bin/env python3
"""matching_sync_cli.py — MatchingEntry DB ↔ 파일 양방향 sync CLI 진단 도구.

Usage:
    py -3 tools\\matching_sync_cli.py export --format yaml --out matching.yaml
    py -3 tools\\matching_sync_cli.py export --format jsonl --out matching.jsonl
    py -3 tools\\matching_sync_cli.py export --format csv --out matching.csv

    py -3 tools\\matching_sync_cli.py import --in matching.yaml --dry-run
    py -3 tools\\matching_sync_cli.py import --in matching.yaml --apply

환경 변수:
    DATABASE_URL — DB 연결 문자열 (기본값: sqlite:///packages/db-admin/backend/walletguardian.db)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# db-admin/backend 디렉터리를 sys.path에 추가 (services, storage 패키지 import용)
_BACKEND = Path(__file__).resolve().parent.parent / "packages" / "db-admin" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.matching_sync import (
    ImportDiff,
    export_to_csv,
    export_to_jsonl,
    export_to_yaml,
    import_from_file,
)


def _get_session():
    """DATABASE_URL 환경 변수 기반으로 SQLAlchemy 세션을 생성한다."""
    default_db = str(_BACKEND / "walletguardian.db")
    db_url = os.getenv("DATABASE_URL", f"sqlite:///{default_db}")
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args)
    return sessionmaker(bind=engine)()


def _print_diff(diff: ImportDiff, dry_run: bool) -> None:
    """ImportDiff를 사람이 읽기 좋은 형태로 출력한다."""
    mode = "[DRY-RUN]" if dry_run else "[APPLY]"
    print(f"\n{mode} Import 결과")
    print(f"  전체 incoming : {diff.total_incoming}")
    print(f"  추가(add)     : {len(diff.to_add)}")
    print(f"  업데이트(upd) : {len(diff.to_update)}")
    print(f"  충돌(conflict): {len(diff.conflicts)}")
    print(f"  변경없음      : {diff.unchanged}")

    if diff.to_add:
        print("\n[추가될 항목]")
        for d in diff.to_add:
            print(f"  + {d['match_key']}")

    if diff.to_update:
        print("\n[업데이트될 항목]")
        for old, new in diff.to_update:
            print(f"  ~ {new['match_key']}  ({old['source']} → {new['source']})")

    if diff.conflicts:
        print("\n[거부된 항목 (충돌 정책)]")
        for existing, incoming, reason in diff.conflicts:
            print(f"  ✗ {incoming['match_key']}")
            print(f"      기존: source={existing['source']}, updated_at={existing.get('updated_at')}")
            print(f"      들어온: source={incoming['source']}, updated_at={incoming.get('updated_at')}")
            print(f"      이유: {reason}")


def cmd_export(args: argparse.Namespace) -> int:
    fmt = args.format.lower()
    out_path = Path(args.out)
    session = _get_session()
    try:
        if fmt == "yaml":
            summary = export_to_yaml(session, out_path)
        elif fmt == "jsonl":
            summary = export_to_jsonl(session, out_path)
        elif fmt == "csv":
            summary = export_to_csv(session, out_path)
        else:
            print(f"오류: 지원하지 않는 format: {fmt!r}. 허용: yaml/jsonl/csv", file=sys.stderr)
            return 1
        print(f"[EXPORT] {summary.count}건 → {summary.path}  (format={summary.format})")
        return 0
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


def cmd_import(args: argparse.Namespace) -> int:
    in_path = Path(getattr(args, "in"))
    dry_run = not args.apply

    if not in_path.exists():
        print(f"오류: 파일을 찾을 수 없습니다: {in_path}", file=sys.stderr)
        return 1

    session = _get_session()
    try:
        diff = import_from_file(session, in_path, dry_run=dry_run)
        _print_diff(diff, dry_run=dry_run)

        if not dry_run and (diff.to_add or diff.to_update):
            session.commit()
            print("\n[APPLY] DB에 변경사항이 커밋되었습니다.")
        elif dry_run:
            print("\n[DRY-RUN] 변경사항이 적용되지 않았습니다. --apply 옵션으로 실제 적용하세요.")

        return 0
    except ValueError as exc:
        print(f"파일 오류: {exc}", file=sys.stderr)
        session.rollback()
        return 1
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        session.rollback()
        return 1
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MatchingEntry DB ↔ 파일 양방향 sync 진단 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # export 서브커맨드
    p_export = sub.add_parser("export", help="DB → 파일 내보내기")
    p_export.add_argument(
        "--format", required=True, choices=["yaml", "jsonl", "csv"],
        help="출력 형식"
    )
    p_export.add_argument("--out", required=True, help="출력 파일 경로")

    # import 서브커맨드
    p_import = sub.add_parser("import", help="파일 → DB 가져오기")
    p_import.add_argument("--in", required=True, dest="in", help="가져올 파일 경로")
    p_import.add_argument(
        "--dry-run", action="store_true", default=True,
        help="dry-run 모드 (기본값; 변경사항 미적용)"
    )
    p_import.add_argument(
        "--apply", action="store_true", default=False,
        help="실제 적용 모드 (--dry-run 무효화)"
    )

    args = parser.parse_args()
    if args.command == "export":
        return cmd_export(args)
    elif args.command == "import":
        return cmd_import(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
