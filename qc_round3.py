#!/usr/bin/env python3
"""Round-3 selector: only images we are CONFIDENT are correct.

Calibrated against 10 human-labelled examples (round 2). Those labels showed the
QC-1 gate was measuring the wrong things -- it passed all 10 while only 2 were
truly right. These five criteria reproduce the human verdict exactly on that set.

  angle      front contact angle. 0deg means a FRONT-ON plate was scraped
             instead of the 3/4 view -- the wrong source image, not a valid
             pose. Negative means detection failed outright.
  frame_h    subject height. Short frames sit outside the geometry the
             constants were measured on.
  aspect     width/height. >3 means an unusually flat or cropped pose.
  temple_thk THE key signal. Thick acetate temples make the -33deg temple
             mirror render a heavy slab that will not visually join the front
             reflection -- the "looks like two separate parts" failure.
  split_rel  where the split falls across the frame. Off-centre means the
             front/temple division landed in the wrong place.
"""
import csv, json, os, sys
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "Reflection Bench Output V2")

ANGLE_LO, ANGLE_HI = 9.5, 12.5
FRAME_H_MIN = 350
ASPECT_MAX = 2.85
TEMPLE_THK_MAX = 20.0
SPLIT_REL_LO, SPLIT_REL_HI = 0.65, 0.73


def measure(pid):
    d = os.path.join(OUT, pid)
    cfgp = os.path.join(d, f"{pid}-config.json")
    if not os.path.exists(cfgp):
        return None
    cfg = json.load(open(cfgp))
    F, S = cfg["front"], cfg["split"]
    srcs = [f for f in os.listdir(d)
            if not f.endswith(".json") and "reflection" not in f]
    if not srcs:
        return None
    si = 255 - np.asarray(Image.open(os.path.join(d, srcs[0])).convert("RGB")
                          ).astype(np.int16).min(axis=2)
    strong = si > 110
    cols = np.nonzero(strong.any(axis=0))[0]
    rows = np.nonzero(strong.any(axis=1))[0]
    if not len(cols) or not len(rows):
        return None
    x0, x1, y0, y1 = cols.min(), cols.max(), rows.min(), rows.max()
    w, h = int(x1 - x0), int(y1 - y0)
    if h < 10:
        return None
    xs = int(S["x"])
    tem = strong[:, xs:]
    occ = tem.any(axis=0).sum()
    thk = float(tem.sum()) / max(occ, 1)

    m = dict(pid=pid, angle=F["angle"], frame_h=h,
             aspect=round(w / h, 2), temple_thk=round(thk, 1),
             split_rel=round((S["x"] - x0) / w, 3))
    fails = []
    if not (ANGLE_LO <= m["angle"] <= ANGLE_HI):     fails.append(f"angle {m['angle']}")
    if m["frame_h"] < FRAME_H_MIN:                    fails.append(f"short {m['frame_h']}")
    if m["aspect"] > ASPECT_MAX:                      fails.append(f"aspect {m['aspect']}")
    if m["temple_thk"] > TEMPLE_THK_MAX:              fails.append(f"thick temple {m['temple_thk']}")
    if not (SPLIT_REL_LO <= m["split_rel"] <= SPLIT_REL_HI): fails.append(f"split {m['split_rel']}")
    m["pass"] = not fails
    m["fails"] = "; ".join(fails)
    # confidence: distance from the centre of every accepted band
    m["conf"] = round(1 - max(
        abs(m["angle"] - 10.75) / 3.0,
        abs(m["aspect"] - 2.55) / 0.7,
        m["temple_thk"] / TEMPLE_THK_MAX,
        abs(m["split_rel"] - 0.69) / 0.06), 3)
    return m


def main():
    pids = sorted(d for d in os.listdir(OUT) if os.path.isdir(os.path.join(OUT, d)))
    rows = []
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        for i, f in enumerate(as_completed([ex.submit(measure, p) for p in pids]), 1):
            r = f.result()
            if r: rows.append(r)
            if i % 500 == 0: print(f"  {i}/{len(pids)}")
    rows.sort(key=lambda r: -r["conf"])
    ok = [r for r in rows if r["pass"]]
    print(f"\nscanned {len(rows)}  |  confident-correct {len(ok)} ({len(ok)/len(rows)*100:.1f}%)")
    with open(os.path.join(ROOT, "QC 1", "round3-scan.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pid","pass","conf","angle","frame_h",
                                           "aspect","temple_thk","split_rel","fails"])
        w.writeheader(); w.writerows(rows)
    from collections import Counter
    c = Counter()
    for r in rows:
        for f_ in r["fails"].split("; "):
            if f_: c[f_.split()[0] + " " + (f_.split()[1] if f_.split()[0]=="thick" else "")] += 1
    print("\nwhy the rest fail:")
    for k, v in c.most_common(8): print(f"  {k:<16} {v}")
    return ok


if __name__ == "__main__":
    main()
