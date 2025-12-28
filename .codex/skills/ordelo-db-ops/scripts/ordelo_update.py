import argparse
import json

from _bootstrap import ensure_repo_on_path, load_json, parse_key_value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update rows in an Ordelo table using pg_settings.client (Supabase)."
    )
    parser.add_argument("--schema", default=None, help="Optional schema (default: public)")
    parser.add_argument("--table", required=True, help="Table name (PostgREST exposed)")
    parser.add_argument(
        "--set-json",
        default=None,
        help="JSON object with columns to update (e.g. '{\"status\":\"active\"}')",
    )
    parser.add_argument("--set-json-file", default=None, help="Path to JSON payload file")
    parser.add_argument(
        "--eq",
        action="append",
        default=[],
        metavar="COL=VALUE",
        help="Equality filter (repeatable; REQUIRED)",
    )
    args = parser.parse_args()

    if not args.eq:
        raise SystemExit("Refusing to run update without at least one --eq filter.")

    payload = load_json(json_str=args.set_json, json_file=args.set_json_file)
    if not isinstance(payload, dict):
        raise SystemExit("--set-json/--set-json-file must be a JSON object.")

    ensure_repo_on_path()
    from config import pg_settings  # type: ignore

    client_ordelo = pg_settings.client
    if args.schema:
        client_ordelo = client_ordelo.schema(args.schema)

    q = client_ordelo.table(args.table).update(payload)
    for col, value in parse_key_value(args.eq):
        q = q.eq(col, value)

    res = q.execute()
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
