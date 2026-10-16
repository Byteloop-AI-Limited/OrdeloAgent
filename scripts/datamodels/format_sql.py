"""Format the authoritative SQL under ordelo_datamodels/ with pgFormatter, safely.

    python scripts/datamodels/format_sql.py            # rewrite files in place
    python scripts/datamodels/format_sql.py --check    # exit 1 and list files that are not formatted

pgFormatter (``pg_format``, settings in ``ordelo_datamodels/.pg_format.conf``) is run on one statement at a time.
A statement's new text is kept only if the formatter changed nothing but layout and keyword case: every string literal
must be byte-for-byte identical and the code with comments and whitespace removed must be equal
(``sqlsplit.code_signature``). Otherwise the statement keeps its previous text and is reported. pgFormatter has been
seen to break a literal containing ``--`` and ``''``, which is why this guard exists. Formatting repeats until the
output is stable, so ``--check`` and a formatting run always agree.

Files listed in ``ordelo_datamodels/.sqlfluffignore`` (history and ad-hoc scripts) are not touched.
Needs ``pg_format`` on PATH or ``PG_FORMAT=/path/to/pg_format`` (https://github.com/darold/pgFormatter, v5.6).
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sqlsplit import code_signature, literals, split  # noqa: E402

ROOT = Path(__file__).resolve().parents[2] / "ordelo_datamodels"
CONF = ROOT / ".pg_format.conf"


def pg_format_bin() -> str | None:
    return os.environ.get("PG_FORMAT") or shutil.which("pg_format")


def ignored_patterns() -> list[str]:
    pats = []
    for line in (ROOT / ".sqlfluffignore").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(line)
    return pats


def authoritative_files() -> list[Path]:
    pats = ignored_patterns()
    out = []
    for p in sorted(ROOT.rglob("*.sql")):
        rel = p.relative_to(ROOT).as_posix()
        if any(rel.startswith(x) if x.endswith("/") else fnmatch.fnmatch(rel, x) for x in pats):
            continue
        out.append(p)
    return out


def _run(binary: str, text: str) -> str:
    res = subprocess.run([binary, "-c", str(CONF)], input=text, capture_output=True, text=True, check=True)
    return res.stdout


def _safe(binary: str, chunk: str) -> tuple[str, bool]:
    try:
        new = _run(binary, chunk)
    except subprocess.CalledProcessError:
        return chunk, False
    if literals(new) != literals(chunk) or code_signature(new) != code_signature(chunk):
        return chunk, False
    return new, True


def format_text(binary: str, text: str) -> tuple[str, list[int]]:
    """Return the formatted text and the indexes of statements that had to keep their old text."""
    for _ in range(4):
        stmts, tail = split(text)
        parts, refused = [], []
        for i, s in enumerate(stmts):
            lead = s["lead"].strip("\n")
            new, ok = _safe(binary, s["text"])
            if not ok:
                refused.append(i)
            parts.append((lead + "\n" if lead else "") + new.strip("\n"))
        out = "\n\n".join(parts)
        if tail.strip():
            out += "\n\n" + tail.strip("\n")
        out = out.strip("\n") + "\n"
        if out == text:
            return out, refused
        text = out
    return text, refused


def main() -> int:
    check = "--check" in sys.argv
    binary = pg_format_bin()
    if not binary:
        print("pg_format not found: install pgFormatter or set PG_FORMAT", file=sys.stderr)
        return 2
    bad = []
    for p in authoritative_files():
        old = p.read_text(encoding="utf-8")
        new, refused = format_text(binary, old)
        rel = p.relative_to(ROOT).as_posix()
        for i in refused:
            print(f"kept unformatted (formatter would change code or a literal): {rel} statement {i + 1}")
        if new != old:
            bad.append(rel)
            if not check:
                p.write_text(new, encoding="utf-8")
    if check and bad:
        print("not formatted:\n  " + "\n  ".join(bad))
        return 1
    print(f"{'checked' if check else 'formatted'} {len(authoritative_files())} files" + (f", {len(bad)} changed" if not check else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
