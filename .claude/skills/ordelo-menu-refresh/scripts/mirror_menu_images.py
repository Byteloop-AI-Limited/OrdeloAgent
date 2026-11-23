"""
Copy missing menu images from Deliveroo's CDN to s3://ordelo-restaurants/<rest_ref>/<sku>.jpg, never overwriting a key.
    . Dependencies: stdlib (argparse, csv, os, subprocess, sys, urllib); the aws CLI (credentials from the shell);
      build_menu_update.image_candidates (same folder) decides which rows need an image
    . Candidates: matched rows (D2/D3) with no image_link plus every row to be inserted (D7); choice-matched rows use the
      parent Deliveroo item's photo, one S3 copy per row
    . For each candidate:
      - aws s3api head-object finds the key -> status exists (never overwritten; build_menu_update links it)
      - download the Deliveroo URL to <dir>/images/out/<sku>.jpg; require HTTP 200, image/jpeg and more than 1 KB
      - aws s3 cp with Content-Type image/jpeg and Cache-Control public, max-age=31536000 -> status uploaded
      - the public URL must return 200; any failure -> status failed (that row's image_link stays unchanged)
    . Writes <dir>/images/manifest.csv (sku, source_url, s3_key, status, bytes); --dry-run writes status pending
  Usage
    . python3 mirror_menu_images.py --rest-ref bnat --dir <onboarding folder> [--dry-run]
  Functions/Classes
    . s3_exists
    . download
    . upload
    . public_ok
    . mirror_one
    . main
"""

import argparse
import csv
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_menu_update import BUCKET, image_candidates, load_inputs, s3_url  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)"}
FIELDS = ["sku", "source_url", "s3_key", "status", "bytes"]


def s3_exists(key):
    r = subprocess.run(["aws", "s3api", "head-object", "--bucket", BUCKET, "--key", key], capture_output=True, text=True)
    if r.returncode == 0:
        return True
    if "Not Found" in r.stderr or "404" in r.stderr:
        return False
    raise RuntimeError(f"head-object {key}: {r.stderr.strip()}")


def download(url, path):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as resp:
        ctype = resp.headers.get("Content-Type", "")
        body = resp.read()
        if resp.status != 200 or not ctype.startswith("image/jpeg") or len(body) <= 1024:
            raise RuntimeError(f"bad download: status={resp.status} type={ctype} bytes={len(body)}")
    with open(path, "wb") as f:
        f.write(body)
    return len(body)


def upload(path, key):
    subprocess.run(["aws", "s3", "cp", path, f"s3://{BUCKET}/{key}", "--content-type", "image/jpeg",
                    "--cache-control", "public, max-age=31536000", "--only-show-errors"], check=True)


def public_ok(url):
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status == 200


def mirror_one(ref, sku, source, out_dir, dry_run):
    key = f"{ref}/{sku}.jpg"
    row = {"sku": sku, "source_url": source, "s3_key": key, "status": "pending", "bytes": ""}
    if dry_run:
        return row
    try:
        if s3_exists(key):
            row["status"] = "exists"
            return row
        path = os.path.join(out_dir, f"{sku}.jpg")
        row["bytes"] = download(source, path)
        upload(path, key)
        row["status"] = "uploaded" if public_ok(s3_url(ref, sku)) else "failed"
    except Exception as exc:
        print(f"failed {sku}: {exc}", file=sys.stderr)
        row["status"] = "failed"
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--rest-ref", required=True)
    ap.add_argument("--dir", default=".")
    ap.add_argument("--snapshot")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    ref = args.rest_ref.lower()
    img_dir = os.path.join(args.dir, "images")
    out_dir = os.path.join(img_dir, "out")
    os.makedirs(out_dir, exist_ok=True)
    inp = load_inputs(ref, args.dir, args.snapshot)
    rows = [mirror_one(ref, sku, src, out_dir, args.dry_run) for sku, src in image_candidates(inp)]
    with open(os.path.join(img_dir, "manifest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print({"candidates": len(rows), **counts})


if __name__ == "__main__":
    main()
