"""Split a SQL file into top-level statements, keeping each statement's leading comment block.

Used by the ordelo_datamodels tooling (format, guide, drift check, standard tests). A statement record is a dict:
``lead`` (comments/blank lines before it), ``text`` (the statement including ``;`` and a same-line trailing comment),
``kind`` (create_table, create_function, cron, insert, ...), ``name`` (object name, lower case) and ``target``
(the table a trigger/index/policy is on, or the object a grant/comment is about). Handles ``--`` and ``/* */``
comments, ``'...'`` strings, ``"..."`` identifiers and ``$tag$`` dollar quotes.
"""
from __future__ import annotations

import re

_DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)?\$")


def split(sql: str) -> tuple[list[dict], str]:
    """Return ``(statements, trailing_text)``; ``trailing_text`` is whatever follows the last ``;``."""
    out: list[dict] = []
    i, n = 0, len(sql)
    buf_start = 0
    stmt_start = None
    while i < n:
        c = sql[i]
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth += 1
                    j += 2
                elif sql.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            i = j
            continue
        if c.isspace():
            i += 1
            continue
        if stmt_start is None:
            stmt_start = i
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'" and j + 1 < n and sql[j + 1] == "'":
                    j += 2
                    continue
                if sql[j] == "'":
                    break
                j += 1
            i = j + 1
            continue
        if c == '"':
            j = sql.find('"', i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == "$":
            m = _DOLLAR.match(sql, i)
            if m:
                tag = m.group(0)
                j = sql.find(tag, m.end())
                i = n if j < 0 else j + len(tag)
                continue
        if c == ";":
            lead = sql[buf_start:stmt_start]
            text = sql[stmt_start : i + 1]
            out.append(classify({"lead": lead, "text": text}))
            i += 1
            m = re.match(r"[ \t]*--[^\n]*", sql[i:])
            if m:
                out[-1]["text"] += m.group(0)
                i += m.end()
            buf_start = i
            stmt_start = None
            continue
        i += 1
    trailing = sql[buf_start:]
    if stmt_start is not None and sql[stmt_start:].strip():
        out.append(classify({"lead": sql[buf_start:stmt_start], "text": sql[stmt_start:]}))
        trailing = ""
    return out, trailing


_ID = r'(?:"?(?:public|cron)"?\.)?"?([A-Za-z_][A-Za-z_0-9\-]*)"?'

_PATTERNS = [
    ("create_table", rf"create\s+(?:unlogged\s+)?table\s+(?:if\s+not\s+exists\s+)?{_ID}"),
    ("create_view", rf"create\s+(?:or\s+replace\s+)?(?:materialized\s+)?view\s+(?:if\s+not\s+exists\s+)?{_ID}"),
    ("create_function", rf"create\s+(?:or\s+replace\s+)?(?:function|procedure)\s+{_ID}"),
    ("create_trigger", rf"create\s+(?:or\s+replace\s+)?(?:constraint\s+)?trigger\s+{_ID}"),
    ("create_index", rf"create\s+(?:unique\s+)?index\s+(?:concurrently\s+)?(?:if\s+not\s+exists\s+)?{_ID}"),
    ("create_policy", rf"create\s+policy\s+{_ID}"),
    ("alter_table", rf"alter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{_ID}"),
    ("alter_function", rf"alter\s+function\s+{_ID}"),
    ("drop_function", rf"drop\s+function\s+(?:if\s+exists\s+)?{_ID}"),
    ("drop_trigger", rf"drop\s+trigger\s+(?:if\s+exists\s+)?{_ID}"),
    ("drop_table", rf"drop\s+table\s+(?:if\s+exists\s+)?{_ID}"),
    ("drop_view", rf"drop\s+view\s+(?:if\s+exists\s+)?{_ID}"),
    ("drop_index", rf"drop\s+index\s+(?:concurrently\s+)?(?:if\s+exists\s+)?{_ID}"),
    ("drop_policy", rf"drop\s+policy\s+(?:if\s+exists\s+)?{_ID}"),
    ("grant", r"grant\s"),
    ("revoke", r"revoke\s"),
    ("comment", rf"comment\s+on\s+\w+\s+{_ID}"),
    ("cron", r"select\s+cron\.(?:schedule|alter_job|unschedule)"),
    ("insert", rf"insert\s+into\s+{_ID}"),
    ("update", rf"update\s+{_ID}"),
    ("delete", rf"delete\s+from\s+{_ID}"),
    ("create_extension", r"create\s+extension"),
    ("create_schema", r"create\s+schema"),
    ("do", r"do\s"),
    ("begin", r"(?:begin|commit|end)\s*;"),
    ("select", r"(?:select|with)\s"),
    ("set", r"set\s"),
]


def classify(rec: dict) -> dict:
    t = rec["text"].lstrip()
    low = t.lower()
    rec["kind"], rec["name"], rec["target"] = "other", None, None
    for kind, pat in _PATTERNS:
        m = re.match(pat, low, re.S)
        if m:
            rec["kind"] = kind
            if m.groups():
                rec["name"] = m.group(1).lower()
            break
    if rec["kind"] in ("create_trigger", "drop_trigger", "create_index", "create_policy", "drop_policy"):
        m = re.search(rf"\son\s+(?:only\s+)?{_ID}", low)
        if m:
            rec["target"] = m.group(1).lower()
    if rec["kind"] in ("grant", "revoke", "comment"):
        m = re.search(r"\bon\s+(?:table|function|view|sequence|column)?\s*" + _ID, low)
        if m:
            rec["target"] = m.group(1).lower()
    return rec


def literals(text: str) -> list[str]:
    """Every single-quoted string literal in order (comments skipped). Formatting must keep them byte for byte."""
    out, i, t = [], 0, text or ""
    n = len(t)
    while i < n:
        if t.startswith("--", i):
            j = t.find("\n", i)
            i = n if j < 0 else j
        elif t.startswith("/*", i):
            j = t.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif t[i] == "'":
            j = i + 1
            while j < n:
                if t[j] == "'" and j + 1 < n and t[j + 1] == "'":
                    j += 2
                    continue
                if t[j] == "'":
                    break
                j += 1
            out.append(t[i : j + 1])
            i = j + 1
        elif t[i] == '"':
            j = t.find('"', i + 1)
            i = n if j < 0 else j + 1
        else:
            i += 1
    return out


def code_signature(text: str) -> str:
    """The code with comments and whitespace removed and keywords case-folded, but string literals kept verbatim."""
    out, i, t = [], 0, text or ""
    n = len(t)
    while i < n:
        if t.startswith("--", i):
            j = t.find("\n", i)
            i = n if j < 0 else j
        elif t.startswith("/*", i):
            j = t.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif t[i] == "'":
            lit = literals(t[i:])[0]
            out.append(lit)
            i += len(lit)
        elif t[i].isspace():
            i += 1
        else:
            out.append(t[i].lower())
            i += 1
    return "".join(out)
