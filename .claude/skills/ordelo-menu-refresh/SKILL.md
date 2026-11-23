---
name: ordelo-menu-refresh
description: Refresh an Ordelo restaurant menu table (<rest_ref>_menu) against that restaurant's Deliveroo menu so ordering direct is visibly cheaper - Deliveroo list price becomes the struck-through price, our price becomes discounted_price, items Deliveroo no longer sells go out of stock, new Deliveroo items are inserted, and missing images are copied to S3. Use when asked to compare a menu with Deliveroo, undercut Deliveroo, refresh or re-price a menu, mark missing items unavailable, or mirror Deliveroo images to the ordelo-restaurants bucket.
---

# Ordelo menu refresh (undercut Deliveroo)

First used for BNAT (`plans/bnat-menu-undercut-plan.md`, worked folder
`notebooks/db_queries/restaurant_queries/onboarding_bnat/`). The scripts are generic; restaurant decisions live in that
restaurant's `menu_overrides.json`.

## Rules (do not change without the owner)

- **Ignore Deliveroo promotions.** Only the Deliveroo list `price` (plus a matched option's uplift) counts; their
  `discounted_price` ("20% off selected items") is not used.
- **Deliveroo dearer:** `price` = Deliveroo price, `discounted_price` = our price (text, two decimals). **Equal or
  cheaper:** no change, listed in the report.
- **Not on Deliveroo:** `availability = 'out of stock'` (storefront shows "Currently unavailable"). Never delete rows and
  never use `menu_item_hidden` for this.
- **New Deliveroo items:** inserted at the Deliveroo price, no discount, emojis removed, Title Case, `sku` = normalised
  title, category from the matched rows' mapping (or `category_map`), Deliveroo description, `addons` as
  `{stepN: {label, required, allow_multiple, options: [{name, price_modifier}]}}`; keep the table's own `branch_link`.
- **Images:** keep an existing `image_link`; otherwise copy the Deliveroo image to `s3://ordelo-restaurants/<ref>/<sku>.jpg`
  (`image/jpeg`, `public, max-age=31536000`). **Never overwrite an existing S3 key** (an existing key is linked as is).
- **Snapshot before apply,** ship SQL with a rollback, apply only after the owner says go. Removing inserted rows is a
  DELETE and needs its own explicit approval (database-operations skill).
- The web price audit (`utils_common/web_ordering/monitoring.py`, `MENU_FLOOR`) uses `discounted_price` when numeric,
  else `price`, so these menus do not raise false alerts.

## Folder layout (per restaurant)

```
<onboarding folder>/
  deliveroo/*.csv              capture from the deliveroo-menu-downloader skill
  menu_overrides.json          restaurant decisions (below)
  snapshots/<ref>_menu_<UTC>.json
  <ref>_menu_vs_deliveroo.csv  compare_menu.py
  images/manifest.csv          mirror_menu_images.py (images/out/ is gitignored)
  <ref>_menu_changes.csv, <ref>_menu_update.sql, <ref>_menu_rollback.sql   build_menu_update.py
```

`menu_overrides.json` keys (titles are matched after normalisation, emojis and case ignored):

| Key | Meaning |
|---|---|
| `reject` | table titles that must stay unmatched (go out of stock) even if the matcher finds something |
| `match` | table title -> `{"item": Deliveroo title, "options": [option names]}`; price = item + option uplifts |
| `accept_fuzzy` | fuzzy matches the owner accepted; other fuzzy matches are left unchanged ("review") |
| `no_insert` | Deliveroo-only items not to insert |
| `category_map` | Deliveroo category -> table category for inserts with no matched row (e.g. combos) |

## Steps

Shell: `source .venv/bin/activate; export PYTHONPATH="$PWD"; envLoad` (see `docs/local-testing-runbook.md`).
`S=.claude/skills/ordelo-menu-refresh/scripts`, `DIR=<onboarding folder>`.

1. **Capture** the Deliveroo menu into `$DIR/deliveroo/` with the deliveroo-menu-downloader skill if the last run is
   more than a few days old. If curl gets Cloudflare's "Just a moment" page, open the menu in the browser, POST
   `document.getElementById('__NEXT_DATA__').textContent` to a local receiver (e.g. a tiny `python3 -m http.server`-style
   handler writing `next_data.json`), then `node extract_file.js next_data.json <scratch>`; never hand-copy chunks. Put the
   page's offer text (e.g. "20% off selected items") into `--notes`.
2. **Snapshot** the live table (anon client, database-operations skill) to `$DIR/snapshots/<ref>_menu_<UTC>.json`.
3. **Compare:** `python3 $S/compare_menu.py --rest-ref <ref> --dir $DIR --db-json $DIR/snapshots/<file>`. Review every
   `fuzzy`, `via_option` and `db_only` row with the owner; record decisions in `menu_overrides.json`; re-run.
4. **Images:** `python3 $S/mirror_menu_images.py --rest-ref <ref> --dir $DIR --dry-run`, then without `--dry-run`. Failed
   rows keep their old `image_link`.
5. **Build:** `python3 $S/build_menu_update.py --rest-ref <ref> --dir $DIR`. Check the group counts it prints.
6. **Rehearse** update, guarded re-run and rollback on the isolated Postgres (ordelo-sql-test-db skill): create the table
   from `ordelo_datamodels/core/menus.sql`, load the snapshot with `OVERRIDING SYSTEM VALUE`, run the SQL files.
7. **Review gate:** show the owner the totals and a sample of `<ref>_menu_changes.csv`; wait for "go".
8. **Apply** `<ref>_menu_update.sql` as one script on a psycopg connection to `pg_settings` (it has its own
   BEGIN/COMMIT; the count checks raise and roll back if any row changed since the snapshot - then re-snapshot and rebuild).
9. **Verify:** re-select the table (counts per group, nothing deleted), every `image_link` returns 200,
   `MENU_API_URL?restaurant_name=<ref>` shows `discounted_price`, and a re-run of compare + build reports 0 updates.
10. **Commit** scripts, CSVs, SQL and overrides (no images, no secrets); put the Deliveroo run id in the message.

## Notes

- A bulk reload of the table from another source undoes the prices and out-of-stock flags; this skill is the refresh path.
- Re-running is safe: rows already undercut are left alone; a stale discount where Deliveroo became cheaper is removed.
- Matched rows that are out of stock are not brought back in stock automatically; do that by hand with the owner.
