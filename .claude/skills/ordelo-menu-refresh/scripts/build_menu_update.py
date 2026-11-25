"""
Build a reviewable "undercut Deliveroo" change set for a <rest_ref>_menu table: changes CSV, update SQL and rollback SQL.
    . Dependencies: stdlib (argparse, collections, csv, decimal, glob, json, os, re, unicodedata); compare_menu (same folder)
    . Inputs (all inside --dir, the restaurant's onboarding folder):
      - <rest_ref>_menu_vs_deliveroo.csv written by compare_menu.py
      - deliveroo/*.csv (capture; the run id comes from crawl_log.csv)
      - snapshots/<rest_ref>_menu_<UTC>.json (newest by default): the authoritative "old" values
      - menu_overrides.json (accept_fuzzy, no_insert, category_map; reject/match are applied by compare_menu.py)
      - images/manifest.csv written by mirror_menu_images.py (optional; rows with status uploaded/exists get image_link)
    . Rules per table row:
      - D1 Deliveroo promotions are ignored: only the list price (+ matched option uplifts) is used
      - D2 matched and Deliveroo dearer than our price (discounted_price if set, else price): price = Deliveroo,
        discounted_price = our price
      - D3 matched and Deliveroo equal or cheaper: no change (reported); a stale discount is removed (price = our price)
      - D6 not on Deliveroo (db_only): availability = 'out of stock' (never deleted)
      - D9 no image_link and the manifest has the row's S3 copy: image_link = public S3 URL
      - fuzzy matches not listed in accept_fuzzy are "review": no change
    . D7 every deliveroo_only item not in no_insert is inserted at the Deliveroo price (D8 format: emojis removed,
      Title Case, sku = normalised title, category from the matched rows' mapping or category_map, addons converted)
    . Writes <rest_ref>_menu_changes.csv, <rest_ref>_menu_update.sql (one transaction, each UPDATE guarded by the old
      values, count checks that raise) and <rest_ref>_menu_rollback.sql (restores updated columns; DELETE of inserted
      rows is left commented out: it needs its own explicit approval)
  Usage
    . python3 build_menu_update.py --rest-ref bnat --dir <onboarding folder> [--snapshot path]
  Functions/Classes
    . strip_emoji
    . title_case
    . money
    . s3_url
    . load_inputs
    . convert_addons
    . category_mapping
    . plan_changes
    . image_candidates
    . sql_literal
    . build_update_sql
    . build_rollback_sql
    . write_changes_csv
    . main
"""

import argparse
import collections
import csv
import glob
import json
import os
import sys
import unicodedata
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_menu import load_deliveroo, load_overrides, norm  # noqa: E402

BUCKET = "ordelo-restaurants"
S3_BASE = f"https://{BUCKET}.s3.eu-west-2.amazonaws.com"
MATCHED = {"exact", "normalised", "via_option", "manual"}
UPDATE_COLS = ["price", "discounted_price", "availability", "image_link"]
INSERT_COLS = ["title", "sku", "description", "availability", "price", "currency", "branch_link", "image_link",
               "branch_name", "category", "discounted_price", "addons", "dietary_requirements"]
CHANGE_COLS = ["id", "action", "group", "reason", "title", "sku",
               "old_price", "new_price", "old_discounted_price", "new_discounted_price",
               "old_availability", "new_availability", "old_image_link", "new_image_link",
               "deliveroo_title", "deliveroo_option", "deliveroo_price", "category"]


def strip_emoji(text):
    out = "".join(c for c in (text or "") if unicodedata.category(c) not in ("So", "Sk", "Cf", "Mn", "Cs")
                  or c.isalnum())
    return " ".join(out.split())


def title_case(text):
    return " ".join(w[:1].upper() + w[1:] for w in strip_emoji(text).split())


def money(value):
    if value is None or str(value).strip() in ("", "None"):
        return None
    try:
        return Decimal(str(value).strip()).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def s3_url(ref, sku):
    return f"{S3_BASE}/{ref}/{sku}.jpg"


