#!/usr/bin/env python3
"""Render a reflection PNG from a Reflection Bench config.

Two-part oblique mirror. A reflection's displacement depends on how high each
point sits above the glass, so one 2D warp cannot serve a whole pair of glasses:
the frame front rests on its lens rims while the temple touches only at its tip.
Each part therefore gets its own contact line and its own depth, and the split
decides which part of the object each mirror is allowed to see.

Measured across the four reference renders in correct/:
    front    contact +10 deg, depth 1.00
    temple   contact -33 deg, depth 1.53

    python3 render_reflection.py config.json -i frame.png -o out.png
    pbpaste | python3 render_reflection.py - -o out.png
"""
import argparse
import json
import sys

import numpy as np
from PIL import Image, ImageFilter

PART_DEFAULTS = {
    # Tuned by hand on 134953 (2026-09-16). The seam between the front and temple
    # mirrors is hidden by the FINISH, not by geometry: a steep fade curve plus
    # heavy blur that only switches on late (blurAt 0.76) keeps the contact edge
    # crisp while the junction further down dissolves. Wide split feather (155)
    # completes the blend. pitch -19.5 tips the front plane so the reflection
    # sits tight under the frame instead of running long.
    "front":  dict(pivotX=517.0, pivotY=684.0, angle=10.0, depth=0.93,
                   roll=0.0, pitch=-19.5, yaw=1.0,
                   opacity=0.50, fade=225.0, curve=2.65, blur=12.0, blurAt=0.76),
    # Temple fade must TRACK the front's, not outlive it. With fade 420 / curve
    # 1.10 the temple stayed dark well past where the front had faded out, and
    # the split boundary showed as a hard step at the junction. Matching the
    # profile (shorter fade, steeper curve, same heavy blur) removes it.
    "temple": dict(pivotX=983.0, pivotY=465.0, angle=-33.0, depth=1.53,
                   roll=0.0, pitch=0.0, yaw=0.0,
                   opacity=0.45, fade=260.0, curve=2.40, blur=12.0, blurAt=0.60),
}
SPLIT_DEFAULTS = dict(x=700.0, angle=1.5, feather=155.0, perspective=2200.0)
FINISH_DEFAULTS = dict(feather=1.5, whiteCut=5.0, brightness=0.93, contrast=1.0)


def normal(angle_deg):
    """Unit normal of a line at `angle_deg`, pointing into the reflection."""
    t = np.radians(angle_deg)
    return -np.sin(t), np.cos(t)


def matte(img, white_cut=6.0):
    """Un-premultiply the subject off its white ground (same as the bench).

    white_cut discards the near-white noise a JPEG leaves behind, which would
    otherwise haze the whole plate."""
    rgb = np.asarray(img.convert("RGB")).astype(np.float32)
    a = 255.0 - rgb.min(axis=2)
    a = np.where(a <= white_cut, 0.0, (a - white_cut) * 255.0 / (255.0 - white_cut))
    a = a / 255.0
    k = np.maximum(a, 1e-6)[..., None]
    return np.clip((rgb - (1.0 - k) * 255.0) / k, 0, 255), a


def split_alpha(sp, W, H, part):
    """Which half of the OBJECT this mirror may see, with a feathered seam."""
    nx, ny = normal(90.0 + sp["angle"])
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    d = (X - sp["x"]) * nx + (Y - H / 2.0) * ny
    f = max(sp["feather"], 1e-6)
    front = np.clip((d + f) / f, 0.0, 1.0)
    return front if part == "front" else 1.0 - front


def _rx(d):
    c, n = np.cos(np.radians(d)), np.sin(np.radians(d))
    return np.array([[1,0,0,0],[0,c,-n,0],[0,n,c,0],[0,0,0,1]], float)


def _ry(d):
    c, n = np.cos(np.radians(d)), np.sin(np.radians(d))
    return np.array([[c,0,n,0],[0,1,0,0],[-n,0,c,0],[0,0,0,1]], float)


def _rz(d):
    c, n = np.cos(np.radians(d)), np.sin(np.radians(d))
    return np.array([[c,-n,0,0],[n,c,0,0],[0,0,1,0],[0,0,0,1]], float)


def part_homography(pp, persp):
    """Persp . Rz(roll) . Rx(pitch) . Ry(yaw) . Oblique, as a 3x3 on the z=0
    plane in pivot-local coords. Pitch/yaw tip the part out of the page, which
    an affine cannot express -- hence the homography."""
    s = pp["depth"]
    k = np.tan(np.radians(pp["angle"])) * (1.0 + s)
    O = np.array([[1,0,0,0],[k,-s,0,0],[0,0,1,0],[0,0,0,1]], float)
    M = _rz(pp.get("roll", 0.0)) @ _rx(pp.get("pitch", 0.0)) @ _ry(pp.get("yaw", 0.0)) @ O
    return np.array([
        [M[0,0], M[0,1], M[0,3]],
        [M[1,0], M[1,1], M[1,3]],
        [-M[2,0]/persp, -M[2,1]/persp, 1.0 - M[2,3]/persp],
    ], float)


