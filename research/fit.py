"""Recover the object->reflection transform from a finished reference image."""
from PIL import Image
import numpy as np

F = 4                                    # work at 256x256


def box(a, r):
    if r < 1: return a
    c = np.cumsum(np.pad(a, ((r + 1, r), (0, 0)), 'edge'), 0)
    a = (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)
    c = np.cumsum(np.pad(a, ((0, 0), (r + 1, r)), 'edge'), 1)
    return (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)


def blur(a, r):
    return box(box(box(a, r), r), r)


def load(f):
    d = 255 - np.asarray(Image.open(f).convert('RGB')).astype(np.float32).min(axis=2)
    return np.asarray(Image.fromarray(d).resize((1024 // F, 1024 // F), Image.BILINEAR))


def samp(src, xs, ys):
    H, W = src.shape
    x0, y0 = np.floor(xs).astype(int), np.floor(ys).astype(int)
    fx, fy = xs - x0, ys - y0
    ok = (x0 >= 0) & (x0 + 1 < W) & (y0 >= 0) & (y0 + 1 < H)
    xa, xb = np.clip(x0, 0, W - 1), np.clip(x0 + 1, 0, W - 1)
    ya, yb = np.clip(y0, 0, H - 1), np.clip(y0 + 1, 0, H - 1)
    t = src[ya, xa] * (1 - fx) + src[ya, xb] * fx
    b = src[yb, xa] * (1 - fx) + src[yb, xb] * fx
    return (t * (1 - fy) + b * fy) * ok


def lcn(a, r=6):
    """Local contrast normalisation - divides out the fade envelope."""
    return a / (np.sqrt(np.maximum(blur(a * a, r), 1e-6)) + 1.0)


def fit(d, Ls, Ths, Ss, band=40):
    """Mirror about y = L + tan(th)(x-N/2), compressed by s along the normal."""
    N = d.shape[0]
    Y, X = np.mgrid[0:N, 0:N].astype(np.float32)
    db = blur(d, 2)
    best = None
    for L in Ls:
        obj = np.where(Y < L - 1, db, 0.0)
        ref = lcn(np.where(Y > L + 1, db, 0.0))
        msk = (Y > L + 3) & (Y < L + band)
        b = ref[msk]; b = b - b.mean(); bn = np.sqrt((b * b).sum())
        if bn < 1e-6: continue
        for th in Ths:
            t = np.radians(th)
            tx, ty = np.cos(t), np.sin(t)
            nx, ny = -np.sin(t), np.cos(t)
            qx, qy = X - N / 2, Y - L
            tan = qx * tx + qy * ty
            nrm = qx * nx + qy * ny
            for s in Ss:
                px = N / 2 + tan * tx + (-nrm / s) * nx
                py = L + tan * ty + (-nrm / s) * ny
                a = lcn(samp(obj, px, py))[msk]
                a = a - a.mean(); an = np.sqrt((a * a).sum())
                if an < 1e-6: continue
                ncc = float((a * b).sum() / (an * bn))
                if best is None or ncc > best[0]: best = (ncc, L, th, s)
    return best


if __name__ == '__main__':
    for f in ['221282.png', '222009.png', '222281.png', '222285.png']:
        d = load(f)
        ncc, L, th, s = fit(d, np.arange(148, 196, 1.0),
                            np.arange(-14, 14.1, 2.0), np.arange(0.15, 1.45, 0.05))
        ncc, L, th, s = fit(d, np.arange(L - 1.5, L + 1.51, 0.25),
                            np.arange(th - 2, th + 2.01, 0.25),
                            np.arange(max(.08, s - .07), s + .071, 0.01))
        print(f"{f}  NCC={ncc:.3f}  contactY={L*F:6.1f}  "
              f"groundAngle={th:+6.2f}deg  scaleY={s:.3f}")
