"""Fit a full 2x3 affine mapping reflection -> object on the reference images."""
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


def make(f, L, band):
    d = blur(load(f), 2)
    Y, X = np.mgrid[0:N, 0:N].astype(np.float32)
    objn = lcn(np.where(Y < L - 1, d, 0.0))
    refn = lcn(np.where(Y > L + 1, d, 0.0))
    msk = (Y > L + 3) & (Y < L + band)
    b = refn[msk]; b = b - b.mean()
    return objn, refn, msk, b, b / np.sqrt((b * b).sum()), X, Y


def score(p, objn, msk, bn, X, Y, L):
    a, bb, c, dd, ex, ey = p
    qx, qy = X - N / 2, Y - L
    px = a * qx + bb * qy + N / 2 + ex
    py = c * qx + dd * qy + L + ey
    v = samp(objn, px, py)[msk]
    v = v - v.mean()
    n = np.sqrt((v * v).sum())
    return -1.0 if n < 1e-9 else float((v / n) @ bn)


def fit(f, L, band=46):
    objn, refn, msk, b, bn, X, Y = make(f, L, band)
    p = np.array([1.0, 0.0, 0.0, -1.25, 0.0, 0.0])
    best = score(p, objn, msk, bn, X, Y, L)
    steps = np.array([.08, .08, .08, .12, 6.0, 6.0])
    for _ in range(60):
        improved = False
        for i in range(6):
            for sgn in (1, -1):
                q = p.copy(); q[i] += sgn * steps[i]
                sc = score(q, objn, msk, bn, X, Y, L)
                if sc > best: best, p, improved = sc, q, True
        if not improved:
            steps *= 0.6
            if steps[4] < 0.05: break
    return best, p


if __name__ == '__main__':
    for f, L in [('221282.png', 690), ('222009.png', 690), ('222281.png', 690), ('222285.png', 720)]:
        sc, p = fit(f, L / F)
        a, bb, c, d, ex, ey = p
        M = np.array([[a, bb], [c, d]])
        fwd = np.linalg.inv(M)                     # object -> reflection
        sx = np.hypot(fwd[0, 0], fwd[1, 0]); sy = np.hypot(fwd[0, 1], fwd[1, 1])
        shear = np.degrees(np.arctan2(fwd[1, 0], fwd[0, 0]))
        print(f"{f}  NCC={sc:.3f}  contactY={L}")
        print(f"    inverse affine (reflection->object): "
              f"[{a:+.3f} {bb:+.3f}; {c:+.3f} {d:+.3f}]  offset=({ex*F:+.0f},{ey*F:+.0f})px")
        print(f"    forward: scaleX={sx:.3f}  scaleY={sy:.3f}  "
              f"x-axis tilt={shear:+.2f}deg  det={np.linalg.det(fwd):+.3f}")
