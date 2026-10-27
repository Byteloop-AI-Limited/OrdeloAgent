"""Compare the SQL files with the live database. Read-only on live; the files are applied to a LOCAL throwaway Postgres.

    export ORDELO_LIVE_DB_URI=postgresql://...        # the live database (read-only transaction, catalogue queries only)
    export ORDELO_TEST_DB_URI=postgresql://postgres@localhost:5433/postgres?host=/tmp   # a local scratch server (it is reset!)
    python scripts/datamodels/drift_check.py [--live-json FILE] [--save-live FILE]

Steps: snapshot the live catalogue (or read --live-json) -> reset the scratch database -> apply stubs, the external objects'
columns and every SQL file (not _archive/, migrations/ or the test scripts) -> compare the two catalogues.
Compared for every object ordelo_datamodels/ owns: functions (normalised body, signature, result, language, volatility, security
definer, grants), tables (columns, constraints, indexes, RLS, policies, grants), views, triggers and pg_cron jobs. Also lists live
objects that no file owns. Formatting and comments never show as drift. Exit code 0 only when there is no difference.
Needs: psycopg, and pgcrypto, uuid-ossp, pgvector and postgis on the scratch server (stubs stand in for pg_cron, pg_net, http, pgmq).
"""
from __future__ import annotations

import json
import os
import re
import sys

import psycopg

sys.path.insert(0, os.path.dirname(__file__))
import catalog as cat  # noqa: E402
from sqlsplit import split  # noqa: E402

REPO = str(cat.DATAMODELS)
_EXT = json.loads((cat.DATAMODELS / "external_objects.json").read_text(encoding="utf-8"))
EXTERNAL, LIBRARY, EXTERNAL_ADDITIONS = _EXT["external"], _EXT["library"], _EXT["additions"]
OBJ = {n: o["file"] for n, o in cat.build_catalog()["objects"].items()}
LIVE: dict = {}
SKIP_DIRS = {"migrations", "_archive"}  # test_support/ scripts that need fixtures are skipped below
SKIP_FILES = {"test_support/test_restaurant_notices.sql", "test_support/test_create_t_order_alerts.sql",
              "test_support/test_magic_link.sql", "test_support/get_ddl_for_table.sql"}


def norm(s: str) -> str:
    s = re.sub(r"/\*.*?\*/", "", s or "", flags=re.S)
    s = re.sub(r"--[^\n]*", "", s)
    s = s.lower().replace("public.", "").replace('"', "")
    return re.sub(r"\s+", "", s)


def canon(s: str) -> str:
    s = (s or "").lower()
    for x in ("::character varying", "::text[]", "::text", "not valid"):
        s = s.replace(x, "")
    return re.sub(r"[\s()]", "", s)


def canon_view(s: str) -> str:
    return canon(re.sub(r"\b[a-z_][a-z0-9_]*\.(?=[a-z_])", "", (s or "").lower()))


def literals(text: str) -> list[str]:
    """Every single-quoted string literal, in order (a small scanner: comments and quotes handled properly).
    Formatting must keep each literal byte for byte."""
    out, i, n, t = [], 0, len(text or ""), text or ""
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


def body_of(text: str) -> str:
    m = re.search(r"(\$[A-Za-z_0-9]*\$)(.*)\1", text, re.S)
    return m.group(2) if m else text


def external_ddl() -> list[str]:
    cols = {}
    for c in LIVE["columns"]:
        cols.setdefault(c["tbl"], []).append(c)
    owned_add = {t: v["columns"] for t, v in EXTERNAL_ADDITIONS.items()}
    out = []
    for name in list(EXTERNAL) + list(LIBRARY):
        if name not in {t["name"] for t in LIVE["tables"]}:
            continue
        defs = []
        for c in cols[name]:
            if c["col"] in owned_add.get(name, []):
                continue
            d = f'"{c["col"]}" {c["type"]}'
            if c["is_notnull"]:
                d += " NOT NULL"
            defs.append(d)
        for k in LIVE["constraints"]:
            if k["tbl"] == name and k["type"] in ("p", "u") and not any(col in k["def"] for col in owned_add.get(name, [])):
                defs.append(f'CONSTRAINT "{k["name"]}" {k["def"]}')
        out.append(f'CREATE TABLE IF NOT EXISTS public."{name}" ({", ".join(defs)});')
    return out