def _csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_inputs(ref, folder, snapshot=None):
    snapshot = snapshot or sorted(glob.glob(os.path.join(folder, "snapshots", f"{ref}_menu_*.json")))[-1]
    with open(snapshot, encoding="utf-8") as f:
        snap = {int(r["id"]): r for r in json.load(f)}
    manifest_path = os.path.join(folder, "images", "manifest.csv")
    manifest = {r["sku"]: r for r in _csv(manifest_path)} if os.path.exists(manifest_path) else {}
    return {
        "ref": ref,
        "snapshot_path": snapshot,
        "snapshot": snap,
        "compare": _csv(os.path.join(folder, f"{ref}_menu_vs_deliveroo.csv")),
        "items": {i["sku"]: i for i in load_deliveroo(os.path.join(folder, "deliveroo"))},
        "run_id": _csv(os.path.join(folder, "deliveroo", "crawl_log.csv"))[-1]["run_id"],
        "overrides": load_overrides(os.path.join(folder, "menu_overrides.json")),
        "manifest": manifest,
    }


def convert_addons(item):
    """Deliveroo option groups -> {stepN: {label, required, allow_multiple, options: [{name, price_modifier}]}}."""
    steps = {}
    for n, g in enumerate(item["_groups"], 1):
        max_sel = int(g["max_select"] or 0)
        steps[f"step{n}"] = {
            "label": strip_emoji(g["label"]),
            "required": g["is_required"] == "true",
            "allow_multiple": max_sel != 1,
            "options": [{"name": strip_emoji(o["name"]), "price_modifier": float(o["price_modifier"] or 0)}
                        for o in item["_opts"][g["group_key"]] if o.get("is_available", "true") != "false"],
        }
    return steps


def category_mapping(compare_rows, overrides):
    votes = collections.defaultdict(collections.Counter)
    for r in compare_rows:
        if r["match_type"] in MATCHED and r["db_category"]:
            votes[norm(strip_emoji(r["deliveroo_category"]))][r["db_category"]] += 1
    mapping = {k: c.most_common(1)[0][0] for k, c in votes.items()}
    mapping.update({norm(strip_emoji(k)): v for k, v in overrides.get("category_map", {}).items()})
    return mapping


def _image_ready(inp, sku):
    m = inp["manifest"].get(sku)
    return s3_url(inp["ref"], sku) if m and m["status"] in ("uploaded", "exists") else None


def plan_changes(inp):
    """Return (rows, inserts): one change dict per table row, plus one dict per new row."""
    ov, snap = inp["overrides"], inp["snapshot"]
    accept_fuzzy = {norm(t) for t in ov.get("accept_fuzzy", [])}
    no_insert = {norm(strip_emoji(t)) for t in ov.get("no_insert", [])}
    rows, inserts = [], []
    for c in inp["compare"]:
        if c["match_type"] == "deliveroo_only":
            if norm(strip_emoji(c["deliveroo_title"])) not in no_insert:
                inserts.append(c)
            continue
        old = snap.get(int(c["db_id"]))
        if old is None:
            raise SystemExit(f"row {c['db_id']} is in the comparison but not in the snapshot; re-run compare_menu.py")
        new = {k: old.get(k) for k in UPDATE_COLS}
        price, disc = money(old.get("price")), money(old.get("discounted_price"))
        ours = disc if disc is not None else price
        reasons = []
        mtype = c["match_type"]
        matched = mtype in MATCHED or (mtype == "fuzzy" and norm(c["db_title"]) in accept_fuzzy)
        if matched:
            xp = money(c["deliveroo_price"])
            if xp is not None and ours is not None and xp > ours:
                group = "D2"
                if (price, disc) != (xp, ours):
                    new["price"], new["discounted_price"] = xp, f"{ours:.2f}"
                    reasons.append("D2")
            else:
                group = "D3"
                if disc is not None:
                    new["price"], new["discounted_price"] = ours, None
                    reasons.append("D3-clear-discount")
            if not old.get("image_link") and c["deliveroo_image_link"]:
                url = _image_ready(inp, old["sku"])
                if url:
                    new["image_link"] = url
                    reasons.append("D9")
        elif mtype == "db_only":
            group = "D6"
            if old.get("availability") != "out of stock":
                new["availability"] = "out of stock"
                reasons.append("D6")
        else:
            group = "review"
        changed = [k for k in UPDATE_COLS if str(new[k]) != str(old.get(k)) and not (
            k == "price" and money(new[k]) == money(old.get(k)))]
        rows.append({"cmp": c, "old": old, "new": new, "group": group, "reasons": reasons, "changed": changed})
    cats = category_mapping(inp["compare"], ov)
    template = collections.Counter((r.get("branch_link"), r.get("branch_name"), r.get("currency")) for r in snap.values())
    branch_link, branch_name, currency = template.most_common(1)[0][0]
    new_rows = []
    for c in inserts:
        item = inp["items"][c["deliveroo_item_id"]]
        title = title_case(item["title"])
        sku = norm(title)
        new_rows.append({"cmp": c, "item": item, "group": "D7", "values": {
            "title": title, "sku": sku, "description": strip_emoji(item["description"]) or None,
            "availability": item["availability"] or "in stock", "price": money(item["price"]),
            "currency": currency or "GBP", "branch_link": branch_link, "image_link": _image_ready(inp, sku),
            "branch_name": branch_name,
            "category": cats.get(norm(strip_emoji(item["category"])), strip_emoji(item["category"]).upper()),
            "discounted_price": None, "addons": convert_addons(item),
            "dietary_requirements": item["dietary_requirements"] or None,
        }})
    skus = [r["old"]["sku"] for r in rows] + [n["values"]["sku"] for n in new_rows]
    dup = [s for s, k in collections.Counter(skus).items() if k > 1]
    if dup:
        raise SystemExit(f"duplicate sku(s) after insert: {dup}")
    return rows, new_rows


