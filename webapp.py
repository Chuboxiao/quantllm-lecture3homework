#!/usr/bin/env python3
"""本地网页入口；历史状态与模拟撮合直接使用 exchange 包。"""
import argparse
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen
import webbrowser

from exchange.book import MatchingEngine, Order, cents, clock_int, clock_text
from exchange.data import DEFAULT_DATA, events, load_symbol
from exchange.replay import HistoricalReplay

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "web"
REFERENCE_RESULTS = ROOT / "reports/results"


def result_file(name):
    current = ROOT / "output" / name
    return current if current.is_file() else REFERENCE_RESULTS / name


def book_view(book):
    return {"depth": book.depth(10), "order_count": len(book.orders),
            "buy_quantity": book.side_quantity["B"], "sell_quantity": book.side_quantity["S"]}


def order_page(book, side=None, price=None, offset=0, limit=50):
    if side is not None and side not in ("B", "S"):
        raise ValueError("方向应为B或S")
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("分页范围无效")
    rows = []
    for s in (side,) if side else ("B", "S"):
        levels = book.levels[s]
        prices = [price] if price is not None and price in levels else ([] if price is not None else list(levels.keys())[::(-1 if s == "B" else 1)])
        for p in prices:
            rows.extend(asdict(o) for o in levels[p].values())
    return {"orders": rows[offset:offset + limit], "total": len(rows), "offset": offset, "limit": limit}


class HistoryCursor:
    def __init__(self, rows, symbol, channel):
        self.rows = rows
        self.symbol = symbol
        self.channel = channel
        self.times = [r[2]["Time"] for r in rows]
        self.index = -1
        self.replay = HistoricalReplay()
        self.price = 0

    def seek(self, index):
        if type(index) is not int:
            raise ValueError("事件位置应为整数")
        index = min(max(index, -1), len(self.rows) - 1)
        if index < self.index:
            self.index = -1
            self.replay = HistoricalReplay()
            self.price = 0
        for i in range(self.index + 1, index + 1):
            _, kind, row = self.rows[i]
            self.replay.apply(kind, row)
            if kind == "exe":
                self.price = cents(row["Price"])
        self.index = index
        return self.state()

    def seek_time(self, text):
        return self.seek(bisect_right(self.times, clock_int(text)) - 1)

    def state(self):
        recent = []
        for seq, kind, r in self.rows[max(0, self.index - 11):self.index + 1]:
            typ = "T" if kind == "exe" else chr(r["OrderKind"])
            recent.append({"sequence": seq, "time": clock_text(r["Time"]), "type": typ,
                           "side": (chr(r["BSFlag"]) if r["BSFlag"] else "N") if kind == "exe" else chr(r["FunctionCode"]),
                           "order_id": r.get("OrderOriNo", 0), "buy_id": r.get("BidOrder", 0), "sell_id": r.get("AskOrder", 0),
                           "price": cents(r["Price"]), "quantity": r["Volume"]})
        current = self.rows[self.index] if self.index >= 0 else None
        return {**book_view(self.replay.book), "symbol": self.symbol, "channel": self.channel,
                "index": self.index, "event_count": len(self.rows), "sequence": current[0] if current else 0,
                "time": clock_text(current[2]["Time"]) if current else "09:15:00.000",
                "time_value": current[2]["Time"] if current else 91500000,
                "last_price": self.price, "trade_volume": self.replay.volume, "trade_count": self.replay.trade_count,
                "phase": self.replay.phase, "events": list(reversed(recent))}