def files():
    for d, ds, fs in os.walk(REPO):
        ds[:] = sorted(x for x in ds if x not in SKIP_DIRS)
        for f in sorted(fs):
            if f.endswith(".sql"):
                r = os.path.relpath(os.path.join(d, f), REPO)
                if r not in SKIP_FILES:
                    yield r


def reset(conn):
    conn.execute("DROP SCHEMA IF EXISTS public, extensions, net, pgmq, cron CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO public;")
    conn.execute(open(os.path.join(os.path.dirname(__file__), "drift_stubs.sql")).read())
    conn.execute("SET search_path TO \"$user\", public, extensions")


def apply_all(conn) -> list[tuple[str, str, str]]:
    pending = [("externals", s) for s in external_ddl()]
    for r in files():
        st, _ = split(open(os.path.join(REPO, r), encoding="utf-8").read())
        pending += [(r, s["text"]) for s in st]
    for _ in range(8):
        failed = []
        for r, sql in pending:
            try:
                with conn.transaction():
                    conn.execute(sql)
            except Exception as e:  # noqa: BLE001
                failed.append((r, sql, str(e).split("\n")[0]))
        if len(failed) == len(pending):
            return failed
        pending = [(r, s) for r, s, _ in failed]
        if not pending:
            return []
    return failed


def snapshot(conn) -> dict:
    def q(sql):
        cur = conn.execute(sql)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    ext = "not exists (select 1 from pg_depend d where d.objid=%s and d.deptype='e')"
    return {
        "functions": q(f"""select p.proname name, pg_get_function_identity_arguments(p.oid) args, pg_get_function_result(p.oid) result,
            l.lanname lang, p.prosecdef secdef, p.provolatile::text volatility, p.proacl::text acl, pg_get_functiondef(p.oid) def
            from pg_proc p join pg_namespace n on n.oid=p.pronamespace join pg_language l on l.oid=p.prolang
            where n.nspname='public' and p.prokind in ('f','p') and {ext % 'p.oid'}"""),
        "columns": q("""select c.relname tbl, a.attname col, format_type(a.atttypid,a.atttypmod) type, a.attnotnull is_notnull,
            pg_get_expr(d.adbin,d.adrelid) dflt from pg_attribute a join pg_class c on c.oid=a.attrelid
            join pg_namespace n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum
            where n.nspname='public' and c.relkind in ('r','p') and a.attnum>0 and not a.attisdropped"""),
        "tables": q("""select c.relname name, c.relrowsecurity rls, c.relacl::text acl from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='public' and c.relkind in ('r','p')"""),
        "constraints": q("""select c.relname tbl, k.conname name, k.contype::text type, pg_get_constraintdef(k.oid) def from pg_constraint k
            join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='public'"""),
        "indexes": q("select tablename tbl, indexname name, indexdef def from pg_indexes where schemaname='public'"),
        "policies": q("select tablename tbl, policyname name, permissive, cmd, roles::text, qual, with_check from pg_policies where schemaname='public'"),
        "views": q("""select c.relname name, c.reloptions::text reloptions, pg_get_viewdef(c.oid,true) def, c.relacl::text acl
            from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind in ('v','m')"""),
        "triggers": q("""select t.tgname name, c.relname tbl, pg_get_triggerdef(t.oid,true) def from pg_trigger t
            join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and not t.tgisinternal"""),
        "cron": q("select jobname, schedule, command, active from cron.job"),
    }


