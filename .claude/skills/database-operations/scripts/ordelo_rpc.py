import argparse
import json

from _bootstrap import ensure_repo_on_path, load_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Call a Supabase RPC / Postgres function using pg_settings.client (Supabase)."
    )
    parser.add_argument("--schema", default=None, help="Optional schema (default: public)")
    parser.add_argument(
        "--function",
        required=True,
        help="Function name (e.g. dispatch_cancel_before_pickup)",
    )
    parser.add_argument("--json", default=None, help="JSON object for RPC args (default: {})")
    parser.add_argument("--json-file", default=None, help="Path to JSON payload file")
    args = parser.parse_args()

    params = {} if (args.json is None and args.json_file is None) else load_json(
        json_str=args.json, json_file=args.json_file
    )
    if not isinstance(params, dict):
        raise SystemExit("--json/--json-file must be a JSON object for RPC parameters.")

    ensure_repo_on_path()
    from config import pg_settings  # type: ignore

    client_ordelo = pg_settings.client
    if args.schema:
        client_ordelo = client_ordelo.schema(args.schema)

    res = client_ordelo.rpc(args.function, params).execute()
    print(json.dumps(res.data, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
