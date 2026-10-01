#!/usr/bin/env python3
"""Re-download plates where the fetcher grabbed the wrong pose.

Original rule: "first white-background gallery image". Some products lead with a
front-on or pure-side shot, so that picked the wrong one. New rule: score every
white-background candidate and take the best 3/4 view -- smallest aspect ratio
among those tall enough, which is what the reflection geometry needs.
"""
import csv, io, json, os, random, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_pids import gallery_for, get, is_plate

SRC = "Stock PIDs"


def shape(raw):
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    ink = (255 - a.min(axis=2)) > 110
    cs, rs = np.nonzero(ink.any(axis=0))[0], np.nonzero(ink.any(axis=1))[0]
    if not len(cs) or not len(rs):
        return None
    w, h = int(cs.max() - cs.min()), int(rs.max() - rs.min())
    if h < 10:
        return None
    return round(w / h, 2), h, im.size


def best_candidate(pid):
    _, urls, pdp = gallery_for(pid)
    cands = []
    for i, u in enumerate(urls[:6]):
        try:
            raw, _ = get(u)
            ok, _, _ = is_plate(raw)
            if not ok:
                continue
            s = shape(raw)
            if not s:
                continue
            asp, h, size = s
            cands.append(dict(idx=i, url=u, aspect=asp, h=h, raw=raw, size=size))
        except Exception:
            continue
    if not cands:
        return None, pdp, cands
    good = [c for c in cands if c["aspect"] <= 3.05 and c["h"] >= 320]
    if good:                       # prefer a true 3/4: tallest, then narrowest
        good.sort(key=lambda c: (-c["h"], c["aspect"]))
        return good[0], pdp, cands
    return None, pdp, cands


def one(pid):
    try:
        best, pdp, cands = best_candidate(pid)
    except Exception as e:
        return dict(pid=pid, result="error", note=f"{type(e).__name__}: {e}")
    if not best:
        return dict(pid=pid, result="no-3/4-in-gallery",
                    note=f"{len(cands)} white plates, none 3/4")
    d = os.path.join(SRC, pid)
    old = [f for f in os.listdir(d) if not f.endswith(".json")]
    ext = os.path.splitext(best["url"].split("?")[0])[1].lower() or ".jpg"
    bak = os.path.join(d, "_wrong-pose")
    os.makedirs(bak, exist_ok=True)
    for f in old:                                   # keep the old one, don't destroy
        os.replace(os.path.join(d, f), os.path.join(bak, f))
    tmp = os.path.join(d, pid + ext + ".part")
    with open(tmp, "wb") as fh:
        fh.write(best["raw"])
    os.replace(tmp, os.path.join(d, pid + ext))
    meta = json.load(open(os.path.join(d, f"{pid}.json")))
    meta.update(image=best["url"], galleryIndex=best["idx"],
                repicked="3/4 view", aspect=best["aspect"], frameHeight=best["h"])
    json.dump(meta, open(os.path.join(d, f"{pid}.json"), "w"), indent=2)
    return dict(pid=pid, result="replaced", gallery_index=best["idx"],
                aspect=best["aspect"], frame_h=best["h"])


def main():
    pids = json.load(open("QC 1/wrong-pose-pids.json"))
    print(f"re-fetching {len(pids)} wrong-pose PIDs with 4 workers ...", flush=True)
    rows, t0 = [], time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(one, p): p for p in pids}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result(); rows.append(r)
            if i % 25 == 0 or r["result"] != "replaced":
                el = time.time() - t0
                print(f"[{i}/{len(pids)}] {r['pid']} {r['result']} "
                      f"{r.get('note','')} (eta {(len(pids)-i)/(i/el)/60:.1f}m)", flush=True)
            time.sleep(0.4)
    with open("QC 1/refetch-report.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["pid","result","gallery_index","aspect",
                                           "frame_h","note"], extrasaction="ignore")
        w.writeheader(); w.writerows(sorted(rows, key=lambda r: r["pid"]))
    from collections import Counter
    print("\n" + str(dict(Counter(r["result"] for r in rows))))


if __name__ == "__main__":
    main()