def warp(col, alpha, pp, W, H, persp=2200.0):
    ox, oy = pp["pivotX"], pp["pivotY"]
    Hi = np.linalg.inv(part_homography(pp, persp))

    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    vx, vy = X - ox, Y - oy
    w = Hi[2,0]*vx + Hi[2,1]*vy + Hi[2,2]
    w = np.where(np.abs(w) < 1e-9, 1e-9, w)
    u = (Hi[0,0]*vx + Hi[0,1]*vy + Hi[0,2]) / w + ox
    v = (Hi[1,0]*vx + Hi[1,1]*vy + Hi[1,2]) / w + oy

    x0, y0 = np.floor(u).astype(np.int32), np.floor(v).astype(np.int32)
    fx, fy = (u - x0)[..., None], (v - y0)[..., None]
    ok = (x0 >= 0) & (x0 + 1 < W) & (y0 >= 0) & (y0 + 1 < H)
    xa, xb = np.clip(x0, 0, W - 1), np.clip(x0 + 1, 0, W - 1)
    ya, yb = np.clip(y0, 0, H - 1), np.clip(y0 + 1, 0, H - 1)

    pre = np.concatenate([col * alpha[..., None], alpha[..., None]], axis=2)
    top = pre[ya, xa] * (1 - fx) + pre[ya, xb] * fx
    bot = pre[yb, xa] * (1 - fx) + pre[yb, xb] * fx
    return (top * (1 - fy) + bot * fy) * ok[..., None]


def fade_alpha(pp, feather, W, H, soft):
    """Screen-space falloff away from this part's contact line."""
    nx, ny = normal(pp["angle"])
    Y, X = np.mgrid[0:H, 0:W].astype(np.float32)
    d = (X - pp["pivotX"]) * nx + (Y - pp["pivotY"]) * ny

    t = np.clip(d / pp["fade"], 0.0, 1.0)
    w = np.clip((t - pp["blurAt"]) / max(1.0 - pp["blurAt"], 1e-6), 0.0, 1.0)
    a = np.power(1.0 - t, pp["curve"]) * (w if soft else 1.0 - w)
    a = np.where(d > pp["fade"], 0.0, a)
    if feather > 0:
        a = a * np.clip((d + feather) / feather, 0.0, 1.0)
    else:
        a = np.where(d < 0, 0.0, a)
    return np.clip(a, 0.0, 1.0)


def auto_contact(img):
    """Port of autoContact() from reflection-bench.html.

    FRONT  the resting plane is the line touching the silhouette from below in
           the most places; sweep the angle and score hits, span and closeness
           to the measured ~10 deg constant.
    TEMPLE only the tip touches, so take the lowest ink in the outermost
           columns and hold the measured -33 deg constant.

    Returns (front_overrides, temple_overrides, split_x).
    """
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    H, W, _ = rgb.shape
    ink = 255 - rgb.min(axis=2)
    # A fixed ink>110 test misses the real lower edge of pale / transparent
    # frames, so the mirror line landed INSIDE them (seen on production plates:
    # up to 74px deep). Scale the threshold to the frame's own darkness. Dark
    # frames (p90 ink ~230) still use 110, so their geometry is unchanged.
    subj = ink > 14
    if subj.any():
        thr = float(np.clip(0.5 * np.percentile(ink[subj], 90), 24, 110))
    else:
        thr = 110.0
    strong = ink > thr

    bottom = np.full(W, -1, dtype=np.int64)
    ys, xs = np.nonzero(strong)
    if not len(xs):
        return {}, {}, None
    np.maximum.at(bottom, xs, ys)                   # lowest strong row per column
    cols = np.nonzero(bottom >= 0)[0]

    best = None
    for deg in np.arange(-4.0, 24.0001, 0.25):
        m = np.tan(np.radians(deg))
        c = float((bottom[cols] - m * cols).max())   # lower support line
        hit = np.abs(bottom[cols] - (m * cols + c)) <= 3
        hits = int(hit.sum())
        if not hits:
            continue
        hc = cols[hit]
        lo, hi = int(hc.min()), int(hc.max())
        sc = hits + (hi - lo) * 0.05 - abs(deg - 10) * 0.9
        if best is None or sc > best[0]:
            best = (sc, float(deg), m, c, hi)

    front = {}
    if best:
        _, deg, m, c, hi = best
        front = {"pivotX": float(hi), "pivotY": float(round(m * hi + c)),
                 "angle": round(deg, 2)}

    tip_x = int(cols.max())
    win = max(20, round(W * 0.04))
    bx, by = tip_x, int(bottom[tip_x])
    for x in range(max(0, tip_x - win), tip_x + 1):
        if bottom[x] > by:
            by, bx = int(bottom[x]), x
    temple = {"pivotX": float(bx), "pivotY": float(by), "angle": -33.0}

    split = None
    if front:
        split = float(round(bx - (bx - front["pivotX"]) * 0.62))
    return front, temple, split


