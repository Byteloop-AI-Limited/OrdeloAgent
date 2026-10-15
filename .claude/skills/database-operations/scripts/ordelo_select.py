import argparse
import json

from _bootstrap import execute_with_fallback, parse_key_value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Select rows from an Ordelo table using the service-role client (Supabase)."
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

    parser.add_argument("--service", action="store_true", help="Skip the anon client and use the service-role key")
    args = parser.parse_args()

    filters = []
    for col, value in parse_key_value(args.eq):
        filters.append(("eq", col, value))
    for col, value in parse_key_value(args.like):
        filters.append(("like", col, value))
    for col, value in parse_key_value(args.ilike):
        filters.append(("ilike", col, value))
    for col, value in parse_key_value(args.in_):
        if not isinstance(value, list):
            raise ValueError(f"--in expects JSON list values; got {col}={value!r}")
        filters.append(("in_", col, value))

    def run(c):
        q = c.table(args.table).select(args.select_)
        for op, col, value in filters:
            q = getattr(q, op)(col, value)
        if args.order:
            if ":" in args.order:
                col, direction = args.order.split(":", 1)
                q = q.order(col, desc=(direction.lower() == "desc"))
            else:
                q = q.order(args.order)
        return q.limit(args.limit).execute()

    res = execute_with_fallback(run, args.schema, service=args.service)
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
