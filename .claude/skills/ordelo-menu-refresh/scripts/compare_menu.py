"""
Compare a live <rest_ref>_menu table with that restaurant's Deliveroo menu CSVs and write a comparison CSV.
    . Dependencies: stdlib (csv, json, re, difflib, unicodedata); config.pg_setting + supabase only when reading the live table
    . Reads <dir>/deliveroo/menu_items.csv, option_groups.csv, options.csv (written by the deliveroo-menu-downloader skill)
    . Reads <rest_ref>_menu with the anon Supabase client, or from --db-json (a JSON list of rows, e.g. a snapshot) when given
    . Reads <dir>/menu_overrides.json when present (see the ordelo-menu-refresh SKILL.md):
      - reject: table titles that must stay unmatched (db_only) even if the automatic matcher finds something
      - match: table title -> {"item": Deliveroo item title, "options": [option names]}; match_type "manual",
        price = item price + the listed options' uplifts
    . Matches each table row to a Deliveroo item, in this order (after the overrides):
      - exact: same normalised title
      - normalised: same title after dropping filler words (burger, kids, loaded, ...), joining "5 pcs" -> "5pcs"
        and ignoring ml/oz/g sizes
      - via_option: Deliveroo merges several rows into one item plus a required choice (e.g. "Oreo Milkshake" = "Milkshake" + "Oreo");
        only required steps count, so optional upsells (drinks, milkshakes) on other items never match; an option equal
        to the whole title scores 1.0 only on single-choice picker items (soft drink can, milkshake), so combos and
        meal sides do not win; ties go to the cheapest item
      - fuzzy: best token similarity at or above FUZZY_MIN
      - db_only: no match
    . Adds one deliveroo_only row for every Deliveroo item no bnat_menu row matched
    . Compares price (Deliveroo item price + option uplift), discount, availability, image, description and add-on steps
    . Writes <dir>/<rest_ref>_menu_vs_deliveroo.csv and prints a summary
  Usage
    . python3 compare_menu.py --rest-ref bnat --dir <onboarding folder> [--db-json path] [--overrides path] [--out path]
  Functions/Classes
    . norm
    . tokens
    . reduced
    . core
    . similarity
    . load_deliveroo
    . load_db
    . load_overrides
    . db_steps
    . find_item
    . manual_match
    . match_row
    . build_rows
    . main
"""

import argparse
import csv
import difflib
import json
import os
import re
import unicodedata

FUZZY_MIN = 0.8
FILLER = {"s", "coca", "sugar", "burger", "burgers", "kids", "loaded", "the", "sandwich", "classic", "award", "winning", "make", "your", "own"}
REWRITE = {"smashburger": "smash", "bulls": "bull", "cola": "coke", "classic_330ml": "330ml"}

SIZE_RE = re.compile(r"^\d+(ml|oz|g)$")

COLUMNS = [
    "match_type", "match_score", "db_id", "db_sku", "db_title", "db_category",
    "deliveroo_item_id", "deliveroo_sku_ordelo", "deliveroo_title", "deliveroo_option", "deliveroo_category",
    "db_price", "deliveroo_price", "deliveroo_discounted_price", "price_diff", "db_discounted_price",
    "db_availability", "deliveroo_availability", "availability_same",
    "db_image_link", "deliveroo_image_link", "description_same",
    "db_addon_steps", "deliveroo_addon_steps", "db_addon_labels", "deliveroo_addon_labels",
    "db_description", "deliveroo_description",
]


def norm(text):
    s = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def tokens(text):
    s = re.sub(r"(\d+)_(pcs|pc|pieces|oz|ml|g)\b", r"\1\2", norm(text))
    out = []
    for t in s.split("_"):
        t = REWRITE.get(t, t)
        if t and t not in FILLER:
            out.append(t)
    return out


def reduced(text):
    return " ".join(tokens(text))


def core(text):
    return frozenset(t for t in tokens(text) if not SIZE_RE.match(t))


