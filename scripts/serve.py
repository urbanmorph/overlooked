"""Local server for the site: site/ at /, a data folder at /data/ (laid out like R2).

Serves gzip when the browser asks for it and supports Range requests, like Cloudflare.
Port 8790 by default (8765 belongs to another project).

Usage: .venv/bin/python scripts/serve.py [--port 8790] [--data data/publish-dev]
"""

import argparse
import gzip
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPRESS = {".json", ".js", ".css", ".html", ".svg"}


def make_handler(site: Path, data: Path):
    class Handler(BaseHTTPRequestHandler):
        def resolve(self):
            path = self.path.split("?", 1)[0].split("#", 1)[0]
            if path.startswith("/data/"):
                base, rel = data, path[len("/data/"):]
            else:
                base, rel = site, path.lstrip("/")
            target = (base / rel).resolve()
            if target.is_dir():
                target = target / "index.html"
            elif not target.exists() and target.with_suffix(".html").is_file():
                target = target.with_suffix(".html")  # /ledger -> ledger.html, as on Cloudflare Pages
            if base.resolve() not in target.parents and target != base.resolve():
                return None
            return target if target.is_file() else None

        def do_HEAD(self):
            self.respond(head=True)

        def do_GET(self):
            self.respond(head=False)

        def respond(self, head):
            target = self.resolve()
            if not target:
                self.send_error(404)
                return
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".js":
                ctype = "text/javascript"
            status, headers = 200, {"Content-Type": ctype, "Accept-Ranges": "bytes", "Cache-Control": "no-cache"}
            rng = self.headers.get("Range")
            m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
            if m:
                start = int(m.group(1)) if m.group(1) else len(body) - int(m.group(2))
                end = int(m.group(2)) if m.group(1) and m.group(2) else len(body) - 1
                headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
                body, status = body[start:end + 1], 206
            elif target.suffix in COMPRESS and "gzip" in self.headers.get("Accept-Encoding", ""):
                body = gzip.compress(body, 6)
                headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(body))
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            if not head:
                self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass

    return Handler


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8790)
    p.add_argument("--data", default=str(ROOT / "data" / "publish-dev"))
    a = p.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(ROOT / "site", Path(a.data)))
    print(f"http://127.0.0.1:{a.port}/  (data from {a.data})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
