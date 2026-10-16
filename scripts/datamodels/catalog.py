"""Read the documented SQL files under ordelo_datamodels/ into one catalogue (dict / catalog.json).

Every authoritative file starts with the standard header (agents.md, "ordelo_datamodels SQL standard"):

    -- =====...
    -- ordelo_datamodels/<folder>/<file>.sql
    -- <one-line title>
    -- =====...
    -- LIVE CHECK    ...          (13 sections, fixed order, value starts at column 17)
    -- OBJECTS       fn     name(args) -> result
    --                   one-line description
    ...
    -- =====...

This module only reads text. It never connects to a database. Used by build_guide.py (guide + catalog.json),
drift_check.py (which objects the repo owns) and tests/test_datamodels_standard.py.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATAMODELS = ROOT / "ordelo_datamodels"

SECTIONS = [
    "LIVE CHECK",
    "OBJECTS",
    "REQUIRES",
    "HOW TO RUN",
    "SIDE EFFECTS",
    "HOW IT FITS",
    "LIFECYCLE",
    "CALLED BY",
    "PYTHON MODEL",
    "SECURITY",
    "TESTS",
    "GOTCHAS",
    "SEE ALSO",
]
KINDS = {"fn": "function", "table": "table", "trg": "trigger", "view": "view", "alter": "alter"}
SKIP_DIRS = {"_archive"}
VALUE_COL = 17  # "-- " + 14-character section name column
RULE = re.compile(r"^-- ={20,}\s*$")
SECTION = re.compile(r"^-- ([A-Z][A-Z ]+?)\s{2,}(.*)$")


def sql_files(root: Path = DATAMODELS) -> list[str]:
    """Every .sql file under ordelo_datamodels/ (relative paths, sorted), except _archive/."""
    out = []
    for p in sorted(root.rglob("*.sql")):
        rel = p.relative_to(root).as_posix()
        if not SKIP_DIRS & set(rel.split("/")[:-1]):
            out.append(rel)
    return out


def role_of(rel: str, text: str) -> str:
    """definition | orphan | migration | script (test harness or ad-hoc query without the standard header)."""
    if rel.startswith("migrations/"):
        return "migration"
    if "\n-- LIVE CHECK " not in text[:4000]:
        return "script"
    if rel.startswith("_orphans/"):
        return "orphan"
    return "definition"


def header_lines(text: str) -> list[str]:
    """The leading comment block (every line up to the first line that is not a `--` comment)."""
    out = []
    for ln in text.split("\n"):
        if not ln.startswith("--"):
            break
        out.append(ln)
    return out


def parse_header(text: str) -> dict:
    """Title, path line and the 13 sections (each a list of raw value lines, indentation kept from column 17)."""
    lines = header_lines(text)
    rules = [i for i, ln in enumerate(lines) if RULE.match(ln)]
    title, path_line = "", ""
    if len(rules) >= 2:
        top = [ln[3:].strip() for ln in lines[rules[0] + 1 : rules[1]]]
        path_line = top[0] if top else ""
        title = " ".join(top[1:]).strip()
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    current = None
    for ln in lines[(rules[1] + 1 if len(rules) >= 2 else 0) :]:
        if RULE.match(ln):
            break
        m = SECTION.match(ln)
        if m and m.group(1) in SECTIONS and len(ln) > VALUE_COL - 1 and ln[3 : VALUE_COL].rstrip() == m.group(1):
            current = m.group(1)
            order.append(current)
            sections[current] = [ln[VALUE_COL:].rstrip()]
        elif current:
            sections[current].append(ln[VALUE_COL:].rstrip() if len(ln) > VALUE_COL else "")
    return {"path_line": path_line, "title": title, "sections": sections, "section_order": order}


def parse_objects(lines: list[str]) -> list[dict]:
    """OBJECTS section -> [{kind, name, signature, description}]."""
    out: list[dict] = []
    for ln in lines:
        m = re.match(r"^(fn|table|trg|view|alter)\s+(\S.*)$", ln)
        if m:
            sig = m.group(2).strip()
            name = re.match(r"[A-Za-z_][A-Za-z0-9_]*", sig).group(0)
            out.append({"kind": KINDS[m.group(1)], "name": name, "signature": sig, "description": ""})
        elif out and ln.strip():
            d = out[-1]["description"]
            out[-1]["description"] = (d + " " + ln.strip()).strip()
    return out


def parse_called_by(lines: list[str]) -> dict[str, list[dict]]:
    """CALLED BY section -> {object: [{via, text}]}; via is cron | sql | trigger | python | r-agents | frontend | ..."""
    out: dict[str, list[dict]] = {}
    current = None
    for ln in lines:
        if not ln.strip() or ln.strip() == "none":
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$", ln)
        if m:
            current = m.group(1)
            out.setdefault(current, [])
            continue
        m = re.match(r"^  (\S+)\s+(\S.*)$", ln)
        if current and m and len(ln) - len(ln.lstrip()) == 2:
            out[current].append({"via": m.group(1), "text": m.group(2).strip()})
        elif current and out[current]:
            out[current][-1]["text"] += " " + ln.strip()
    return out


def paths_in(lines: list[str]) -> list[str]:
    """First token of every non-empty line (REQUIRES / TESTS / SEE ALSO hold one path per line, maybe with a note)."""
    out = []
    for ln in lines:
        s = ln.strip()
        if s and s != "none":
            out.append(s)
    return out


def unquote(lit: str) -> str:
    return lit[1:-1].replace("''", "'")


CRON_CALL = re.compile(r"cron\.schedule\s*\(\s*('(?:[^']|'')*')\s*,\s*('(?:[^']|'')*')\s*,\s*('(?:[^']|'')*')\s*\)", re.S)
CRON_NOTE = re.compile(r"^-- pg_cron job '([^']+)': runs every (.+?), (active|INACTIVE)\b(.*)$")


def parse_cron(rel: str, text: str) -> list[dict]:
    """pg_cron jobs a file schedules (runnable cron.schedule statements; activity from the annotation above each)."""
    notes = {}
    for i, ln in enumerate(text.split("\n"), 1):
        m = CRON_NOTE.match(ln)
        if m:
            notes[m.group(1)] = {"active": m.group(3) == "active", "line": i}
    out = []
    for m in CRON_CALL.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        if text[line_start : m.start()].lstrip().startswith("--"):
            continue  # commented-out example
        name = unquote(m.group(1))
        note = notes.get(name, {})
        out.append(
            {
                "job": name,
                "schedule": unquote(m.group(2)),
                "command": unquote(m.group(3)),
                "active": note.get("active", True),
                "file": rel,
                "line": note.get("line") or text.count("\n", 0, m.start()) + 1,
            }
        )
    return out


def parse_migration(text: str) -> dict:
    lines = header_lines(text)
    info = {"applied": "", "current": [], "purpose": ""}
    key = None
    for ln in lines[1:]:
        body = ln[3:]
        if body.startswith("Applied to live:"):
            key, info["applied"] = "applied", body.split(":", 1)[1].strip()
        elif body.startswith("Current definitions now live in:"):
            key = "current"
            info["current"].append(body.split(":", 1)[1].strip())
        elif body.startswith("Purpose:"):
            key, info["purpose"] = "purpose", body.split(":", 1)[1].strip()
        elif body.startswith("The feature files above"):
            break
        elif key == "current" and body.strip():
            info["current"].append(body.strip())
        elif key in ("applied", "purpose") and body.strip():
            info[key] += " " + body.strip()
    return info


def script_title(text: str) -> str:
    for ln in text.split("\n")[:12]:
        if not ln.startswith("--"):
            continue
        s = ln.lstrip("-").strip()
        if s and not set(s) <= set("=-") and not ln.startswith("--  "):
            return s
    return "Ad-hoc query (no header)"


def parse_file(rel: str, text: str) -> dict:
    role = role_of(rel, text)
    folder = rel.split("/")[0] if "/" in rel else ""
    entry: dict = {"path": rel, "folder": folder, "role": role, "lines": text.count("\n") + 1}
    if role in ("definition", "orphan"):
        h = parse_header(text)
        s = h["sections"]
        entry.update(
            title=h["title"],
            path_line=h["path_line"],
            section_order=h["section_order"],
            sections={k: "\n".join(v).rstrip() for k, v in s.items()},
            objects=parse_objects(s.get("OBJECTS", [])),
            called_by=parse_called_by(s.get("CALLED BY", [])),
            requires=paths_in(s.get("REQUIRES", [])),
            see_also=paths_in(s.get("SEE ALSO", [])),
            tests=paths_in(s.get("TESTS", [])),
        )
    elif role == "migration":
        entry.update(title=parse_migration(text)["purpose"] or rel, migration=parse_migration(text), objects=[])
    else:
        entry.update(title=script_title(text), objects=[])
    entry["cron"] = parse_cron(rel, text)
    return entry


def build_catalog(root: Path = DATAMODELS) -> dict:
    """The whole catalogue: files, objects (name -> where it is defined) and pg_cron jobs. Deterministic (no timestamps)."""
    files = [parse_file(rel, (root / rel).read_text(encoding="utf-8")) for rel in sql_files(root)]
    objects: dict[str, dict] = {}
    duplicates: list[str] = []
    for f in files:
        for o in f.get("objects", []):
            if o["kind"] == "alter":
                continue
            key = o["name"]
            if key in objects:
                duplicates.append(f"{key}: {objects[key]['file']} and {f['path']}")
                continue
            objects[key] = {
                "kind": o["kind"],
                "file": f["path"],
                "folder": f["folder"],
                "role": f["role"],
                "signature": o["signature"],
                "description": o["description"],
                "called_by": f.get("called_by", {}).get(key, []),
            }
    cron = sorted((j for f in files for j in f["cron"]), key=lambda j: j["job"])
    return {
        "source": "ordelo_datamodels/**/*.sql (except _archive/); built by scripts/datamodels/build_guide.py",
        "files": files,
        "objects": dict(sorted(objects.items())),
        "cron": cron,
        "duplicates": duplicates,
    }
