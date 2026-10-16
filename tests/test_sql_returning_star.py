"""A function that declares RETURNS TABLE (...) and ends an INSERT with `RETURNING *;` stops working the moment someone
adds a column to that table ("structure of query does not match function result type", 42804). init_delivery /
init_takeaway did exactly that when the Ready / adjust migration added columns to delivery_summary and takeaway_summary.
List the columns instead."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "ordelo_datamodels"


def test_no_returns_table_function_returns_star():
    bad = []
    for path in ROOT.rglob("*.sql"):
        if "archive" in path.name or "misc_sql" in path.parts:
            continue
        text = path.read_text()
        if "RETURNS TABLE" in text and re.search(r"^\s*RETURNING\s+\*\s*;", text, re.M):
            bad.append(str(path.relative_to(ROOT)))
    assert not bad, f"RETURNING * inside a RETURNS TABLE function (breaks when the table gains a column): {bad}"