def image_candidates(inp):
    """Rows needing an S3 image copy: (sku, Deliveroo image URL) for matched rows without image_link and new rows."""
    rows, new_rows = plan_changes(inp)
    out = [(r["old"]["sku"], r["cmp"]["deliveroo_image_link"]) for r in rows
           if r["group"] in ("D2", "D3") and not r["old"].get("image_link") and r["cmp"]["deliveroo_image_link"]]
    out += [(n["values"]["sku"], n["item"]["image_link"]) for n in new_rows if n["item"]["image_link"]]
    return out


def sql_literal(value, col=None):
    if value is None:
        return "NULL"
    if col == "price":
        return f"{money(value):.2f}"
    if col == "addons":
        return sql_literal(json.dumps(value, ensure_ascii=False)) + "::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def _header(inp, kind, n_upd, n_ins):
    return (f"-- {inp['ref']}_menu {kind}: generated by .claude/skills/ordelo-menu-refresh/scripts/build_menu_update.py\n"
            f"-- Deliveroo capture run: {inp['run_id']}\n"
            f"-- Snapshot: {os.path.basename(inp['snapshot_path'])}\n"
            f"-- Updated rows: {n_upd}; inserted rows: {n_ins}\n")


def build_update_sql(inp, rows, new_rows):
    table = f"public.{inp['ref']}_menu"
    upd = [r for r in rows if r["changed"]]
    lines = [_header(inp, "update (undercut Deliveroo)", len(upd), len(new_rows)),
             "-- Each UPDATE only touches a row whose touched columns still hold the snapshot values; the count checks",
             "-- raise (rolling everything back) if any row was edited since the snapshot or a new title already exists.",
             "BEGIN;", "", "DO $menu$", "DECLARE", "    n_upd integer := 0;", "    n_ins integer := 0;", "    c integer;",
             "BEGIN"]
    for r in upd:
        sets = ", ".join(f"{k} = {sql_literal(r['new'][k], k)}" for k in r["changed"])
        guards = " AND ".join(f"{k} IS NOT DISTINCT FROM {sql_literal(r['old'].get(k), k)}" for k in r["changed"])
        lines.append(f"    -- {r['old']['title']} ({', '.join(r['reasons'])})")
        lines.append(f"    UPDATE {table} SET {sets} WHERE id = {r['old']['id']} AND {guards};")
        lines.append("    GET DIAGNOSTICS c = ROW_COUNT; n_upd := n_upd + c;")
    for n in new_rows:
        v = n["values"]
        vals = ", ".join(sql_literal(v[k], k) for k in INSERT_COLS)
        lines.append(f"    -- {v['title']} (D7)")
        lines.append(f"    INSERT INTO {table} ({', '.join(INSERT_COLS)})")
        lines.append(f"    SELECT {vals}")
        lines.append(f"    WHERE NOT EXISTS (SELECT 1 FROM {table} WHERE lower(title) = lower({sql_literal(v['title'])})"
                     f" OR sku = {sql_literal(v['sku'])});")
        lines.append("    GET DIAGNOSTICS c = ROW_COUNT; n_ins := n_ins + c;")
    lines += [f"    IF n_upd <> {len(upd)} THEN RAISE EXCEPTION 'expected {len(upd)} updated rows, got %', n_upd; END IF;",
              f"    IF n_ins <> {len(new_rows)} THEN RAISE EXCEPTION 'expected {len(new_rows)} inserted rows, got %', n_ins;"
              " END IF;",
              "END", "$menu$;", "", "COMMIT;", ""]
    return "\n".join(lines)


