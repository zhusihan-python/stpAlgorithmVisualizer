#!/usr/bin/env python3
"""Local server for the web topology editor.

    python3 serve.py            # http://127.0.0.1:8765/

Serves the editor page and exposes POST /generate: the editor sends a
topology payload (topologies.from_dict schema) plus protocol/seed and gets
back the full step-animation document, which it plays via player.js.
The simulation stays in Python — nothing is reimplemented in JS.
"""

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import generate
import stp
import topologies

ROOT = Path(__file__).parent


def generate_document(payload: dict) -> dict:
    """POST /generate body -> animation document (or raises ValueError)."""
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    protocol = payload.get("protocol", "stp")
    if protocol not in ("stp", "rstp", "pvst", "mstp"):
        raise ValueError(f"unknown protocol {protocol!r}")
    topology, positions = topologies.from_dict(payload.get("topology"))
    seed = int(payload.get("seed", 42))
    document, _ = generate.build_document(
        "custom", topology, protocol=protocol, seed=seed, positions=positions)
    return document


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_POST(self):
        if self.path != "/generate":
            self.send_error(404, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            document = generate_document(payload)
            body = json.dumps(document, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
        except ValueError as exc:  # bad JSON, bad schema, or stp.validate
            body = json.dumps(
                {"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # quieter default output
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/editor.html"
    print(f"topology editor: {url}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
