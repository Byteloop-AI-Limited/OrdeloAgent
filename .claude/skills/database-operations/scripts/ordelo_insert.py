import argparse
import json

from _bootstrap import execute_with_fallback, load_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Insert rows into an Ordelo table using the service-role client (Supabase)."
    )
    parser.add_argument("--schema", default=None, help="Optional schema (default: public)")
    parser.add_argument("--table", required=True, help="Table name (PostgREST exposed)")
    parser.add_argument("--json", default=None, help="JSON object or JSON array of objects")
    parser.add_argument("--json-file", default=None, help="Path to JSON payload file")
    parser.add_argument("--service", action="store_true", help="Skip the anon client and use the service-role key")
    args = parser.parse_args()

    payload = load_json(json_str=args.json, json_file=args.json_file)
    res = execute_with_fallback(
        lambda c: c.table(args.table).insert(payload).execute(), args.schema, service=args.service
    )
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
