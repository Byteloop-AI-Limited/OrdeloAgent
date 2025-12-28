import argparse
import json

from _bootstrap import ensure_repo_on_path, load_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Insert rows into an Ordelo table using pg_settings.client (Supabase)."
    )
    parser.add_argument("--schema", default=None, help="Optional schema (default: public)")
    parser.add_argument("--table", required=True, help="Table name (PostgREST exposed)")
    parser.add_argument("--json", default=None, help="JSON object or JSON array of objects")
    parser.add_argument("--json-file", default=None, help="Path to JSON payload file")
    args = parser.parse_args()

    payload = load_json(json_str=args.json, json_file=args.json_file)
    ensure_repo_on_path()
    from config import pg_settings  # type: ignore

    client_ordelo = pg_settings.client
    if args.schema:
        client_ordelo = client_ordelo.schema(args.schema)

    res = client_ordelo.table(args.table).insert(payload).execute()
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
