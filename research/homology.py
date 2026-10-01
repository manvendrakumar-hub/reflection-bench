"""Fit a HARMONIC HOMOLOGY (a true projective mirror) to the reference renders.

    H = I - 2 (V a^T)/(a^T V)

  axis a   - the contact line. Every point on it is fixed, so the lens rims AND
             the temple tips all touch their own reflection.
  vertex V - the vanishing point of the vertical direction. Every point slides
             toward V, by an amount that grows with its height off the glass.

Four parameters, H^2 = I exactly, so it is a genuine mirror rather than a warp
that happens to look like one.
"""
from PIL import Image
import numpy as np

F = 2
N = 1024 // F


def box(a, r):
    if r < 1: return a
    c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), 'edge'), 0)
    a = (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)
    c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), 'edge'), 1)
    return (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)


def blur(a, r): return box(box(box(a, r), r), r)
def lcn(a, r=5): return a / (np.sqrt(np.maximum(blur(a * a, r), 1e-6)) + 0.8)


def load(f):
    d = 255 - np.asarray(Image.open(f).convert('RGB')).astype(np.float32).min(axis=2)
    return np.asarray(Image.fromarray(d).resize((N, N), Image.BILINEAR))


def samp(s, xs, ys):
    x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
    fx, fy = xs - x0, ys - y0
    ok = (x0 >= 0) & (x0 + 1 < N) & (y0 >= 0) & (y0 + 1 < N)
    xa, xb = np.clip(x0, 0, N - 1), np.clip(x0 + 1, 0, N - 1)
    ya, yb = np.clip(y0, 0, N - 1), np.clip(y0 + 1, 0, N - 1)
    t = s[ya, xa] * (1 - fx) + s[ya, xb] * fx
    b = s[yb, xa] * (1 - fx) + s[yb, xb] * fx
    return (t * (1 - fy) + b * fy) * ok


def prep(f):
    """Normalise the whole frame once; the mask only selects which pixels score.
    Thresholding before normalising destroys the anti-aliased structure that
    actually carries the correlation."""
    d = blur(load(f), 1)
    dn = lcn(d)
    strong = blur((d > 120).astype(np.float32), 3) > 0.02
    refmask = (d > 8) & (d < 100) & (~strong)
    return dn, dn, refmask


def H_of(p):
    y0, phi, vx, vy = p
    n = np.array([-np.sin(np.radians(phi)), np.cos(np.radians(phi))])
    a = np.array([n[0], n[1], -(n[0] * (N / 2) + n[1] * y0)])
    V = np.array([vx, vy, 1.0])
    den = a @ V
    if abs(den) < 1e-9: return None
    return np.eye(3) - 2.0 * np.outer(V, a) / den


def fit(f, init, iters=260):
    objn, refn, msk = prep(f)
    Y, X = np.mgrid[0:N, 0:N].astype(np.float32)
    b = refn[msk]; b = b - b.mean(); b = b / np.sqrt((b * b).sum())
    xs, ys = X[msk], Y[msk]

    def sc(p):
        H = H_of(p)
        if H is None: return -1.0
        w = H[2, 0] * xs + H[2, 1] * ys + H[2, 2]
        w = np.where(np.abs(w) < 1e-6, 1e-6, w)
        px = (H[0, 0] * xs + H[0, 1] * ys + H[0, 2]) / w
        py = (H[1, 0] * xs + H[1, 1] * ys + H[1, 2]) / w
        v = samp(objn, px, py)
        v = v - v.mean(); n = np.sqrt((v * v).sum())
        return -1.0 if n < 1e-9 else float((v / n) @ b)

    # multi-start: the landscape is rough, one descent gets stuck
    cands = []
    for dy in (-30, 0, 30):
        for dphi in (-10, -5, 0, 5, 10):
            for vy in (900, 1600, 3000, 6000, 20000):
                for vx in (-400, 256, 900):
                    q = np.array([init[0]+dy, init[1]+dphi, vx, vy/F], float)
                    cands.append((sc(q), q))
    cands.sort(key=lambda t: -t[0])
    p = cands[0][1].copy()
    best = cands[0][0]
    step = np.array([8.0, 4.0, 120.0, 400.0])
    for _ in range(iters):
        moved = False
        for i in range(4):
            for s in (1, -1):
                q = p.copy(); q[i] += s * step[i]
                v = sc(q)
                if v > best: best, p, moved = v, q, True
        if not moved:
            step *= 0.6
            if step[0] < 0.05: break
    return best, p


if __name__ == '__main__':
    # axis y at image centre (full px), axis angle, vertex (full px)
    INIT = {'221282.png': (719, -31, 512, 3000),
            '222009.png': (700, -28, 512, 3000),
            '222281.png': (700, -25, 512, 3000),
            '222285.png': (730, -25, 512, 3000)}
    for f, ini in INIT.items():
        i = (ini[0] / F, ini[1], ini[2] / F, ini[3] / F)
        ncc, p = fit(f, i)
        y0, phi, vx, vy = p
        print(f"{f}  NCC={ncc:.3f}   axis: y({N//2*F})={y0*F:7.1f}px  angle={phi:+7.2f}deg"
              f"   vertex=({vx*F:9.0f},{vy*F:9.0f})px")
