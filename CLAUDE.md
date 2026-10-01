# Reflection Bench v2

Adds a physically-correct glass-surface reflection to eyewear product shots by
**geometry only**. No generative model, no repainted pixels, no LLM anywhere in
the pipeline. The reflection is a warped, masked copy of the original subject
composited underneath it. Source images are never modified.

Built for Lenskart-style product plates: a frame on a pure-white ground,
square, 1024² or 1080².

**This runs entirely offline.** Nothing here calls Claude, an API, or a browser.
The only step that touches the network is `fetch_pids.py`, which downloads
plates from Lenskart — skip it if you already have the images.

---

## Run it

```bash
pip install -r requirements.txt        # numpy, pillow, openpyxl

./run_offline.sh reflect               # render everything in "Stock PIDs"
./run_offline.sh fetch                 # download plates for PIDs in the sheet
./run_offline.sh all                   # fetch then reflect
./run_offline.sh serve                 # HTTP service on :8080
```

`run_offline.sh` with no argument prints usage — it deliberately does **not**
default to `all`, because `all` is a ~50 minute network job.

If `python3` on PATH lacks numpy/pillow, point at one that has them:
`PY=/usr/local/bin/python3 ./run_offline.sh reflect`. On the machine this was
built on, the Homebrew `python3` has neither; `/usr/local/bin/python3` does.

### As a service

```bash
python3 reflect_server.py --port 8080          # stdlib only, no Flask

curl -X POST --data-binary @frame.jpg -H 'Content-Type: image/jpeg' \
     http://localhost:8080/reflect -o out.png
curl "http://localhost:8080/reflect?opacity=0.3&blur=8" ...   # finish overrides
curl http://localhost:8080/health
```

The response carries the resolved config in an `X-Reflection-Config` header, so
every render is reproducible. Server output is **bit-identical** to batch output
(verified: max channel difference 0).

### Interactive tuning

`reflection-bench.html` — open in any browser, no server. Drag an image on,
**Auto-detect contacts**, adjust, **Export PNG**. Use it to find settings; the
batch and server paths use the same maths.

---

## The one thing to understand

**A reflection's displacement depends on how high each point sits above the
glass.** A 2D image has no height channel, so *no single 2D warp can reflect a
whole pair of glasses* — two points at the same place in the image can sit at
different heights and must move by different amounts.

The frame front **rests on its lens rims**. The temple touches **only at its
tip** and climbs away toward the hinge. Different heights → different mirrors.
So the tool runs **two independent mirrors** and blends them at a split.

Established by fitting, not assumed. See "Rejected models" — don't re-derive them.

### The mirror is oblique, not perpendicular

Points drop **straight down** onto the contact line. They do **not** reflect
perpendicular to it. Pivot-local:

```
qx = x
qy = m(1 + s)·x  −  s·y            m = tan(contactAngle), s = depth
```

i.e. the plain affine `matrix(1, m(1+s), 0, −s, 0, 0)` about the pivot. Every
point *on* the contact line maps to itself, so the lens rims and the temple tip
each touch their own reflection with no tuning.

---

## Measured constants

From the four reference renders in `correct/` (ground truth — real product
renders, not our output):

| part | contact angle | depth | fit quality (NCC) |
|---|---|---|---|
| front | **+10.0° ± 0.9** | **1.00 ± 0.02** | 0.59 |
| temple | **−33.2° ± 1.6** | **1.53** | 0.60 – 0.78 |

Fade envelope: peak opacity **≈0.40** at the contact line, zero by **≈260 px**.

Strongest evidence: the temple fit was given **no** hint where the tip was, and
its contact line came back through **(970, 451)**. The tip measures **(970, 445)**.

## Rejected models — do not retry

| model | result | why it fails |
|---|---|---|
| vertical flip about a horizontal line | gaps under the far rim | ignores the 3/4 view |
| **orthogonal** mirror about a tilted line | fitted matrices are asymmetric | orthogonal reflection is forced to be symmetric; the data is not |
| vertical squash (depth 0.5) | — | measured depth is 1.00; there is no squash |
| single 8-DOF homography | NCC 0.01 – 0.25 | cannot encode per-point height |
| harmonic homology (4-DOF projective mirror) | NCC 0.12 – 0.25 | same reason |

No usable prior art: published work is either reflection *removal* or
diffusion-based generation (MirrorFusion, DEROBA), and the latter repaints
pixels, which this project rules out.