def compare(live, loc) -> list[str]:
    owned = set(OBJ)
    problems = []

    def by(rows, *keys):
        return {tuple(r[k] for k in keys): r for r in rows}

    lf, rf = by(live["functions"], "name", "args"), by(loc["functions"], "name", "args")
    for k, f in lf.items():
        if f["name"] not in owned:
            continue
        g = rf.get(k)
        if not g:
            problems.append(f"function missing: {k}")
            continue
        for a in ("result", "lang", "secdef", "volatility", "acl"):
            if f[a] != g[a]:
                problems.append(f"function {k[0]}: {a} live={f[a]} repo={g[a]}")
        if norm(body_of(f["def"])) != norm(body_of(g["def"])):
            problems.append(f"function {k[0]}: body differs")
        elif literals(body_of(f["def"])) != literals(body_of(g["def"])):
            problems.append(f"function {k[0]}: string literals differ")
        hl, hr = re.split(r"\bAS \$", f["def"])[0], re.split(r"\bAS \$", g["def"])[0]
        if norm(hl) != norm(hr):
            problems.append(f"function {k[0]}: header differs\n   live: {' '.join(hl.split())}\n   repo: {' '.join(hr.split())}")
    for k in rf:
        if k[0] in owned and k not in lf:
            problems.append(f"function not live: {k}")
    owned_tables = {t["name"] for t in live["tables"] if t["name"] in owned}
    add_cols = {(t, c) for t, v in EXTERNAL_ADDITIONS.items() for c in v["columns"]}
    lc, rc = by(live["columns"], "tbl", "col"), by(loc["columns"], "tbl", "col")
    for k, c in lc.items():
        if k[0] not in owned_tables and k not in add_cols:
            continue
        d = rc.get(k)
        if not d:
            problems.append(f"column missing: {k}")
            continue
        for a in ("type", "is_notnull", "dflt"):
            if c[a] != d[a]:
                problems.append(f"column {k}: {a} live={c[a]} repo={d[a]}")
    for k in rc:
        if k[0] in owned_tables and k not in lc:
            problems.append(f"column not live: {k}")
    lt, rt = by(live["tables"], "name"), by(loc["tables"], "name")
    for t in owned_tables:
        if (t,) not in rt:
            problems.append(f"table missing: {t}")
            continue
        for a in ("rls", "acl"):
            if lt[(t,)][a] != rt[(t,)][a]:
                problems.append(f"table {t}: {a} live={lt[(t,)][a]} repo={rt[(t,)][a]}")
    add_cons = {(t, c) for t, v in EXTERNAL_ADDITIONS.items() for c in v["constraints"] + v["indexes"]}
    for kind in ("constraints", "indexes"):
        lk, rk = by(live[kind], "tbl", "name"), by(loc[kind], "tbl", "name")
        for k, c in lk.items():
            if k[0] not in owned_tables and k not in add_cons:
                continue
            d = rk.get(k)
            if not d:
                problems.append(f"{kind[:-1]} missing: {k}")
            elif canon(c["def"]) != canon(d["def"]):
                problems.append(f"{kind[:-1]} {k}: live={c['def']} repo={d['def']}")
        for k in rk:
            if k[0] in owned_tables and k not in lk:
                problems.append(f"{kind[:-1]} not live: {k}")
    lp, rp = by(live["policies"], "tbl", "name"), by(loc["policies"], "tbl", "name")
    for k, p in lp.items():
        if k[0] in owned_tables and (rp.get(k) or {}).get("qual") != p["qual"]:
            problems.append(f"policy differs/missing: {k}")
    lv, rv = by(live["views"], "name"), by(loc["views"], "name")
    for k, v in lv.items():
        if k[0] not in owned:
            continue
        w = rv.get(k)
        if not w:
            problems.append(f"view missing: {k[0]}")
            continue
        for a in ("reloptions", "acl"):
            if v[a] != w[a]:
                problems.append(f"view {k[0]}: {a} live={v[a]} repo={w[a]}")
        if canon_view(v["def"]) != canon_view(w["def"]):
            problems.append(f"view {k[0]}: definition differs")
    ltr, rtr = by(live["triggers"], "name"), by(loc["triggers"], "name")
    for k, t in ltr.items():
        if k[0] not in owned:
            continue
        if not rtr.get(k):
            problems.append(f"trigger missing: {k[0]}")
        elif canon(rtr[k]["def"]) != canon(t["def"]):
            problems.append(f"trigger {k[0]}: live={t['def']} repo={rtr[k]['def']}")
    for k in rtr:
        if k not in ltr:
            problems.append(f"trigger not live: {k[0]}")
    lj, rj = by(live["cron"], "jobname"), by(loc["cron"], "jobname")
    for k, j in lj.items():
        r = rj.get(k)
        if not r:
            problems.append(f"cron missing: {k[0]}")
        else:
            for a in ("schedule", "command", "active"):
                if (j[a].strip() if isinstance(j[a], str) else j[a]) != (r[a].strip() if isinstance(r[a], str) else r[a]):
                    problems.append(f"cron {k[0]}: {a} live={j[a]!r} repo={r[a]!r}")
    for k in rj:
        if k not in lj:
            problems.append(f"cron not live: {k[0]}")
    return problems


