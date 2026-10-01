"""Fit the OBLIQUE (vertical-shear) mirror: points drop straight down onto a
tilted contact line, rather than reflecting perpendicular to it.

    contact line:  L(x) = L0 + m*(x - 512)
    object -> reflection:  qy = L(x) - s*(py - L(x)),  qx = px
"""
from PIL import Image
import numpy as np

F = 4
N = 1024 // F


def box(a, r):
    if r < 1: return a
    c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), 'edge'), 0)
    a = (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)
    c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), 'edge'), 1)
    return (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)


def blur(a, r): return box(box(box(a, r), r), r)
def lcn(a, r=6): return a / (np.sqrt(np.maximum(blur(a * a, r), 1e-6)) + 0.8)


def load(f):
    d = 255 - np.asarray(Image.open(f).convert('RGB')).astype(np.float32).min(axis=2)
    return np.asarray(Image.fromarray(d).resize((N, N), Image.BILINEAR))


def samp(src, xs, ys):
    x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
    fx, fy = xs - x0, ys - y0
    ok = (x0 >= 0) & (x0 + 1 < N) & (y0 >= 0) & (y0 + 1 < N)
    xa, xb = np.clip(x0, 0, N - 1), np.clip(x0 + 1, 0, N - 1)
    ya, yb = np.clip(y0, 0, N - 1), np.clip(y0 + 1, 0, N - 1)
    t = src[ya, xa] * (1 - fx) + src[ya, xb] * fx
    b = src[yb, xa] * (1 - fx) + src[yb, xb] * fx
    return (t * (1 - fy) + b * fy) * ok


def fit(f, L0, band=70):
    d = blur(load(f), 2)
    Y, X = np.mgrid[0:N, 0:N].astype(np.float32)
    dn = lcn(d)

    def sc(p):
        L, m, s = p
        lam = L + m * (X - N / 2)
        py = lam - (Y - lam) / s
        objn = np.where(dn * 0 + Y < 0, 0, dn)          # full frame; mask does the work
        v = samp(objn, X, py)
        msk = (Y > lam + 3) & (Y < lam + band) & (py < lam - 1)
        a = v[msk]; b = dn[msk]
        if a.size < 500: return -1.0
        a = a - a.mean(); b = b - b.mean()
        na, nb = np.sqrt((a * a).sum()), np.sqrt((b * b).sum())
        return -1.0 if na < 1e-9 or nb < 1e-9 else float((a @ b) / (na * nb))

    p = np.array([L0 / F, 0.20, 1.0])
    best = sc(p)
    step = np.array([2.0, 0.05, 0.15])
    for _ in range(90):
        moved = False
        for i in range(3):
            for g in (1, -1):
                q = p.copy(); q[i] += g * step[i]
                if q[2] < 0.15: continue
                v = sc(q)
                if v > best: best, p, moved = v, q, True
        if not moved:
            step *= 0.62
            if step[0] < 0.05: break
    return best, p


if __name__ == '__main__':
    rows = []
    for f, L0 in [('221282.png', 690), ('222009.png', 690),
                  ('222281.png', 690), ('222285.png', 720)]:
        ncc, (L, m, s) = fit(f, L0)
        ang = np.degrees(np.arctan(m))
        rows.append((L * F, ang, s))
        print(f"{f}  NCC={ncc:.3f}  contactY@512={L*F:6.1f}  "
              f"groundAngle={ang:+6.2f}deg  scaleY={s:.3f}")
    a = np.array(rows)
    print(f"\nMEAN  contactY={a[:,0].mean():.0f}  groundAngle={a[:,1].mean():+.2f}deg  "
          f"scaleY={a[:,2].mean():.3f}   (sd {a[:,1].std():.2f}deg / {a[:,2].std():.3f})")