class Simulator:
    def __init__(self):
        self.reset(True)

    def reset(self, seed):
        self.engine = MatchingEngine()
        self.phase = "continuous"
        self.next_id = 1
        self.sequence = 0
        self.trades = []
        self.message = "已载入示例盘口：10元有两笔卖单，分别为300股和500股。" if seed else "空订单簿，等待你的第一笔委托。"
        if seed:
            for side, price, quantity in [("S", 1000, 300), ("S", 1000, 500), ("S", 1001, 600), ("B", 999, 400), ("B", 998, 700)]:
                self.engine.submit(Order(self.next_id, side, price, quantity))
                self.next_id += 1

    def act(self, body):
        action = body.get("action")
        result = []
        self.sequence += 1
        if action == "reset":
            self.reset(bool(body.get("seed", True)))
        elif action == "phase":
            phase = body.get("phase")
            if phase not in ("continuous", "auction"):
                raise ValueError("请选择连续竞价或集合竞价")
            b, s = self.engine.book.best("B"), self.engine.book.best("S")
            if phase == "continuous" and b and s and b.price >= s.price:
                raise ValueError("买卖报价已相交，请先执行集合竞价统一撮合")
            self.phase = phase
            self.message = "集合竞价：新增订单先排队，点击统一撮合后成交。" if phase == "auction" else "连续竞价：每笔新订单立即按价格与时间优先撮合。"
        elif action in ("order", "demo"):
            if action == "demo":
                self.reset(True)
                body = {"side": "B", "price": "10.00", "quantity": 1000}
            side = body.get("side")
            quantity = body.get("quantity")
            if side not in ("B", "S") or type(quantity) is not int or not 1 <= quantity <= 100000000:
                raise ValueError("数量应为1至100000000的整数，方向应为买入或卖出")
            price = cents(body.get("price", 0))
            if not 1 <= price <= 10000000:
                raise ValueError("价格应大于0且不高于100000元")
            oid = self.next_id
            result = self.engine.submit(Order(oid, side, price, quantity, 93000000, self.sequence), auction=self.phase == "auction")
            self.next_id += 1
            executed = sum(t.quantity for t in result)
            remaining = self.engine.book.orders[oid].quantity if oid in self.engine.book.orders else 0
            self.message = f"订单 #{oid}：{'买入' if side == 'B' else '卖出'} {quantity:,}股，限价 {price / 100:.2f}元。"
            self.message += f"生成{len(result)}笔成交，共{executed:,}股；剩余{remaining:,}股排队。" if self.phase == "continuous" else "已加入集合竞价队列，等待统一撮合。"
        elif action == "cancel":
            oid = body.get("order_id")
            if type(oid) is not int:
                raise ValueError("请选择有效订单")
            quantity = body.get("quantity")
            if quantity is not None and type(quantity) is not int:
                raise ValueError("撤销数量应为整数")
            removed = self.engine.cancel(oid, quantity)
            self.message = f"订单 #{oid} 已撤销{removed:,}股。撤单不产生成交。"
        elif action == "uncross":
            if self.phase != "auction":
                raise ValueError("请先选择集合竞价模式")
            result = self.engine.uncross(150000000, self.sequence)
            self.message = f"集合竞价统一撮合：{len(result)}笔成交，共{sum(t.quantity for t in result):,}股。"
            if result:
                self.message += f"统一成交价{result[0].price / 100:.2f}元。"
        else:
            raise ValueError("未知模拟操作")
        self.trades.extend(t.record() for t in result)
        self.engine.book.assert_valid()
        return self.state()

    def state(self):
        p, q = self.engine.auction_price() if self.phase == "auction" else (None, 0)
        return {**book_view(self.engine.book), "phase": self.phase, "message": self.message,
                "trades": list(reversed(self.trades[-100:])), "trade_count": len(self.trades),
                "trade_volume": sum(x["quantity"] for x in self.trades), "next_id": self.next_id,
                "orders": order_page(self.engine.book, limit=100)["orders"], "auction_price": p, "auction_quantity": q}


class Session:
    def __init__(self):
        self.lock = threading.RLock()
        self.last_used = time.monotonic()
        self.history = None
        self.simulator = Simulator()


