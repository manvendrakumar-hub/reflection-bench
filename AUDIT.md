# Agent Audit — Reflection Bench v2

Session `51a2d0be-f869-4b4e-a2f8-b31205818efa` · model `claude-opus-5` · SHA-256 hash chain verified.

Explicit records and rationale summaries only. No hidden chain-of-thought is captured or claimed.

## 1. session.init  —  2026-09-08T20:01:36.513Z

`record_hash: 312d898a02bcdb6faf8ee9232f77bc72853dec6b1cfdba6b54147d5191469a75`

## 2. artifact.created  —  2026-09-08T20:04:37.574Z

Generated three reflection variants from identity-composite.png by mirroring the subject across the measured tilted contact line (240,634)-(565,689) with vertical compression, distance-based blur and an opacity ramp. Source file left untouched (mtime Sep 4 15:46, sha1 13b70eb4387498759cc1aee8fc30ea29589d42ab).

```json
{
  "method": "shear-mirror across measured ground line, bilinear resample, progressive gaussian blur, power falloff opacity, composited under original over white",
  "provenance": "observed"
}
```

```json
[
  {
    "note": "recommended: squash 0.55, strength 0.34, fade 300px",
    "path": "identity-composite-reflection.png"
  },
  {
    "note": "subtle matte-glass",
    "path": "identity-composite-reflection-soft.png"
  },
  {
    "note": "strong wet/polished-glass",
    "path": "identity-composite-reflection-glass.png"
  }
]
```

`record_hash: 581da143bdd7755d411448d1753a5daca90fb29ac4ae69144324db39267f50ff`

## 3. artifact.created  —  2026-09-08T20:19:35.084Z

Built Reflection Bench: an interactive HTML rig (CSS matrix3d homography mirror + screen-space mask/blur) with 18 parameters, draggable contact reticles, presets and a copyable JSON config; plus render_reflection.py which replays the same config in numpy/PIL at full resolution. Verified in Chrome via playwright (no console errors) and confirmed the Python render matches the browser preview for the Laid-flat preset.

```json
{
  "provenance": "observed",
  "verification": "playwright screenshot of local file, console clean; python render visually matched browser preview",
  "web_research": "no deterministic prior art found; published work is diffusion-based (MirrorFusion/DEROBA) or reflection-removal, both unsuitable since they repaint pixels"
}
```

```json
[
  {
    "path": "reflection-bench.html",
    "url": "https://claude.ai/code/artifact/3a853eca-2172-4a2f-a5f7-761ad4147513"
  },
  {
    "path": "render_reflection.py"
  }
]
```

`record_hash: ab20aee49da473d208f4044da758cf899259b600892d8e5cebcae30bfe9f8904`

## 4. finding.recorded  —  2026-09-08T20:45:09.427Z

Measured the true reflection operator from the four reference renders in correct/. A 6-param affine fit gave consistently ASYMMETRIC inverse matrices (M01~-0.05 vs M10~+0.40), which rules out orthogonal reflection about a tilted line. Constrained oblique fit (vertical-shear mirror) gave groundAngle 10.02deg +-0.92 and scaleY 1.016 +-0.022 across all four - i.e. points drop straight down onto a ~10deg contact line with NO vertical compression. Fade envelope measured at peak ~0.40 at contact decaying to zero by ~260px.

```json
{
  "per_image": {
    "221282": [
      683.8,
      8.93,
      0.984
    ],
    "222009": [
      665.7,
      9.84,
      1.019
    ],
    "222281": [
      670.7,
      9.85,
      1.014
    ],
    "222285": [
      699.8,
      11.48,
      1.046
    ]
  },
  "prior_error": "bench v1 used orthogonal reflection about the tilted line plus 0.5 vertical squash - both wrong",
  "provenance": "observed",
  "validation": "stripped a reference's own reflection and regenerated it from fitted params; geometry matched side by side"
}
```

```json
[
  {
    "note": "rewired to oblique operator, image loading, auto-detect",
    "path": "reflection-bench.html"
  },
  {
    "path": "render_reflection.py"
  },
  {
    "path": "reflection-config.json"
  },
  {
    "path": "identity-composite-oblique.png"
  }
]
```

`record_hash: 504fc9f5faba6de6fd337493b1c82ee2ef9e4ceb50be93d055630a5130e2f7fb`

## 5. finding.recorded  —  2026-09-08T21:27:34.216Z

Root-caused the missing temple reflection. Reflection displacement scales with each point's height above the glass, which a 2D map cannot represent - proven by fitting: a full 8-DOF homography and a 4-DOF harmonic homology both topped out at NCC 0.12-0.25 over the whole reflection, while the front-only oblique fit scores 0.59 and a temple-only oblique fit scores 0.60-0.78. So the reference renders use TWO independent mirrors. Temple params: contact -33.2deg +-1.6, depth 1.53 (vs front +10deg, depth 1.00). Independent confirmation: the fitted temple contact line passes through (970,451) and the measured temple tip is (970,445) - it located the tip without being told.

```json
{
  "bugs_fixed": [
    "gFront/gTemple id collision between rail sections and SVG guide lines",
    "split gradient inverted - normal points left so front sits above d0"
  ],
  "provenance": "observed",
  "rejected_models": {
    "harmonic_homology": "NCC 0.115-0.249",
    "orthogonal_mirror": "asymmetric fitted matrices rule it out",
    "single_homography": "NCC 0.014-0.249"
  },
  "temple_per_image": {
    "221282": [
      759.5,
      -33.95,
      1.621
    ],
    "222009": [
      749.1,
      -31.37,
      1.337
    ],
    "222281": [
      749.5,
      -31.11,
      1.388
    ],
    "222285": [
      776.9,
      -34.45,
      1.773
    ]
  }
}
```

```json
[
  {
    "path": "reflection-bench.html",
    "url": "https://claude.ai/code/artifact/3a853eca-2172-4a2f-a5f7-761ad4147513"
  },
  {
    "path": "render_reflection.py"
  },
  {
    "path": "identity-composite-2part.png"
  }
]
```

`record_hash: 9c3fd6b7c385c6542b5afcb2e0f8eb4a7615a84600ba0453dcde984c78e498cb`
