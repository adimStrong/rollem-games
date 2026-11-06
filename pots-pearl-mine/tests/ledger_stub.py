"""Fake wins-ledger: accepts POST /api/win and appends each payload to tests/ledger_posts.jsonl.
Usage: python tests/ledger_stub.py [port]  (default 8791)"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

OUT = os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(body.decode("utf-8", "replace") + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("ledger stub on", PORT, "->", OUT, flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
