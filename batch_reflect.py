#!/usr/bin/env python3
"""Batch-apply the reflection to downloaded PID plates. No browser, no LLM.

Geometry is detected per image (auto_contact, ported from the bench's JS and
verified identical on real plates). The finish -- opacity, fade, curve, blur,
depth, contact angles -- comes from the measured Reference preset baked into
render_reflection.PART_DEFAULTS, so every image gets the same look.

    python3 batch_reflect.py --limit 10
    python3 batch_reflect.py --all --workers 8
    python3 batch_reflect.py --pids 137002,234792

Output: "Reflection Bench Output V2/<PID>/" containing the source image,
<PID>-reflection.png and <PID>-config.json.
"""
import argparse
import csv
import json
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_reflection import (PART_DEFAULTS, SPLIT_DEFAULTS, FINISH_DEFAULTS,
                               auto_contact, render)

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT, "Stock PIDs")
OUT_DIR = os.path.join(ROOT, os.environ.get("REFL_OUT", "Reflection Bench Output V3"))


def source_for(pid):
    """Any image the folder holds, not a fixed extension list.

    An allowlist silently skipped 7 .gif PIDs on the first full run -- the run
    reported success while dropping them. Ask Pillow what it can open instead,
    so a .tiff/.avif/.bmp never falls through the same trap. (.gif here is a
    3-frame animation cycling a badge detail; frame 0 is a normal plate and
    Image.open returns frame 0 by default.)"""
    d = os.path.join(SRC_DIR, pid)
    if not os.path.isdir(d):
        return None
    cands = sorted(f for f in os.listdir(d)
                   if not f.lower().endswith(".json") and not f.startswith("."))
    preferred = (".jpg", ".jpeg", ".png", ".webp", ".gif")
    cands.sort(key=lambda f: (os.path.splitext(f)[1].lower() not in preferred, f))
    for f in cands:
        path = os.path.join(d, f)
        try:
            with Image.open(path) as im:
                im.verify()
            return path
        except Exception:
            continue
    return None


def check(out_path, front_y):
    """Cheap sanity gate: did a reflection actually land, below the frame,
    without running off the canvas? Flags the handful worth a manual look."""
    a = np.asarray(Image.open(out_path).convert("RGB")).astype(np.int16)
    H, W, _ = a.shape
    ink = 255 - a.min(axis=2)
    band = ink[int(front_y) + 8:, :]                 # strictly below the contact
    if band.size == 0:
        return "no-room-below"
    frac = float((band > 8).mean())
    if frac < 0.002:
        return "reflection-missing"
    if float((ink[-3:, :] > 8).mean()) > 0.25:
        return "runs-off-canvas"
    return "ok"


def one(pid):
    src = source_for(pid)
    if not src:
        return dict(pid=pid, status="no-source")
    dest = os.path.join(OUT_DIR, pid)
    os.makedirs(dest, exist_ok=True)
    out_png = os.path.join(dest, f"{pid}-reflection.png")

    try:
        f_over, t_over, split_x = auto_contact(Image.open(src))
        if not f_over:
            return dict(pid=pid, status="no-contact-found")

        cfg = {
            "front": {**PART_DEFAULTS["front"], **f_over},
            "temple": {**PART_DEFAULTS["temple"], **t_over},
            "split": {**SPLIT_DEFAULTS, **({"x": split_x} if split_x else {})},
            "finish": dict(FINISH_DEFAULTS),
        }
        tmp = out_png + ".part"                      # atomic: never leave a partial PNG
        render(cfg, src, tmp, auto=False, fmt="PNG")  # geometry already resolved
        os.replace(tmp, out_png)

        shutil.copy(src, os.path.join(dest, os.path.basename(src)))
        cfg_out = {"pid": pid, "source": os.path.basename(src),
                   "model": "two-part oblique mirror", **cfg}
        json.dump(cfg_out, open(os.path.join(dest, f"{pid}-config.json"), "w"), indent=2)

        return dict(pid=pid, status=check(out_png, cfg["front"]["pivotY"]),
                    front=f"{f_over['pivotX']:.0f},{f_over['pivotY']:.0f}@{f_over['angle']}",
                    temple=f"{t_over['pivotX']:.0f},{t_over['pivotY']:.0f}")
    except Exception as e:
        return dict(pid=pid, status="error", note=f"{type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--pids", default=None)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    args = ap.parse_args()

    if args.pids:
        pids = [p.strip() for p in args.pids.split(",") if p.strip()]
    else:
        have = sorted(d for d in os.listdir(SRC_DIR)
                      if os.path.isdir(os.path.join(SRC_DIR, d)))
        try:                                          # prefer the sheet's own order
            from fetch_pids import remaining_pids
            order = [p for p in remaining_pids() if p in set(have)]
        except Exception:
            order = have
        pids = order if args.all else order[args.start:args.start + args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"reflecting {len(pids)} image(s) on {args.workers} workers...")
    t0 = time.time()
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(one, p): p for p in pids}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            rows.append(r)
            el = time.time() - t0
            eta = (len(pids) - i) / (i / el) if el > 0 else 0
            print(f"[{i}/{len(pids)}] {r['pid']:>8}  {r['status']:<18} "
                  f"{r.get('front','')}  {r.get('note','')}   (eta {eta/60:.1f}m)"[:150])

    man = os.path.join(OUT_DIR, "manifest.csv")
    keys = ["pid", "status", "front", "temple", "note"]
    new = not os.path.exists(man)
    with open(man, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["pid"]))

    el = time.time() - t0
    ok = sum(1 for r in rows if r["status"] == "ok")
    print(f"\n{ok}/{len(rows)} clean in {el/60:.1f} min ({el/max(len(rows),1):.2f}s/image)")
    for r in rows:
        if r["status"] != "ok":
            print(f"  ! {r['pid']}: {r['status']} {r.get('note','')}")


if __name__ == "__main__":
    main()
