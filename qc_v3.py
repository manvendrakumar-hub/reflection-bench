#!/usr/bin/env python3
"""QC for the tuned (v3) render.

temple_thk is GONE as a criterion. The tuned finish settings -- steep fade curve,
heavy blur switching on late, wide split feather -- dissolve the front/temple
seam, so thick acetate temples no longer split into "two parts". Verified by
re-rendering the exact PIDs a reviewer labelled as that failure.

What remains is genuine geometry: a plate that was never a 3/4 view (angle 0),
detection that failed (negative angle), or a subject too small/flat/offset.
"""
import csv, json, os
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
from PIL import Image

OUT = os.environ.get("REFL_OUT", "Reflection Bench Output V3")


def measure(pid):
    """Never let one unreadable file abort the scan -- a single zero-byte PNG
    from a partial write killed a full 2211-image run."""
    try:
        return _measure(pid)
    except Exception as e:
        return dict(pid=pid, angle=0, frame_h=0, aspect=0, split_rel=0, refl_ink=0,
                    **{"pass": False}, fails=f"unreadable:{type(e).__name__}", conf=-1.0)


def _measure(pid):
    d = os.path.join(OUT, pid)
    cp = os.path.join(d, f"{pid}-config.json")
    if not os.path.exists(cp):
        return None
    cfg = json.load(open(cp))
    F, S = cfg["front"], cfg["split"]
    srcs = [f for f in os.listdir(d)
            if not f.endswith(".json") and "reflection" not in f]
    if not srcs:
        return None
    si = 255 - np.asarray(Image.open(os.path.join(d, srcs[0])).convert("RGB")
                          ).astype(np.int16).min(axis=2)
    st = si > 110
    cols = np.nonzero(st.any(axis=0))[0]
    rows = np.nonzero(st.any(axis=1))[0]
    if not len(cols) or not len(rows):
        return None
    x0, x1, y0, y1 = cols.min(), cols.max(), rows.min(), rows.max()
    w, h = int(x1 - x0), int(y1 - y0)
    if h < 10:
        return None

    # is there actually reflection ink below the contact line?
    o = 255 - np.asarray(Image.open(os.path.join(d, f"{pid}-reflection.png")
                                    ).convert("RGB")).astype(np.int16).min(axis=2)
    m = np.tan(np.radians(F["angle"]))
    H, W = o.shape
    below = []
    for x in range(0, W, 3):
        y = int(F["pivotY"] + m * (x - F["pivotX"]))
        if 0 < y < H - 60:
            below.append(o[y + 6:y + 60, x].mean())
    refl = float(np.mean(below)) if below else 0.0

    r = dict(pid=pid, angle=F["angle"], frame_h=h, aspect=round(w / h, 2),
             split_rel=round((S["x"] - x0) / w, 3), refl_ink=round(refl, 2))
    fails = []
    if not (9.5 <= r["angle"] <= 12.5):            fails.append("angle")
    if h < 320:                                     fails.append("short")
    if r["aspect"] > 3.10:                          fails.append("aspect")
    if not (0.65 <= r["split_rel"] <= 0.73):        fails.append("split")
    if refl < 0.35:                                 fails.append("no-reflection")
    r["pass"] = not fails
    r["fails"] = ";".join(fails)
    r["conf"] = round(1 - max(abs(r["angle"] - 10.75) / 3.0,
                              abs(r["aspect"] - 2.55) / 0.7,
                              abs(r["split_rel"] - 0.69) / 0.06), 3)
    return r


def main():
    pids = sorted(d for d in os.listdir(OUT) if os.path.isdir(os.path.join(OUT, d)))
    rows = []
    with ProcessPoolExecutor(max_workers=os.cpu_count()) as ex:
        for f in as_completed([ex.submit(measure, p) for p in pids]):
            r = f.result()
            if r:
                rows.append(r)
    rows.sort(key=lambda r: -r["conf"])
    ok = [r for r in rows if r["pass"]]
    print(f"scanned {len(rows)}   passing {len(ok)}  ({len(ok)/len(rows)*100:.1f}%)")
    with open("QC 1/v3-scan.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pid","pass","conf","angle","frame_h",
                                           "aspect","split_rel","refl_ink","fails"])
        w.writeheader(); w.writerows(rows)
    from collections import Counter
    c = Counter(f for r in rows for f in r["fails"].split(";") if f)
    print("failures:", dict(c.most_common()))
    print("top 10:", [r["pid"] for r in ok[:10]])
    json.dump([r["pid"] for r in ok[:10]],
              open(os.path.join("QC 1", "v3-top10.json"), "w"))


if __name__ == "__main__":
    main()
