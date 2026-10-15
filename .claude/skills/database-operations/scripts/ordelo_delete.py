import argparse
import json

from _bootstrap import execute_with_fallback, parse_key_value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete rows from an Ordelo table using the service-role client (Supabase)."
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
    parser.add_argument("--service", action="store_true", help="Skip the anon client and use the service-role key")
    parser.add_argument(
        "--approved-by",
        default=None,
        help="REQUIRED. Who approved THIS delete and where (e.g. 'Lohith, chat 2026-10-15'). Never invent this.",
    )
    args = parser.parse_args()

    if not args.eq:
        raise SystemExit("Refusing to run delete without at least one --eq filter.")
    if not args.approved_by:
        raise SystemExit(
            "Refusing to delete: no human approval recorded. Ask the user to approve this exact delete, "
            "then pass --approved-by '<who/when>'."
        )
    if not args.confirm:
        raise SystemExit("Dry-run: add --confirm to execute the delete.")

    def run(c):
        q = c.table(args.table).delete()
        for col, value in parse_key_value(args.eq):
            q = q.eq(col, value)
        return q.execute()

    print(f"[db-ops] DELETE on {args.table} where {args.eq}; approved by: {args.approved_by}", file=__import__("sys").stderr)
    res = execute_with_fallback(run, args.schema, service=args.service)
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