def build_rollback_sql(inp, rows, new_rows):
    table = f"public.{inp['ref']}_menu"
    upd = [r for r in rows if r["changed"]]
    lines = [_header(inp, "rollback", len(upd), len(new_rows)),
             "-- Restores the touched columns of every updated row to the snapshot values.", "BEGIN;"]
    for r in upd:
        sets = ", ".join(f"{k} = {sql_literal(r['old'].get(k), k)}" for k in r["changed"])
        lines.append(f"UPDATE {table} SET {sets} WHERE id = {r['old']['id']};")
    lines += ["COMMIT;", "",
              "-- Removing the inserted rows is a DELETE: run it only with its own explicit approval",
              "-- (database-operations skill). Check first with the SELECT.",
              f"-- SELECT id, title, sku FROM {table} WHERE sku IN ("
              + ", ".join(sql_literal(n["values"]["sku"]) for n in new_rows) + ");",
              f"-- DELETE FROM {table} WHERE sku IN ("
              + ", ".join(sql_literal(n["values"]["sku"]) for n in new_rows) + ");", ""]
    return "\n".join(lines)


def write_changes_csv(path, rows, new_rows):
    def fmt(v):
        return "" if v is None else (f"{v:.2f}" if isinstance(v, Decimal) else str(v))

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CHANGE_COLS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for r in rows:
            o, n, c = r["old"], r["new"], r["cmp"]
            out = {"id": o["id"], "action": "update" if r["changed"] else "none", "group": r["group"],
                   "reason": ";".join(r["reasons"]), "title": o["title"], "sku": o["sku"],
                   "deliveroo_title": c["deliveroo_title"], "deliveroo_option": c["deliveroo_option"],
                   "deliveroo_price": c["deliveroo_price"], "category": o.get("category")}
            for k in UPDATE_COLS:
                out[f"old_{k}"], out[f"new_{k}"] = fmt(o.get(k)), fmt(n[k])
            w.writerow(out)
        for x in new_rows:
            v = x["values"]
            w.writerow({"id": "", "action": "insert", "group": "D7", "reason": "D7" + (";D9" if v["image_link"] else ""),
                        "title": v["title"], "sku": v["sku"], "new_price": fmt(v["price"]),
                        "new_availability": v["availability"], "new_image_link": fmt(v["image_link"]),
                        "deliveroo_title": x["item"]["title"], "deliveroo_price": x["cmp"]["deliveroo_price"],
                        "category": v["category"]})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--rest-ref", required=True)
    ap.add_argument("--dir", default=".")
    ap.add_argument("--snapshot")
    args = ap.parse_args()
    ref = args.rest_ref.lower()
    inp = load_inputs(ref, args.dir, args.snapshot)
    rows, new_rows = plan_changes(inp)
    out = {k: os.path.join(args.dir, f"{ref}_menu_{k}") for k in ("changes.csv", "update.sql", "rollback.sql")}
    write_changes_csv(out["changes.csv"], rows, new_rows)
    with open(out["update.sql"], "w", encoding="utf-8") as f:
        f.write(build_update_sql(inp, rows, new_rows))
    with open(out["rollback.sql"], "w", encoding="utf-8") as f:
        f.write(build_rollback_sql(inp, rows, new_rows))
    groups = collections.Counter(r["group"] for r in rows)
    print(json.dumps({
        "run_id": inp["run_id"], "snapshot": os.path.basename(inp["snapshot_path"]),
        "groups": dict(groups), "inserts": len(new_rows),
        "updated_rows": sum(1 for r in rows if r["changed"]),
        "by_reason": dict(collections.Counter(x for r in rows for x in r["reasons"])),
        "images_set": sum(1 for r in rows if "D9" in r["reasons"]) + sum(1 for n in new_rows if n["values"]["image_link"]),
        "images_missing": sum(1 for r in rows if r["group"] in ("D2", "D3") and not r["new"]["image_link"])
        + sum(1 for n in new_rows if not n["values"]["image_link"]),
        "out": out,
    }, indent=1))


if __name__ == "__main__":
    main()