---

## Files

```
run_offline.sh            Entry point. fetch | reflect | serve | all.
batch_reflect.py          Batch renderer. Multiprocess, no browser. THE workhorse.
reflect_server.py         HTTP wrapper (stdlib only). POST /reflect.
render_reflection.py      The pipeline itself + auto_contact() detection.
reflection-bench.html     Interactive tuner. Standalone, offline.
fetch_pids.py             Downloads plates from Lenskart for PIDs in the sheet.
requirements.txt          numpy, pillow, openpyxl.

Shadow Remaining PIDs.xlsx   Source list. "Overall" minus "Shadow PIDs" = to do.
Stock PIDs/<PID>/         Downloaded plates + per-PID .json + manifest.csv.
Reflection Bench Output V2/  Rendered output, one folder per PID.
correct/                     Ground-truth references. Do not edit.
test/                        Assorted frames for testing.
research/                    The fitting scripts that produced the constants.
AUDIT.md                     Signed agent-audit trail of the derivation.
```

## Pipeline order

`matte → brightness/contrast → oblique warp → screen-space blur → fade mask →
composite under the untouched original`

The HTML, the batch renderer and the server all implement this identically.
Browser vs headless parity was measured on 10 real plates: mean absolute
difference **0.11–0.39 of 255**, geometry identical; the residual is only the
gaussian-blur kernel differing between canvas and PIL.

## What happens per image

1. `auto_contact()` finds the **front** contact line — sweeps the angle and
   takes the lower support line touching the silhouette in the most places,
   scored on hits, span and closeness to the measured ~10°.
2. It finds the **temple** tip — lowest ink in the outermost columns — and holds
   the measured −33°.
3. The split is placed between them; each side gets its own mirror.
4. A sanity gate flags `reflection-missing`, `runs-off-canvas`, `no-room-below`.

Geometry is per-image. The **finish** (opacity, fade, curve, blur, depth,
angles) comes from `render_reflection.PART_DEFAULTS` — the measured Reference
preset — so every image gets the same look. Change it there, or per-request via
server query params.

---

## Results so far

- 2,325 PIDs remaining in the sheet; 2,211 plates downloaded, **114 are 404 on
  Lenskart** (delisted) — listed in `Stock PIDs/failed_pids.csv`.
- All 2,211 rendered: **2,210 clean, 1 flagged**, 5.3 min at 0.14 s/image on
  8 workers.
- The flagged one (`243622`) is a clear crystal frame whose reflection is faint
  *because the subject is near-transparent*. Correct behaviour, not a defect.

## Conventions and gotchas

- **Never modify the source image.** Every output is a new file.
- **Presets change surface finish only.** Geometry is measured, not styled.
- **White cut** (default 6) discards near-white noise before matting. Required
  for JPEG sources; harmless on clean PNGs.
- The matte assumes a **pure white background**, recovering alpha as
  `255 − min(r,g,b)`. It will not work on a coloured or gradient ground.
- **Front-on poses detect 0.0° and that is correct** — a front-facing frame's
  bottom silhouette genuinely is horizontal, and there's no temple sweeping
  sideways. Not a failure; don't "fix" it.
- Only the **near** temple is handled. In all four references the far temple's
  reflection is hidden behind the frame. The structure supports a third part.
- **Do not use an extension allowlist for source images.** An earlier allowlist
  silently skipped 7 `.gif` PIDs while reporting success — the worst kind of
  failure. `source_for()` now asks Pillow what it can open.
- `reflection-bench.html` carries **no `<head>` tags and no charset meta** (it
  doubles as a Claude Artifact, which supplies the wrapper). Every non-ASCII
  character must therefore be escaped (`\uXXXX` in JS, `&#NNN;` in markup) or it
  renders as mojibake from `file://`.
- Element IDs are shared between rail sections and SVG guide lines; they once
  collided (`gFront`) and sliders vanished into an SVG `<line>`. Guides are now
  `lnFront` / `lnTemple` / `lnSplit`.

## Verification

Check geometry changes against `correct/` the way the constants were derived:
strip a reference's own reflection, regenerate from config, compare.
`research/oblique.py` is the harness.

When fitting, **normalise the whole frame before masking**. Thresholding first
destroys the anti-aliased structure that carries the correlation and collapses
NCC to ~0 — that bug cost real time.
