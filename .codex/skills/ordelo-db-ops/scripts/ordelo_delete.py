import argparse
import json

from _bootstrap import ensure_repo_on_path, parse_key_value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete rows from an Ordelo table using pg_settings.client (Supabase)."
    )
    parser.add_argument("--schema", default=None, help="Optional schema (default: public)")
    parser.add_argument("--table", required=True, help="Table name (PostgREST exposed)")
    parser.add_argument(
        "--eq",
        action="append",
        default=[],
        metavar="COL=VALUE",
        help="Equality filter (repeatable; REQUIRED)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually perform the delete (otherwise exit)",
    )
    args = parser.parse_args()

    if not args.eq:
        raise SystemExit("Refusing to run delete without at least one --eq filter.")
    if not args.confirm:
        raise SystemExit("Dry-run: add --confirm to execute the delete.")

    ensure_repo_on_path()
    from config import pg_settings  # type: ignore

    client_ordelo = pg_settings.client
    if args.schema:
        client_ordelo = client_ordelo.schema(args.schema)

    q = client_ordelo.table(args.table).delete()
    for col, value in parse_key_value(args.eq):
        q = q.eq(col, value)

    res = q.execute()
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
