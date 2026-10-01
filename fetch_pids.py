#!/usr/bin/env python3
"""Download the primary white-background product plate for Lenskart PIDs.

`https://www.lenskart.com/product/<PID>` redirects to the real PDP, whose
__NEXT_DATA__ carries the full gallery. Gallery entry 0 is normally the 3/4
plate on white -- the exact input Reflection Bench expects. Not always, though,
so each candidate is checked for a white ground and the first one that passes
is kept; the index actually used is recorded in the manifest.

    python3 fetch_pids.py --limit 5                 # first 5 not yet downloaded
    python3 fetch_pids.py --limit 100 --start 5
    python3 fetch_pids.py --pids 137002,234792

Output: "Stock PIDs/<PID>/<PID>.<ext>" plus <PID>.json per product,
and a manifest.csv across the run.
"""
import argparse
import csv
import io
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(ROOT, "Stock PIDs")
SHEET = os.path.join(ROOT, "Shadow Remaining PIDs.xlsx")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
NEXT_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.S)


def get(url, timeout=40):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,*/*",
        "Accept-Language": "en-IN,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.geturl()


def remaining_pids():
    """Overall PIDs that are not in the already-has-shadow sheet, in sheet order."""
    import openpyxl
    wb = openpyxl.load_workbook(SHEET, read_only=True, data_only=True)

    def col(name):
        out = []
        for i, row in enumerate(wb[name].iter_rows(values_only=True)):
            if i == 0 or row[0] is None:
                continue
            v = row[0]
            out.append(str(int(v)) if isinstance(v, float) else str(v).strip())
        return out

    done = set(col("Shadow PIDs"))
    return [p for p in dict.fromkeys(col("Overall")) if p not in done]


def gallery_for(pid):
    """(product name, [image urls in gallery order], resolved pdp url)."""
    html, final = get(f"https://www.lenskart.com/product/{pid}")
    m = NEXT_RE.search(html.decode("utf-8", "replace"))
    if not m:
        raise RuntimeError("no __NEXT_DATA__ on page")
    data = json.loads(m.group(1))
    results = data["props"]["pageProps"]["data"]["productDetailData"]["result"]
    prod = next((r["data"] for r in results
                 if isinstance(r, dict) and isinstance(r.get("data"), dict)
                 and r["data"].get("galleryWidget")), None)
    if prod is None:
        raise RuntimeError("no product block in __NEXT_DATA__")
    urls = [it["imageUrl"] for it in prod["galleryWidget"]["data"]
            if it.get("type") == "IMAGE" and it.get("imageUrl")]
    name = " ".join(str(prod.get(k, "")) for k in ("brandName", "modelName"))
    name = name.replace("\u00a0", " ").strip()   # NBSP in some brand names
    return name or prod.get("productTitle", ""), urls, final


def is_plate(raw):
    """A product plate sits on a white ground. Model shots and lifestyle do not."""
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    h, w, _ = a.shape
    corners = np.concatenate([a[:8, :8].reshape(-1, 3), a[:8, -8:].reshape(-1, 3),
                              a[-8:, :8].reshape(-1, 3), a[-8:, -8:].reshape(-1, 3)])
    white_frac = float((a.min(axis=2) > 245).mean())
    return (corners.min() > 244 and white_frac > 0.45), im.size, round(white_frac, 3)


def fetch_one(pid, pause):
    dest = os.path.join(OUTDIR, pid)
    os.makedirs(dest, exist_ok=True)
    existing = [f for f in os.listdir(dest) if f.startswith(pid + ".")
                and not f.endswith(".json")]
    if existing:
        return dict(pid=pid, status="skipped", file=existing[0], note="already present")

    name, urls, pdp = gallery_for(pid)
    if not urls:
        return dict(pid=pid, status="no-images", pdp=pdp)

    for idx, url in enumerate(urls[:6]):
        try:
            raw, _ = get(url)
            ok, size, frac = is_plate(raw)
        except Exception as e:
            continue
        if not ok:
            time.sleep(pause * 0.3)
            continue
        ext = os.path.splitext(url.split("?")[0])[1].lower() or ".jpg"
        fname = pid + ext
        with open(os.path.join(dest, fname), "wb") as f:
            f.write(raw)
        json.dump({"pid": pid, "product": name, "pdp": pdp,
                   "image": url, "galleryIndex": idx,
                   "size": list(size), "whiteFraction": frac},
                  open(os.path.join(dest, pid + ".json"), "w"), indent=2)
        return dict(pid=pid, status="ok", file=fname, gallery_index=idx,
                    size=f"{size[0]}x{size[1]}", white=frac, product=name, pdp=pdp)

    return dict(pid=pid, status="no-white-plate", pdp=pdp, note=f"{len(urls)} images, none on white")


_manifest_lock = threading.Lock()
_progress_lock = threading.Lock()
_done_count = [0]


def _worker(pid, pause):
    """Each thread staggers its own requests; N threads => ~N x throughput
    since the work is I/O-bound (network latency), not CPU-bound."""
    try:
        r = fetch_one(pid, pause)
    except Exception as e:
        r = dict(pid=pid, status="error", note=f"{type(e).__name__}: {e}")
    time.sleep(pause + random.uniform(0, 0.5))
    return r


def _append_manifest(rows):
    man = os.path.join(OUTDIR, "manifest.csv")
    keys = ["pid", "status", "file", "gallery_index", "size", "white", "product", "pdp", "note"]
    with _manifest_lock:
        new = not os.path.exists(man)
        with open(man, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--pids", default=None, help="comma-separated, overrides the sheet")
    ap.add_argument("--pause", type=float, default=1.2, help="seconds between a thread's own requests")
    ap.add_argument("--workers", type=int, default=4, help="concurrent threads")
    args = ap.parse_args()

    pids = ([p.strip() for p in args.pids.split(",") if p.strip()] if args.pids
            else remaining_pids()[args.start:args.start + args.limit])
    os.makedirs(OUTDIR, exist_ok=True)
    total = len(pids)
    print(f"fetching {total} PID(s) with {args.workers} workers...")

    rows = []
    batch = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_worker, pid, args.pause): pid for pid in pids}
        for fut in as_completed(futures):
            r = fut.result()
            rows.append(r)
            batch.append(r)
            with _progress_lock:
                _done_count[0] += 1
                n = _done_count[0]
            elapsed = time.time() - t0
            rate = n / elapsed if elapsed > 0 else 0
            eta = (total - n) / rate if rate > 0 else 0
            print(f"[{n}/{total}] {r['pid']:>8}  {r['status']:<14} "
                  f"{r.get('file','') or r.get('note','')}  {r.get('product','')}"
                  f"   (eta {eta/60:.1f}m)"[:170])
            if len(batch) >= 20:
                _append_manifest(batch)
                batch = []
    if batch:
        _append_manifest(batch)

    done = sum(1 for r in rows if r["status"] == "ok")
    elapsed = time.time() - t0
    print(f"\n{done}/{len(rows)} downloaded -> {OUTDIR}   ({elapsed/60:.1f} min total)")
    for r in rows:
        if r["status"] not in ("ok", "skipped"):
            print(f"  ! {r['pid']}: {r['status']} {r.get('note','')}")


if __name__ == "__main__":
    main()
