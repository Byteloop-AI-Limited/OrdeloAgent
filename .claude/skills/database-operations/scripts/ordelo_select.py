import argparse
import json

from _bootstrap import ensure_repo_on_path, parse_key_value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select rows from an Ordelo table using pg_settings.client (Supabase)."
    )
    parser.add_argument(
        "--schema", default=None, help="Optional schema (default: public)"
    )
    parser.add_argument("--table", required=True, help="Table name (PostgREST exposed)")
    parser.add_argument(
        "--select",
        dest="select_",
        default="*",
        help='Select clause (default: "*"; e.g. "col1,col2")',
    )
    parser.add_argument(
        "--eq",
        action="append",
        default=[],
        metavar="COL=VALUE",
        help="Equality filter (repeatable)",
    )
    parser.add_argument(
        "--like",
        action="append",
        default=[],
        metavar="COL=PATTERN",
        help="LIKE filter (repeatable)",
    )
    parser.add_argument(
        "--ilike",
        action="append",
        default=[],
        metavar="COL=PATTERN",
        help="ILIKE filter (repeatable)",
    )
    parser.add_argument(
        "--in",
        dest="in_",
        action="append",
        default=[],
        metavar="COL=[...]",
        help="IN filter where VALUE is a JSON list (repeatable)",
    )
    parser.add_argument("--limit", type=int, default=50, help="Max rows to return")
    parser.add_argument(
        "--order",
        default=None,
        help='Order by "col" or "col:asc" or "col:desc"',
    )

    args = parser.parse_args()

    ensure_repo_on_path()
    from config import pg_settings  # type: ignore

    client_ordelo = pg_settings.client
    if args.schema:
        client_ordelo = client_ordelo.schema(args.schema)

    q = client_ordelo.table(args.table).select(args.select_)

    for col, value in parse_key_value(args.eq):
        q = q.eq(col, value)
    for col, value in parse_key_value(args.like):
        q = q.like(col, value)
    for col, value in parse_key_value(args.ilike):
        q = q.ilike(col, value)
    for col, value in parse_key_value(args.in_):
        if not isinstance(value, list):
            raise ValueError(f"--in expects JSON list values; got {col}={value!r}")
        q = q.in_(col, value)

    if args.order:
        if ":" in args.order:
            col, direction = args.order.split(":", 1)
            q = q.order(col, desc=(direction.lower() == "desc"))
        else:
            q = q.order(args.order)

    res = q.limit(args.limit).execute()
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
