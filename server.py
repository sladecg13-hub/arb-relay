#!/usr/bin/env python3
"""
Arb Station relay: serves ArbStation.html and fetches exchange prices server-side,
so the browser never hits exchange cross-site (CORS) limits.

    python3 server.py            # then open http://localhost:8000
    python3 server.py 9000       # custom port

Open it from your phone with http://<this computer's local IP>:8000 on the same Wi-Fi,
or run it on a small cloud server. It only reads public price data. It holds no keys
and cannot trade. Standard library only, no installs.
"""
import concurrent.futures as cf
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))


def http_get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ArbStation relay)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


KR = {"BTC": "XBTUSD", "ZEC": "ZECUSD", "SOL": "SOLUSD"}
CB = {"BTC": "BTC-USD", "ZEC": "ZEC-USD", "SOL": "SOL-USD"}
LOW = {"BTC": "btcusd", "ZEC": "zecusd", "SOL": "solusd"}


def pos(x):
    v = float(x)
    if not v > 0:
        raise ValueError("bad price")
    return v


def kraken(s):
    d = json.loads(http_get("https://api.kraken.com/0/public/Ticker?pair=" + KR[s]))
    if d.get("error"):
        raise ValueError(d["error"][0])
    t = list(d["result"].values())[0]
    return pos(t["b"][0]), pos(t["a"][0])


def coinbase(s):
    d = json.loads(http_get("https://api.exchange.coinbase.com/products/%s/ticker" % CB[s]))
    return pos(d["bid"]), pos(d["ask"])


def bitstamp(s):
    d = json.loads(http_get("https://www.bitstamp.net/api/v2/ticker/%s/" % LOW[s]))
    return pos(d["bid"]), pos(d["ask"])


def gemini(s):
    d = json.loads(http_get("https://api.gemini.com/v1/pubticker/" + LOW[s]))
    return pos(d["bid"]), pos(d["ask"])


def okx(s):
    d = json.loads(http_get("https://www.okx.com/api/v5/market/ticker?instId=%s-USDT" % s))
    t = d["data"][0]
    return pos(t["bidPx"]), pos(t["askPx"])


def bybit(s):
    d = json.loads(http_get("https://api.bybit.com/v5/market/tickers?category=spot&symbol=%sUSDT" % s))
    t = d["result"]["list"][0]
    return pos(t["bid1Price"]), pos(t["ask1Price"])


def kucoin(s):
    d = json.loads(http_get("https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=%s-USDT" % s))
    return pos(d["data"]["bestBid"]), pos(d["data"]["bestAsk"])


EXCHANGES = {"Kraken": kraken, "Coinbase": coinbase, "Bitstamp": bitstamp, "Gemini": gemini,
             "OKX": okx, "Bybit": bybit, "KuCoin": kucoin}


_cache, _lock = {}, threading.Lock()


def all_quotes(sym):
    """Shared 2-second cache so several open pages cannot hammer the exchanges."""
    with _lock:
        hit = _cache.get(sym)
        if hit and time.time() - hit[0] < 2:
            return hit[1]
    out = _fetch_all(sym)
    with _lock:
        _cache[sym] = (time.time(), out)
    return out


def _fetch_all(sym):
    out = {}
    with cf.ThreadPoolExecutor(max_workers=len(EXCHANGES)) as ex:
        futs = {ex.submit(fn, sym): name for name, fn in EXCHANGES.items()}
        for f in cf.as_completed(futs):
            name = futs[f]
            try:
                bid, ask = f.result()
                out[name] = {"bid": bid, "ask": ask}
            except Exception as e:  # blocked in your country, rate limit, pair not listed, timeout
                out[name] = {"error": (type(e).__name__ + ": " + str(e))[:90]}
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/ping":
            return self._send(200, json.dumps({"arbstation": True}))
        if u.path == "/api/quotes":
            sym = (parse_qs(u.query).get("symbol", ["BTC"])[0]).upper()
            if sym not in KR:
                return self._send(400, json.dumps({"error": "symbol must be BTC, ZEC or SOL"}))
            return self._send(200, json.dumps(all_quotes(sym)))
        if u.path in ("/", "/index.html", "/ArbStation.html"):
            try:
                with open(os.path.join(HERE, "ArbStation.html"), "rb") as f:
                    return self._send(200, f.read(), "text/html; charset=utf-8")
            except FileNotFoundError:
                return self._send(404, "ArbStation.html must sit next to server.py", "text/plain")
        self._send(404, "not found", "text/plain")

    def log_message(self, *a):
        pass


def main():
    # Cloud hosts (Render, etc.) pass the port in the PORT environment variable.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8000"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print("Arb Station relay listening on port %d." % port, flush=True)
    print("On your own computer: http://localhost:%d  (phone on same Wi-Fi: http://<computer IP>:%d)" % (port, port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
