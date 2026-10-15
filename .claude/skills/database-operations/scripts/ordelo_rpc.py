import argparse
import json

from _bootstrap import execute_with_fallback, load_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Call a Supabase RPC / Postgres function using the service-role client (Supabase)."
    )
    parser.add_argument("--schema", default=None, help="Optional schema (default: public)")
    parser.add_argument(
        "--function",
        required=True,
        help="Function name (e.g. dispatch_cancel_before_pickup)",
    )
    parser.add_argument("--json", default=None, help="JSON object for RPC args (default: {})")
    parser.add_argument("--json-file", default=None, help="Path to JSON payload file")
    parser.add_argument("--service", action="store_true", help="Skip the anon client and use the service-role key")
    args = parser.parse_args()

    params = {} if (args.json is None and args.json_file is None) else load_json(
        json_str=args.json, json_file=args.json_file
    )
    if not isinstance(params, dict):
        raise SystemExit("--json/--json-file must be a JSON object for RPC parameters.")

    res = execute_with_fallback(
        lambda c: c.rpc(args.function, params).execute(), args.schema, service=args.service
    )
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