def similarity(a, b):
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    jac = len(ta & tb) / len(ta | tb)
    seq = difflib.SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return round(max(jac, seq), 3)


def _read(src, name):
    with open(os.path.join(src, name), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_deliveroo(src):
    items = [i for i in _read(src, "menu_items.csv") if i["is_active"] == "true"]
    groups, options = _read(src, "option_groups.csv"), _read(src, "options.csv")
    by_item = {}
    for g in sorted(groups, key=lambda g: int(g["step_index"])):
        by_item.setdefault(g["item_key"], []).append(g)
    opts = {}
    for o in sorted(options, key=lambda o: int(o["option_index"])):
        opts.setdefault(o["group_key"], []).append(o)
    for i in items:
        i["_groups"] = by_item.get(i["item_key"], [])
        i["_opts"] = {g["group_key"]: opts.get(g["group_key"], []) for g in i["_groups"]}
    return items


def load_db(rest_ref, db_json):
    if db_json:
        with open(db_json, encoding="utf-8") as f:
            return json.load(f)
    from config.pg_setting import pg_settings
    from supabase import create_client
    client = create_client(pg_settings.rest_url, pg_settings.rest_key)
    return client.table(f"{rest_ref.lower()}_menu").select("*").order("id").execute().data


def load_overrides(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def db_steps(row):
    addons = row.get("addons") or {}
    if isinstance(addons, str):
        addons = json.loads(addons) if addons.strip() else {}
    steps = sorted(addons.items(), key=lambda kv: int(re.sub(r"\D", "", kv[0]) or 0))
    return [s.get("label", "") for _, s in steps if isinstance(s, dict)]


def find_item(items, title):
    hits = [i for i in items if norm(i["title"]) == norm(title)]
    if len(hits) != 1:
        raise SystemExit(f"override: Deliveroo item {title!r} matched {len(hits)} items")
    return hits[0]


def manual_match(spec, items):
    """Resolve one override {"item", "options"} to (item, [options]); every option must exist on the item."""
    item = find_item(items, spec["item"])
    all_opts = [o for g in item["_groups"] for o in item["_opts"][g["group_key"]]]
    chosen = []
    for name in spec.get("options", []):
        hits = [o for o in all_opts if norm(o["name"]) == norm(name)]
        if not hits:
            raise SystemExit(f"override: option {name!r} not found on {item['title']!r}")
        chosen.append(hits[0])
    return item, chosen


def match_row(row, items, overrides=None):
    """Return (match_type, score, item, [options]) for one menu row."""
    overrides = overrides or {}
    t_norm = norm(row["title"])
    if t_norm in {norm(t) for t in overrides.get("reject", [])}:
        return "db_only", 0.0, None, []
    for title, spec in overrides.get("match", {}).items():
        if norm(title) == t_norm:
            item, opts = manual_match(spec, items)
            return "manual", 1.0, item, opts
    mtype, score, item, option = _auto_match(row, items)
    return mtype, score, item, [option] if option else []


def _auto_match(row, items):
    t_norm, t_red = norm(row["title"]), reduced(row["title"])
    for i in items:
        if norm(i["title"]) == t_norm:
            return "exact", 1.0, i, None
    for i in items:
        if reduced(i["title"]) == t_red or core(i["title"]) == core(row["title"]):
            return "normalised", 1.0, i, None
    same = []
    for i in items:
        i_red = reduced(i["title"])
        required = [g for g in i["_groups"] if g["is_required"] == "true"]
        for g in required:
            for o in i["_opts"][g["group_key"]]:
                o_red, o_core = reduced(o["name"]), core(o["name"])
                if not o_core or not o_core <= set(t_red.split()):
                    continue
                picker = len(required) == 1 and o_core == core(row["title"])
                score = 1.0 if picker else similarity(t_red, f"{o_red} {i_red}")
                same.append((score, -(_money(i["price"]) or 0), i, o))
    best = max(same, key=lambda x: (x[0], x[1])) if same else (0.0, 0, None, None)
    best = (best[0], best[2], best[3])
    if best[0] >= FUZZY_MIN:
        return "via_option", best[0], best[1], best[2]
    score, item = max(((similarity(t_red, reduced(i["title"])), i) for i in items), key=lambda x: x[0])
    if score >= FUZZY_MIN:
        return "fuzzy", score, item, None
    return "db_only", score, None, None


def _money(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _clean(v):
    return "" if v is None or str(v) in ("None", "none") else str(v)


def _dlv_cols(item, options):
    if item is None:
        return {}
    uplift = sum(_money(o["price_modifier"]) or 0.0 for o in options)
    price = _money(item["price"])
    disc = _money(item["discounted_price"])
    return {
        "deliveroo_item_id": item["sku"],
        "deliveroo_sku_ordelo": item["sku_ordelo"],
        "deliveroo_title": item["title"],
        "deliveroo_option": " + ".join(o["name"] for o in options),
        "deliveroo_category": item["category"],
        "deliveroo_price": f"{price + uplift:.2f}" if price is not None else "",
        "deliveroo_discounted_price": f"{disc + uplift:.2f}" if disc is not None else "",
        "deliveroo_availability": item["availability"],
        "deliveroo_image_link": item["image_link"],
        "deliveroo_addon_steps": len(item["_groups"]),
        "deliveroo_addon_labels": " | ".join(g["label"] for g in item["_groups"]),
        "deliveroo_description": item["description"],
    }


def build_rows(db, items, overrides=None):
    rows, used = [], set()
    for r in db:
        mtype, score, item, options = match_row(r, items, overrides)
        labels = db_steps(r)
        out = {
            "match_type": mtype, "match_score": score,
            "db_id": r.get("id"), "db_sku": _clean(r.get("sku")), "db_title": r.get("title"),
            "db_category": r.get("category"), "db_price": _clean(r.get("price")),
            "db_discounted_price": _clean(r.get("discounted_price")),
            "db_availability": _clean(r.get("availability")), "db_image_link": _clean(r.get("image_link")),
            "db_addon_steps": len(labels), "db_addon_labels": " | ".join(labels),
            "db_description": _clean(r.get("description")),
        }
        out.update(_dlv_cols(item, options))
        if item is not None:
            used.add(item["item_key"])
            dp, xp = _money(out["db_price"]), _money(out["deliveroo_price"])
            out["price_diff"] = f"{xp - dp:.2f}" if dp is not None and xp is not None else ""
            out["availability_same"] = str(out["db_availability"] == out["deliveroo_availability"]).lower()
            out["description_same"] = str(" ".join(out["db_description"].split()) == out["deliveroo_description"]).lower()
        rows.append(out)
    for i in items:
        if i["item_key"] not in used:
            out = {"match_type": "deliveroo_only", "match_score": ""}
            out.update(_dlv_cols(i, []))
            rows.append(out)
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--rest-ref", required=True)
    ap.add_argument("--dir", default=".", help="onboarding folder holding deliveroo/ and menu_overrides.json")
    ap.add_argument("--db-json")
    ap.add_argument("--overrides")
    ap.add_argument("--out")
    args = ap.parse_args()
    ref = args.rest_ref.lower()
    out = args.out or os.path.join(args.dir, f"{ref}_menu_vs_deliveroo.csv")
    overrides = load_overrides(args.overrides or os.path.join(args.dir, "menu_overrides.json"))
    items, db = load_deliveroo(os.path.join(args.dir, "deliveroo")), load_db(ref, args.db_json)
    rows = build_rows(db, items, overrides)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["match_type"]] = counts.get(r["match_type"], 0) + 1
    matched = [r for r in rows if r.get("price_diff")]
    print(json.dumps({
        "db_rows": len(db), "deliveroo_items": len(items), "match_types": counts,
        "price_differs": sum(1 for r in matched if float(r["price_diff"]) != 0),
        "out": out,
    }, indent=1))


if __name__ == "__main__":
    main()
