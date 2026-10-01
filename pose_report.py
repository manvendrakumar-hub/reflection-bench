#!/usr/bin/env python3
"""Classify the pose of every downloaded plate.

The fetcher took the first white-background gallery image, which is usually the
3/4 view but not always -- some products lead with a front-on or pure-side shot.
Pose separates cleanly on the subject's bounding box:

    3/4 view   aspect ~2.2-3.0, tall  (~370-410px)   <- what the tool needs
    front-on   aspect ~3.4-4.0, short (~240-290px)
    side-on    aspect >4.0,     short
"""
import csv, json, os
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from PIL import Image

SRC = "Stock PIDs"


def pose_of(aspect, h):
    if aspect <= 3.05 and h >= 320:
        return "3/4 view"
    if aspect > 3.9:
        return "side-on"
    return "front-on"


def measure(pid):
    d = os.path.join(SRC, pid)
    try:
        f = [x for x in os.listdir(d) if not x.endswith(".json")][0]
        a = np.asarray(Image.open(os.path.join(d, f)).convert("RGB")).astype(np.int16)
        ink = (255 - a.min(axis=2)) > 110
        cs, rs = np.nonzero(ink.any(axis=0))[0], np.nonzero(ink.any(axis=1))[0]
        if not len(cs) or not len(rs):
            return None
        w, h = int(cs.max() - cs.min()), int(rs.max() - rs.min())
        if h < 10:
            return None
        asp = round(w / h, 2)
        meta = json.load(open(os.path.join(d, f"{pid}.json")))
        return dict(pid=pid, pose=pose_of(asp, h), aspect=asp, frame_h=h,
                    gallery_index=meta.get("galleryIndex", ""),
                    product=meta.get("product", ""), pdp=meta.get("pdp", ""))
    except Exception as e:
        return dict(pid=pid, pose="unreadable", aspect=0, frame_h=0,
                    gallery_index="", product="", pdp="", note=str(e))


def main():
    pids = sorted(d for d in os.listdir(SRC) if os.path.isdir(os.path.join(SRC, d)))
    rows = []
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        for f in as_completed([ex.submit(measure, p) for p in pids]):
            r = f.result()
            if r:
                rows.append(r)
    rows.sort(key=lambda r: (r["pose"], r["pid"]))
    with open("QC 1/pose-report.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pid","pose","aspect","frame_h",
                                           "gallery_index","product","pdp"],
                           extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    from collections import Counter
    c = Counter(r["pose"] for r in rows)
    print(f"scanned {len(rows)} downloaded plates\n")
    for k, v in c.most_common():
        print(f"  {k:<12} {v:>5}  ({v/len(rows)*100:.1f}%)")
    bad = [r for r in rows if r["pose"] != "3/4 view"]
    b1 = {d for d in os.listdir("Batch 1") if os.path.isdir(os.path.join("Batch 1", d))}
    print(f"\nwrong pose: {len(bad)}   of which already in Batch 1: "
          f"{len([r for r in bad if r['pid'] in b1])}")
    json.dump([r["pid"] for r in bad], open("QC 1/wrong-pose-pids.json", "w"))


if __name__ == "__main__":
    main()