class Application:
    def __init__(self, data=DEFAULT_DATA):
        self.data = data
        self.summary = json.loads(result_file("summary.json").read_text())
        self.symbols = [x["symbol"] for x in self.summary["results"] if "error" not in x]
        self.sessions = {}
        self.cache = OrderedDict()
        self.lock = threading.RLock()

    def new_session(self):
        with self.lock:
            now = time.monotonic()
            self.sessions = {k: v for k, v in self.sessions.items() if now - v.last_used < 3600}
            if len(self.sessions) >= 16:
                oldest = min(self.sessions, key=lambda k: self.sessions[k].last_used)
                del self.sessions[oldest]
            token = secrets.token_urlsafe(24)
            self.sessions[token] = Session()
            return {"session": token}

    def session(self, token):
        with self.lock:
            s = self.sessions.get(token)
            if s is None:
                raise ValueError("会话已过期，请刷新页面")
            s.last_used = time.monotonic()
            return s

    def symbol_data(self, symbol):
        if symbol not in self.symbols:
            raise ValueError("股票不在本数据包中")
        with self.lock:
            if symbol in self.cache:
                self.cache.move_to_end(symbol)
                return self.cache[symbol]
            rows, _, channel = events(self.data, symbol)
            snapshots = load_symbol(self.data, "snp", symbol).to_pylist()
            values = [r for r in snapshots if r["Price"] > 0 and r["Time"] <= 150000000]
            stride = max(1, len(values) // 1600)
            series = [{"time": r["Time"], "price": cents(r["Price"]), "volume": r["Volume"]} for r in values[::stride]]
            stock_summary = next(x for x in self.summary["results"] if x["symbol"] == symbol)
            item = (rows, channel, series, stock_summary)
            self.cache[symbol] = item
            while len(self.cache) > 2:
                self.cache.popitem(last=False)
            return item

    def request(self, method, path, body=None):
        parsed = urlparse(path)
        query = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
        body = body or {}
        if parsed.path == "/api/meta" and method == "GET":
            return {"symbols": self.symbols, "date": "2026-09-23", "aggregate": self.summary["aggregate"]}
        if parsed.path == "/api/session" and method == "POST":
            return self.new_session()
        s = self.session(body.get("session") or query.get("session"))
        with s.lock:
            if parsed.path == "/api/history" and method == "POST":
                symbol = int(body.get("symbol", 600036))
                rows, channel, series, verified = self.symbol_data(symbol)
                changed = s.history is None or s.history.symbol != symbol
                if changed:
                    s.history = HistoryCursor(rows, symbol, channel)
                action = body.get("action", "seek")
                if action == "seek":
                    state = s.history.seek_time(body["time"]) if "time" in body else s.history.seek(body.get("index", s.history.index))
                elif action == "step":
                    count = body.get("count", 1)
                    if type(count) is not int or not -10000 <= count <= 10000:
                        raise ValueError("每次最多移动10000个事件")
                    state = s.history.seek(s.history.index + count)
                else:
                    raise ValueError("未知回放操作")
                if changed or body.get("include_series"):
                    state["series"] = series
                    state["validation"] = {"snapshot": verified["replay"]["snapshot_check"],
                                           "final_book_exact": verified["final_book_exact"],
                                           "trades_exact": all(x["ordered_trade_pairs_exact"] for x in verified["simulation"]["comparisons"].values())}
                return state
            if parsed.path == "/api/simulator":
                return s.simulator.state() if method == "GET" else s.simulator.act(body)
            if parsed.path == "/api/orders" and method == "GET":
                source = query.get("source", "history")
                book = s.history.replay.book if source == "history" and s.history else s.simulator.engine.book if source == "simulator" else None
                if book is None:
                    raise ValueError("请先加载历史盘口")
                return order_page(book, query.get("side"), int(query["price"]) if "price" in query else None,
                                  int(query.get("offset", 0)), int(query.get("limit", 50)))
        raise ValueError("没有这个接口")


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, content, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)

        def handle_request(self, method):
            path = urlparse(self.path).path
            static = {"/": (ASSETS / "index.html", "text/html; charset=utf-8"),
                      "/app.js": (ASSETS / "app.js", "text/javascript; charset=utf-8"),
                      "/style.css": (ASSETS / "style.css", "text/css; charset=utf-8"),
                      "/report": (result_file("report.html"), "text/html; charset=utf-8")}
            if method == "GET" and path in static:
                file, kind = static[path]
                return self.send(200, file.read_bytes(), kind)
            if not path.startswith("/api/"):
                return self.send(404, b"Not found", "text/plain")
            try:
                body = None
                if method == "POST":
                    origin = self.headers.get("Origin")
                    if origin and origin != f"http://{self.headers.get('Host')}":
                        return self.send(403, b"Origin rejected", "text/plain")
                    length = int(self.headers.get("Content-Length", 0))
                    if length > 16384 or length <= 0:
                        raise ValueError("请求大小无效")
                    if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                        raise ValueError("请求应为JSON")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("请求应为对象")
                result = app.request(method, self.path, body)
                self.send(200, json.dumps(result, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            except (ValueError, TypeError, KeyError) as e:
                message = str(e) if not isinstance(e, KeyError) else "订单不存在或请求缺少字段"
                self.send(400, json.dumps({"error": message}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            except Exception as e:
                print(f"请求失败：{type(e).__name__}: {e}", flush=True)
                self.send(500, json.dumps({"error": "加载失败，请查看启动窗口中的提示"}, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def do_GET(self):
            self.handle_request("GET")

        def do_POST(self):
            self.handle_request("POST")

        def log_message(self, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description="上证50实践课网页")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    args = parser.parse_args()
    app = Application()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(app))
    except OSError:
        url = f"http://127.0.0.1:{args.port}"
        try:
            with urlopen(url + "/api/meta", timeout=2) as response:
                existing = json.load(response)
            if existing.get("symbols") == app.symbols and existing.get("date") == "2026-09-23":
                print(f"模拟交易所已经在运行：{url}", flush=True)
                if args.open:
                    webbrowser.open(url)
                return
        except Exception:
            pass
        parser.error(f"端口{args.port}不可用，请用 --port 指定其他端口")
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"网页已启动：{url}\n保持此窗口打开；关闭时按 Ctrl+C。", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
