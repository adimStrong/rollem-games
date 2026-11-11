"""Static file server for the backend-less promo games (gspot, t2b).

Two things beyond plain file serving, both added 2026-11-11 when those games gained a one-day link
expiry and a 12:00-23:59 play window:

1. GET /api/now -- the PH server clock. The page gates play on the PH date and must not trust the
   player's device clock, which is one tap away from being wound back. Serving this from the SAME host
   that just served the page means there is no CORS to get wrong, and that if the page loaded at all
   this endpoint will answer -- which is what lets the page fail CLOSED without stranding anyone.
2. Cache-Control on the HTML. SimpleHTTPRequestHandler sends no cache headers, so a browser may reuse a
   heuristically-cached page. A player on the OLD cached page opening a NEW link would fall through to
   demo mode and "win" something the ledger never records. no-cache forces a revalidate (cheap: it 304s
   when unchanged) so the page and the link format can never drift apart.
"""
import json
import os
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.path = "/index.html"
        if self.path.split("?")[0] == "/api/now":
            self.send_now()
            return
        super().do_GET()

    def send_now(self):
        ph = time.gmtime(time.time() + 8 * 3600)   # PH = UTC+8, no DST
        body = json.dumps({
            "ms": int(time.time() * 1000),
            "date": time.strftime("%Y-%m-%d", ph),
            "day": time.strftime("%Y%m%d", ph),    # the link token's day part
            "hm": time.strftime("%H:%M", ph),
            "min": ph.tm_hour * 60 + ph.tm_min,
            "tz": "Asia/Manila",
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # a cached clock would silently un-expire every link, so this one must never be stored
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        if self.path.split("?")[0].endswith((".html", "/")):
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