def front_bitangent(img, split_x=None, ink_min=18, ang_lo=0.0, ang_hi=20.0):
    """Physical contact line of the frame FRONT: glasses resting on glass touch
    at two points (both lens bottoms), so the mirror line is the edge of the
    LOWER convex hull of the silhouette that spans the widest. Uses faint ink
    so a rimless lens edge counts -- the darkest-ink line anchored on nose pads
    (228431) and touched only one lens (236564). Returns (pivotX, pivotY, angle)
    or None."""
    a = np.asarray(img.convert("RGB")).astype(np.int16)
    ink = 255 - a.min(axis=2)
    H, W = ink.shape
    sub = ink > ink_min
    xs_all = np.nonzero(sub.any(axis=0))[0]
    if not len(xs_all):
        return None
    lim = int(split_x) if split_x else W
    pts = []
    for x in range(int(xs_all.min()), min(lim, W)):
        ys = np.nonzero(sub[:, x])[0]
        if len(ys):
            pts.append((x, int(ys.max())))
    if len(pts) < 10:
        return None
    # lower hull in image coords (y grows downward): keep the points of max y
    hull = []
    for p in pts:
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            if (x2 - x1) * (p[1] - y1) - (y2 - y1) * (p[0] - x1) >= 0:
                hull.pop()
            else:
                break
        hull.append(p)
    best = None
    for (x1, y1), (x2, y2) in zip(hull, hull[1:]):
        if x2 == x1:
            continue
        ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        span = x2 - x1
        if ang_lo <= ang <= ang_hi and (best is None or span > best[0]):
            best = (span, x2, y2, ang)
    if not best:
        return None
    return float(best[1]), float(best[2]), round(best[3], 2)


def render(cfg, src_path, out_path, auto=False, fmt=None):
    parts, sp, fin = {}, dict(SPLIT_DEFAULTS), dict(FINISH_DEFAULTS)
    for name, base in PART_DEFAULTS.items():
        p = dict(base)
        p.update({k: float(v) for k, v in (cfg.get(name) or {}).items() if k in base})
        parts[name] = p
    sp.update({k: float(v) for k, v in (cfg.get("split") or {}).items() if k in sp})
    fin.update({k: float(v) for k, v in (cfg.get("finish") or {}).items() if k in fin})

    img = Image.open(src_path)
    W, H = img.size

    if auto:
        # geometry per image; the finish (opacity/fade/blur/depth) stays as given
        f_over, t_over, split_x = auto_contact(img)
        parts["front"].update(f_over)
        parts["temple"].update(t_over)
        if split_x is not None:
            sp["x"] = split_x
    col, alpha = matte(img, fin["whiteCut"])

    adj = np.clip(col * fin["brightness"], 0, 255)
    adj = np.clip((adj / 255.0 - 0.5) * fin["contrast"] + 0.5, 0, 1) * 255.0

    out = np.full((H, W, 3), 255.0, np.float32)
    for name in ("front", "temple"):
        pp = parts[name]
        src_a = alpha * split_alpha(sp, W, H, name)
        layer = warp(adj, src_a, pp, W, H, sp["perspective"])

        rgba = np.concatenate([layer[..., :3], layer[..., 3:4] * 255.0], axis=2)
        rgba = np.clip(rgba, 0, 255).astype(np.uint8)
        soft = (np.asarray(Image.fromarray(rgba).filter(
                ImageFilter.GaussianBlur(pp["blur"]))) if pp["blur"] > 0 else rgba)

        for is_soft in (False, True):
            lay = (soft if is_soft else rgba).astype(np.float32)
            m = (fade_alpha(pp, fin["feather"], W, H, is_soft) * pp["opacity"])[..., None]
            out = out * (1.0 - (lay[..., 3:4] / 255.0) * m) + lay[..., :3] * m

    out = out * (1.0 - alpha[..., None]) + col * alpha[..., None]
    im_out = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    im_out.save(out_path, format=fmt) if fmt else im_out.save(out_path)
    if isinstance(out_path, str):
        print(f"wrote {out_path}  ({W}x{H})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("config", help="JSON from the bench, or - for stdin")
    ap.add_argument("-i", "--image", default="identity-composite.png")
    ap.add_argument("-o", "--out", default="identity-composite-reflected.png")
    ap.add_argument("--auto", action="store_true",
                    help="detect contact points from the image instead of using the config's")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.config == "-" else open(args.config).read()
    render(json.loads(raw), args.image, args.out, auto=args.auto)
