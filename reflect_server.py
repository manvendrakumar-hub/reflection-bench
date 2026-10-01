#!/usr/bin/env python3
"""HTTP wrapper around the reflection pipeline. Standard library only.

No LLM, no browser, no external service. Start it and POST an image:

    python3 reflect_server.py --port 8080

    curl -X POST --data-binary @frame.jpg \
         -H 'Content-Type: image/jpeg' \
         http://localhost:8080/reflect -o out.png

    curl "http://localhost:8080/reflect?opacity=0.3&fade=300" ...   # overrides
    curl http://localhost:8080/health

Geometry is detected per image. The finish comes from the measured Reference
preset unless overridden by query parameters.
"""
import argparse
import io
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_reflection import (PART_DEFAULTS, SPLIT_DEFAULTS, FINISH_DEFAULTS,
                               auto_contact, render)

MAX_BYTES = 40 * 1024 * 1024
# query param -> (config section, key)
OVERRIDES = {
    "opacity": ("front", "opacity"), "fade": ("front", "fade"),
    "curve": ("front", "curve"), "blur": ("front", "blur"),
    "t_opacity": ("temple", "opacity"), "t_fade": ("temple", "fade"),
    "t_blur": ("temple", "blur"),
    "whiteCut": ("finish", "whiteCut"), "brightness": ("finish", "brightness"),
    "contrast": ("finish", "contrast"),
}


def build_config(img, params):
    f_over, t_over, split_x = auto_contact(img)
    if not f_over:
        raise ValueError("could not find a contact line - is the subject on white?")
    cfg = {
        "front": {**PART_DEFAULTS["front"], **f_over},
        "temple": {**PART_DEFAULTS["temple"], **t_over},
        "split": {**SPLIT_DEFAULTS, **({"x": split_x} if split_x else {})},
        "finish": dict(FINISH_DEFAULTS),
    }
    for key, (section, field) in OVERRIDES.items():
        if key in params:
            try:
                cfg[section][field] = float(params[key][0])
            except (TypeError, ValueError):
                pass
    return cfg


class Handler(BaseHTTPRequestHandler):
    server_version = "ReflectionBench/2.0"

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/health", "/"):
            self._send(200, json.dumps({
                "status": "ok", "model": "two-part oblique mirror",
                "defaults": {"front": PART_DEFAULTS["front"],
                             "temple": PART_DEFAULTS["temple"],
                             "finish": FINISH_DEFAULTS},
                "usage": "POST an image to /reflect",
            }, indent=2))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/reflect":
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                self._send(400, json.dumps({"error": "empty body"}))
                return
            if n > MAX_BYTES:
                self._send(413, json.dumps({"error": f"body over {MAX_BYTES} bytes"}))
                return
            raw = self.rfile.read(n)
            img = Image.open(io.BytesIO(raw))
            img.load()

            params = parse_qs(parsed.query)
            cfg = build_config(img, params)

            out_tmp = io.BytesIO()
            render(cfg, io.BytesIO(raw), out_tmp, auto=False, fmt="PNG")
            data = out_tmp.getvalue()

            self._send(200, data, "image/png",
                       {"X-Reflection-Config": json.dumps(cfg, separators=(",", ":"))})
        except ValueError as e:
            self._send(422, json.dumps({"error": str(e)}))
        except Exception as e:
            traceback.print_exc()
            self._send(500, json.dumps({"error": f"{type(e).__name__}: {e}"}))

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Reflection Bench server on http://{args.host}:{args.port}")
    print("  GET  /health    POST /reflect")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
