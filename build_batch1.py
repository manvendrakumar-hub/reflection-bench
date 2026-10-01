#!/usr/bin/env python3
"""Re-render everything on the corrected default, QC it, and fill Batch 1 to 1000.

The temple fade fix (opacity .45 / fade 260 / curve 2.40) changed the default,
so every image must be re-rendered -- otherwise Batch 1 would mix two looks.
Delivery folders carry reflection + config + qc only, never the source image.
"""
import csv, json, os, shutil, subprocess, sys, time

ROOT = os.path.dirname(os.path.abspath(__file__))
TARGET = 1000

t0 = time.time()
if "--skip-render" not in sys.argv:
    print("[1/3] re-rendering all PIDs on the corrected default ...", flush=True)
    r = subprocess.run([sys.executable, "-u", "batch_reflect.py", "--all", "--workers", "8"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = [l for l in r.stdout.splitlines() if not l.startswith("wrote ")][-3:]
    print("   " + " | ".join(tail), flush=True)
else:
    print("[1/3] skipped (render already complete)", flush=True)

print(f"[2/3] QC scan ... ({time.time()-t0:.0f}s)", flush=True)
subprocess.run([sys.executable, "qc_v3.py"], cwd=ROOT, check=True)

print(f"[3/3] selecting top {TARGET} ... ({time.time()-t0:.0f}s)", flush=True)
rows = [r for r in csv.DictReader(open(os.path.join(ROOT, "QC 1/v3-scan.csv")))
        if r["pass"] == "True"]
rows.sort(key=lambda r: -float(r["conf"]))
pick = rows[:TARGET]

B = os.path.join(ROOT, "Batch 1")
src_root = os.path.join(ROOT, "Reflection Bench Output V3")
os.makedirs(B, exist_ok=True)
keep = {r["pid"] for r in pick}

# drop any existing folder no longer in the top 1000
for d in list(os.listdir(B)):
    p = os.path.join(B, d)
    if os.path.isdir(p) and d not in keep:
        shutil.rmtree(p)

for r in pick:
    pid = r["pid"]
    d = os.path.join(B, pid)
    os.makedirs(d, exist_ok=True)
    shutil.copy(os.path.join(src_root, pid, f"{pid}-reflection.png"),
                os.path.join(d, f"{pid}-reflection.png"))
    shutil.copy(os.path.join(src_root, pid, f"{pid}-config.json"),
                os.path.join(d, f"{pid}-config.json"))
    json.dump(r, open(os.path.join(d, f"{pid}-qc.json"), "w"), indent=2)
    # belt and braces: never ship the source image
    for fn in os.listdir(d):
        if not fn.endswith(".json") and "reflection" not in fn:
            os.remove(os.path.join(d, fn))

with open(os.path.join(B, "batch1-manifest.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["pid","conf","angle","frame_h","aspect",
                                      "split_rel","refl_ink"], extrasaction="ignore")
    w.writeheader(); w.writerows(pick)

n = len([d for d in os.listdir(B) if os.path.isdir(os.path.join(B, d))])
print(f"\nBatch 1: {n} PIDs   ({time.time()-t0:.0f}s total)")
print(f"confidence range: {pick[-1]['conf']} .. {pick[0]['conf']}")