def live_snapshot(uri: str) -> dict:
    """Catalogue-only, read-only snapshot of the live database (the same shape snapshot() gives for the scratch one,
    plus the extras the 'no file' report needs)."""
    with psycopg.connect(uri, autocommit=False, connect_timeout=15, prepare_threshold=None) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        out = snapshot(conn)
        ext = "not exists (select 1 from pg_depend d where d.objid=%s and d.deptype='e')"
        cur = conn.execute(
            f"""select c.relname name, c.relkind::text kind from pg_class c join pg_namespace n on n.oid=c.relnamespace
                where n.nspname='public' and c.relkind in ('r','p','v','m') and {ext % 'c.oid'}""")
        out["relations"] = [{"name": r[0], "kind": r[1]} for r in cur.fetchall()]
        conn.rollback()
    return out


def no_file_report(live) -> list[str]:
    """Live relations and functions that no file owns, no other repo owns and no library owns."""
    known = set(OBJ) | set(EXTERNAL) | set(LIBRARY)
    out = []
    for r in live.get("relations", []):
        if r["name"] not in known:
            out.append(f"live {'view' if r['kind'] in ('v', 'm') else 'table'} with no file: {r['name']}")
    for f in live["functions"]:
        if f["name"] not in known:
            out.append(f"live function with no file: {f['name']}({f['args']})")
    return sorted(set(out))


def main():
    args = sys.argv[1:]

    def opt(name):
        return args[args.index(name) + 1] if name in args else None

    live_json, save = opt("--live-json"), opt("--save-live")
    dsn = os.environ.get("ORDELO_TEST_DB_URI")
    if not dsn:
        sys.exit("set ORDELO_TEST_DB_URI to a LOCAL throwaway Postgres (it is reset)")
    host = (re.search(r"@([^:/?]+)", dsn) or [None, ""])[1]
    if host not in ("localhost", "127.0.0.1", "::1", "") and "host=/" not in dsn:
        sys.exit(f"ORDELO_TEST_DB_URI must be local, got {host!r}")
    if live_json:
        live = json.load(open(live_json))
    else:
        uri = os.environ.get("ORDELO_LIVE_DB_URI")
        if not uri:
            sys.exit("set ORDELO_LIVE_DB_URI (read-only use) or pass --live-json FILE")
        live = live_snapshot(uri)
    if save:
        json.dump(live, open(save, "w"), indent=1, default=str)
    LIVE.clear()
    LIVE.update(live)
    with psycopg.connect(dsn, autocommit=True) as conn:
        reset(conn)
        failed = apply_all(conn)
        loc = snapshot(conn)
    for r, sql, err in failed:
        print(f"APPLY FAILED {r}: {err} :: {' '.join(sql.split())[:140]}")
    problems = compare(LIVE, loc)
    for p in problems:
        print("DIFF", p)
    extra = no_file_report(LIVE)
    for p in extra:
        print("NOTE", p)
    print(f"{len(failed)} statements failed to apply, {len(problems)} differences from live, {len(extra)} live objects with no file")
    sys.exit(1 if failed or problems else 0)


if __name__ == "__main__":
    main()
