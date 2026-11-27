"""Issue or reuse one personal rider link. Distribute the URL privately."""

import argparse
from contextlib import redirect_stdout
from io import StringIO
import asyncio
import sys

from channels.telegram.rider_invites import issue, normalize_phone


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phone", help="One rider phone in international format")
    args = parser.parse_args(argv)
    try:
        phone = normalize_phone(args.phone)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        with redirect_stdout(StringIO()):
            url = asyncio.run(issue(phone))
    except Exception:
        # A PostgREST error can contain transaction data. Print no traceback or request details.
        print("Could not issue the rider invite. Check database access and retry.", file=sys.stderr)
        return 1
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
