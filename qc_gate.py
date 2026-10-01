#!/usr/bin/env python3
"""QC-1 gate for rendered reflections. Three measured parameters, one verdict.

Runs on the OUTPUT alone (plus its config), so it works as a post-render gate
with no reference image needed.

    P1 ADHESION   does the reflection actually touch the frame at the contact
                  line, or does it float? For each column where the frame has
                  ink just above the line, is there ink just below it?
    P2 DENSITY    reflection ink relative to frame ink. Too faint reads as
                  missing, too strong reads as a second product.
    P3 CONTAINMENT does it stay in bounds -- not clipped by the canvas edge,
                  not bleeding back up over the product?

Verdict:  correct | can-be-better | incorrect

    python3 qc_gate.py --sample 400
    python3 qc_gate.py --pids 137002,243622
"""
import argparse
import csv
import json
import os
import random
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "Reflection Bench Output V2")

# Thresholds. Tuned on the measured reference look (peak opacity ~0.40).
ADH_GOOD, ADH_POOR = 0.80, 0.45
DENS_LO, DENS_HI = 0.10, 0.55           # acceptable band
DENS_DEAD = 0.03                        # below this the reflection is invisible
CONT_GOOD, CONT_POOR = 0.02, 0.10
FRAME_INK_MIN = 8.0     # below this the frame is too pale for a ratio to mean anything
REFL_INK_MIN = 0.35     # absolute floor: is there any reflection ink at all


def ink_of(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    return 255 - a.min(axis=2)


def score(pid):
    d = os.path.join(OUT_DIR, pid)
    out = os.path.join(d, f"{pid}-reflection.png")
    cfgp = os.path.join(d, f"{pid}-config.json")
    if not (os.path.exists(out) and os.path.exists(cfgp)):
        return dict(pid=pid, verdict="missing")

    cfg = json.load(open(cfgp))
    f = cfg["front"]
    ink = ink_of(out)
    H, W = ink.shape
    m = np.tan(np.radians(f["angle"]))
    px, py = f["pivotX"], f["pivotY"]
    xs = np.arange(W)
    line = (py + m * (xs - px)).astype(int)          # contact line per column

    # ---- P1 adhesion: ink just above vs just below the line, per column
    above = np.zeros(W, bool)
    below = np.zeros(W, bool)
    for x in range(W):
        y = line[x]
        if 12 < y < H - 12:
            above[x] = (ink[max(0, y - 14):y - 1, x] > 40).any()
            below[x] = (ink[y + 1:y + 15, x] > 6).any()
    n = int(above.sum())
    adhesion = float((above & below).sum() / n) if n else 0.0

    # ---- P2 density: reflection band vs frame band
    band_f, band_r = [], []
    for x in range(W):
        y = line[x]
        if 60 < y < H - 60:
            band_f.append(ink[max(0, y - 120):y - 2, x])
            band_r.append(ink[y + 2:min(H, y + 122), x])
    fm = float(np.mean([b.mean() for b in band_f])) if band_f else 0.0
    rm = float(np.mean([b.mean() for b in band_r])) if band_r else 0.0
    # The ratio divides by frame ink, so on a pale frame the denominator
    # collapses and the ratio becomes noise -- it was measuring frame paleness,
    # not reflection quality. Only trust it when there is real signal above the
    # line; otherwise fall back to an absolute presence test.
    ratio_valid = fm >= FRAME_INK_MIN
    density = (rm / fm) if ratio_valid else float("nan")
    present = rm >= REFL_INK_MIN

    # ---- P3 containment: clipped at the bottom, or spilling above the line
    containment = float((ink[-3:, :] > 8).mean())   # ink touching the canvas floor

    # ---- verdict
    bad  = (adhesion < ADH_POOR) or (not present) or (containment > CONT_POOR)
    dens_ok = (DENS_LO <= density <= DENS_HI) if ratio_valid else present
    good = (adhesion >= ADH_GOOD) and dens_ok and (containment <= CONT_GOOD)
    verdict = "incorrect" if bad else ("correct" if good else "can-be-better")

    reasons = []
    if adhesion < ADH_POOR:       reasons.append(f"reflection detached ({adhesion:.2f})")
    elif adhesion < ADH_GOOD:     reasons.append(f"partial contact ({adhesion:.2f})")
    if not present:               reasons.append(f"no reflection ink (abs {rm:.2f})")
    elif ratio_valid and density < DENS_LO:  reasons.append(f"too faint ({density:.3f})")
    elif ratio_valid and density > DENS_HI:  reasons.append(f"too strong ({density:.3f})")
    if containment > CONT_POOR:   reasons.append(f"clipped at canvas edge ({containment:.3f})")
    elif containment > CONT_GOOD: reasons.append(f"near canvas edge ({containment:.3f})")

    return dict(pid=pid, verdict=verdict,
                adhesion=round(adhesion, 3),
                density=(round(density, 3) if ratio_valid else ""),
                frame_ink=round(fm, 2), refl_ink=round(rm, 2),
                containment=round(containment, 4),
                angle=f["angle"], reasons="; ".join(reasons))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--pids", default=None)
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.pids:
        pids = [p.strip() for p in args.pids.split(",") if p.strip()]
    else:
        allp = sorted(d for d in os.listdir(OUT_DIR)
                      if os.path.isdir(os.path.join(OUT_DIR, d)))
        random.seed(11)
        pids = allp if args.sample >= len(allp) else random.sample(allp, args.sample)

    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(score, p) for p in pids]
        for i, fut in enumerate(as_completed(futs), 1):
            rows.append(fut.result())
            if i % 50 == 0:
                print(f"  scored {i}/{len(pids)}")

    rows.sort(key=lambda r: r["pid"])
    from collections import Counter
    c = Counter(r["verdict"] for r in rows)
    print(f"\nQC-1 over {len(rows)} PIDs:")
    for k in ("correct", "can-be-better", "incorrect", "missing"):
        if c[k]:
            print(f"  {k:<15} {c[k]:>5}  ({c[k]/len(rows)*100:.1f}%)")

    if args.out:
        keys = ["pid", "verdict", "adhesion", "density", "frame_ink", "refl_ink",
                "containment", "angle", "reasons"]
        with open(args.out, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote {args.out}")
    return rows


if __name__ == "__main__":
    main()
