"""Keeps ordelo_datamodels/ honest (the "ordelo_datamodels SQL standard" in agents.md). Offline: reads files only.

Checks: every definition file has the 13 header sections in order; each object is defined once and its CREATE exists;
paths named in headers, in Python "Database objects" docstrings and in the guide flows exist; Python .rpc()/.table() names are
known; migrations are marked as history; the committed guide/catalog are current; pg_format would not change anything.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "datamodels"))
import build_guide  # noqa: E402
import catalog as cat  # noqa: E402

DM = cat.DATAMODELS
EXT = json.loads((DM / "external_objects.json").read_text(encoding="utf-8"))
CONTENT = json.loads((DM / "guide_content.json").read_text(encoding="utf-8"))
CAT = cat.build_catalog()
DEFS = [f for f in CAT["files"] if f["role"] in ("definition", "orphan")]
SKIP_PY_DIRS = {".git", ".venv", "venv", "node_modules", "tests", "notebooks", "__pycache__", "build", "dist"}


PATH_TOKEN = re.compile(r"^[A-Za-z0-9_./*-]+\.(?:sql|md|py|html|json|mjs|ts)$")


def _missing(entry: str) -> list[str]:
    """Paths named in one header line (comma-separated, with an optional '(note)'); free text is not checked."""
    entry = re.sub(r"\([^)]*\)", "", entry)
    out = []
    for tok in (t.strip() for t in entry.split(",")):
        if not PATH_TOKEN.match(tok) or "*" in tok or tok.startswith(("restaurant-agents", "restaurant-frontend")):
            continue
        if not ((ROOT / tok).exists() or (DM / tok).exists()):
            out.append(tok)
    return out


def test_folder_layout_is_known():
    folders = {f["folder"] for f in CAT["files"]}
    known = {c["folder"] for c in CONTENT["capabilities"]}
    assert folders <= known, f"folders missing from guide_content.json capabilities: {sorted(folders - known)}"
    stray = [p.name for p in DM.glob("*.sql")]
    assert not stray, f"SQL files must live in a capability folder, not ordelo_datamodels/: {stray}"


@pytest.mark.parametrize("f", DEFS, ids=lambda f: f["path"])
def test_header_has_every_section_in_order(f):
    assert f["section_order"] == cat.SECTIONS, f"{f['path']}: header sections {f['section_order']}"
    assert f["path_line"] == f"ordelo_datamodels/{f['path']}", f"{f['path']}: second header line must be the file path"
    assert f["title"], f"{f['path']}: one-line title missing"
    assert f["sections"]["LIVE CHECK"].strip(), f"{f['path']}: LIVE CHECK empty"
    assert f["objects"] or f["cron"], f"{f['path']}: OBJECTS lists nothing (a file with no objects must at least schedule a cron job)"


def test_every_object_is_defined_once():
    assert CAT["duplicates"] == []


@pytest.mark.parametrize("f", [f for f in DEFS if f["objects"]], ids=lambda f: f["path"])
def test_listed_objects_exist_in_the_file(f):
    text = (DM / f["path"]).read_text(encoding="utf-8")
    hdr = len(cat.header_lines(text))
    for o in f["objects"]:
        if o["kind"] == "alter":
            continue
        assert build_guide.object_line(o["name"], o["kind"], text, hdr), f"{f['path']}: OBJECTS lists {o['kind']} {o['name']} but no CREATE for it"


@pytest.mark.parametrize("f", DEFS, ids=lambda f: f["path"])
def test_header_paths_exist(f):
    missing = [m for p in f["requires"] + f["see_also"] + f["tests"] for m in _missing(p)]
    assert not missing, f"{f['path']}: paths that do not exist: {missing}"


def test_migrations_are_marked_history():
    for f in CAT["files"]:
        if f["role"] == "migration":
            head = (DM / f["path"]).read_text(encoding="utf-8").split("\n", 3)
            assert head[0].startswith("-- MIGRATION (history"), f["path"]
            assert f["migration"]["applied"] and f["migration"]["current"], f"{f['path']}: needs 'Applied to live' and 'Current definitions now live in'"
            for cur in f["migration"]["current"]:
                assert not _missing(cur), f"{f['path']}: current definition path {cur!r} does not exist"


def test_flows_name_known_objects():
    known = set(CAT["objects"]) | set(EXT["external"]) | set(EXT["library"])
    bad = [(fl["id"], o) for fl in CONTENT["flows"] for s in fl["steps"] for o in s["objects"] if o not in known]
    assert not bad, f"flows mention objects that do not exist: {bad}"


def test_cron_jobs_are_runnable_statements():
    jobs = [j["job"] for j in CAT["cron"]]
    assert len(jobs) == len(set(jobs)), "a pg_cron job is scheduled by two files"


def _python_files():
    for p in ROOT.rglob("*.py"):
        if not SKIP_PY_DIRS & set(p.relative_to(ROOT).parts):
            yield p


def test_python_rpc_and_table_names_are_known():
    known = set(CAT["objects"]) | set(EXT["external"]) | set(EXT["library"]) | set(EXT.get("other", {}))
    pat = re.compile(r"\.(?:rpc|table|from_)\(\s*[\"']([a-z_][a-z0-9_]*)[\"']")
    bad: dict[str, set[str]] = {}
    for p in _python_files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name in pat.findall(text):
            if name not in known:
                bad.setdefault(name, set()).add(p.relative_to(ROOT).as_posix())
    assert not bad, "Python uses database names no SQL file defines (add the file, or list the name under 'other' in ordelo_datamodels/external_objects.json): " + json.dumps({k: sorted(v) for k, v in bad.items()})


def test_python_database_sections_point_at_real_files():
    pat = re.compile(r"ordelo_datamodels/([A-Za-z0-9_./-]+\.sql)")
    bad = []
    for p in _python_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        doc = ast.get_docstring(tree) or ""
        if "Database objects (" not in doc:
            continue
        for rel in pat.findall(doc):
            if not (DM / rel).exists():
                bad.append(f"{p.relative_to(ROOT)}: {rel}")
    assert not bad, bad


def test_committed_guide_is_current():
    built = build_guide.build_all()
    stale = [p.name for p, t in built.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
    assert not stale, f"regenerate with: python scripts/datamodels/build_guide.py  (stale: {stale})"


def test_sql_is_formatted():
    binary = shutil.which("pg_format")
    if not binary:
        import os

        binary = os.environ.get("PG_FORMAT")
    if not binary:
        pytest.skip("pg_format not installed (pgFormatter 5.6); CI/devs with it get the check")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "datamodels" / "format_sql.py"), "--check"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
