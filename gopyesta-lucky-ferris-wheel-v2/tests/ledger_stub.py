"""Tiny stand-in for wins-ledger: records every POST /api/win to ledger_posts.jsonl."""
import json, os
from http.server import HTTPServer, BaseHTTPRequestHandler
OUT = os.path.join(os.path.dirname(__file__), "ledger_posts.jsonl")
open(OUT, "w").close()
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); body = self.rfile.read(n)
        with open(OUT, "a", encoding="utf-8") as f: f.write(body.decode() + "\n")
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b'{"ok":true}')
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", 8799), H).serve_forever()
