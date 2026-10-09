"""上交所剩余委托行情的事件回放；真实成交只在这里扣减一次。"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import pyarrow as pa
from .book import Order, OrderBook, cents
from .data import events, load_symbol, ParquetSink

EVENT_SCHEMA = pa.schema([
    ("symbol", pa.int32()), ("channel", pa.int32()), ("sequence", pa.int64()),
    ("time", pa.int32()), ("type", pa.string()), ("order_id", pa.int64()),
    ("buy_id", pa.int64()), ("sell_id", pa.int64()), ("side", pa.string()),
    ("price", pa.int32()), ("quantity", pa.int64()), ("bid_price", pa.int32()),
    ("bid_quantity", pa.int64()), ("ask_price", pa.int32()), ("ask_quantity", pa.int64()),
    ("total_bid_quantity", pa.int64()), ("total_ask_quantity", pa.int64()),
    ("trade_volume", pa.int64()), ("trade_count", pa.int64()),
])


class HistoricalReplay:
    def __init__(self):
        self.book = OrderBook()
        self.volume = 0
        self.trade_count = 0
        self.stats = Counter()
        self.phase = "before_open"

    def apply(self, kind, r):
        self.stats["events"] += 1
        if kind == "ord":
            code = chr(r["OrderKind"])
            if code == "S":
                self.phase = {73: "open_call", 79: "continuous", 74: "close_call", 67: "closed", 86: "after_hours"}.get(r["FunctionCode"], "unknown")
                self.stats["status"] += 1
            elif code == "A":
                self.book.add(Order(r["OrderOriNo"], chr(r["FunctionCode"]), cents(r["Price"]), r["Volume"], r["Time"], r["BizIndex"]))
                self.stats["adds"] += 1
            elif code == "D":
                self.book.reduce(r["OrderOriNo"], r["Volume"])
                self.stats["cancels"] += 1
            else:
                raise ValueError(f"未知委托类型 {code}")
        else:
            flag = r["BSFlag"]
            if flag not in (0, 66, 83):
                raise ValueError(f"未知成交方向 {flag}")
            # 主动单首次撮合尚未入簿。集合竞价双方已存在；连续竞价被动方必须存在。
            for side, oid in [("B", r["BidOrder"]), ("S", r["AskOrder"])]:
                if oid in self.book.orders:
                    if self.book.orders[oid].side != side:
                        raise ValueError(f"成交订单方向不符 {oid}")
                    self.book.reduce(oid, r["Volume"])
                    self.stats["trade_decrements"] += 1
                elif flag == ord(side):
                    self.stats["unpublished_aggressor_legs"] += 1
                else:
                    raise ValueError(f"业务序号 {r['BizIndex']} 缺少被动/集合竞价订单 {oid}")
            self.volume += r["Volume"]
            self.trade_count += 1
            self.stats["trades"] += 1

    def event_record(self, symbol, channel, seq, kind, r):
        bid, ask = self.book.best("B"), self.book.best("S")
        return {
            "symbol": symbol, "channel": channel, "sequence": seq, "time": r["Time"],
            "type": chr(r["OrderKind"]) if kind == "ord" else "T",
            "order_id": r.get("OrderOriNo", 0), "buy_id": r.get("BidOrder", 0),
            "sell_id": r.get("AskOrder", 0), "side": chr(r["FunctionCode"]) if kind == "ord" else (chr(r["BSFlag"]) if r["BSFlag"] else "N"),
            "price": cents(r["Price"]), "quantity": r["Volume"],
            "bid_price": bid.price if bid else 0, "bid_quantity": self.book.totals["B"].get(bid.price, 0) if bid else 0,
            "ask_price": ask.price if ask else 0, "ask_quantity": self.book.totals["S"].get(ask.price, 0) if ask else 0,
            "total_bid_quantity": self.book.side_quantity["B"], "total_ask_quantity": self.book.side_quantity["S"],
            "trade_volume": self.volume, "trade_count": self.trade_count,
        }


def depth_vector(book):
    d = book.depth(10)
    result = []
    for side in ("bids", "asks"):
        levels = d[side]
        for i in range(10):
            result.extend((levels[i]["price"], levels[i]["quantity"]) if i < len(levels) else (0, 0))
    return result


def snapshot_vector(r):
    return [v for side in ("Bid", "Ask") for i in range(1, 11) for v in (cents(r[f"{side}Price{i}"]), int(r[f"{side}Volume{i}"]))]


def milliseconds(t):
    return (t // 10000000 * 3600 + t // 100000 % 100 * 60 + t // 1000 % 100) * 1000 + t % 1000


class SnapshotCheck:
    """快照没有 BizIndex；用累计成交量+笔数限定候选，保留时间偏移而不伪造精确对应。"""

    def __init__(self, rows):
        self.groups = defaultdict(list)
        self.results = []
        for r in rows:
            t = r["Time"]
            if not (93000000 <= t < 145700000 or 150000000 <= t < 150500000):
                continue  # 集合竞价快照是虚拟撮合盘口，不能直接等同原始排队簿。
            item = {"time": t, "volume": r["AccVolume"], "trade_count": r["MatchItem"],
                    "minimum_different_fields": 40, "sequence": None, "offset_ms": None,
                    "candidate_found": False, "expected": snapshot_vector(r),
                    "total_bid": r["TotalBidVolume"], "total_ask": r["TotalAskVolume"],
                    "totals_match": False, "actual": None}
            self.groups[(r["AccVolume"], r["MatchItem"])].append(item)
            self.results.append(item)

    def observe(self, replay, seq, time):
        candidates = self.groups.get((replay.volume, replay.trade_count))
        if not candidates:
            return
        candidates = [x for x in candidates if abs(milliseconds(time) - milliseconds(x["time"])) <= 3000]
        if not candidates:
            return
        actual = depth_vector(replay.book)
        for x in candidates:
            diff = sum(a != b for a, b in zip(actual, x["expected"]))
            totals = replay.book.side_quantity["B"] == x["total_bid"] and replay.book.side_quantity["S"] == x["total_ask"]
            offset = milliseconds(time) - milliseconds(x["time"])
            old_rank = (x["minimum_different_fields"], not x["totals_match"], abs(x["offset_ms"] or 0))
            if not x["candidate_found"] or (diff, not totals, abs(offset)) < old_rank:
                x.update(minimum_different_fields=diff, sequence=seq, offset_ms=offset, candidate_found=True,
                         actual=actual, totals_match=totals)

    def summary(self):
        total = len(self.results)
        aligned = sum(x["candidate_found"] for x in self.results)
        exact = sum(x["candidate_found"] and x["minimum_different_fields"] == 0 for x in self.results)
        return {"eligible": total, "volume_and_count_aligned": aligned, "depth10_exact": exact,
                "depth10_exact_rate": exact / total if total else None,
                "depth10_and_totals_exact": sum(x["candidate_found"] and x["minimum_different_fields"] == 0 and x["totals_match"] for x in self.results),
                "method": "相同累计成交量和笔数、事件时间距快照不超过3秒，搜索逐事件候选；这不是时间戳直接对齐的准确率。"}

    def save(self, path):
        schema = pa.schema([("time", pa.int32()), ("volume", pa.int64()), ("trade_count", pa.int64()),
                            ("sequence", pa.int64()), ("offset_ms", pa.int32()),
                            ("candidate_found", pa.bool_()), ("minimum_different_fields", pa.int32()),
                            ("totals_match", pa.bool_()), ("expected", pa.list_(pa.int64())), ("actual", pa.list_(pa.int64()))])
        with ParquetSink(path, schema) as out:
            for x in self.results:
                out.append(x)


def replay_symbol(data, symbol, out=None, until=None, sequence=None):
    rows, after, channel = events(data, symbol)
    replay = HistoricalReplay()
    checks = SnapshotCheck(load_symbol(data, "snp", symbol).to_pylist()) if out else None
    sink = ParquetSink(Path(out) / "events.parquet", EVENT_SCHEMA) if out else None
    last = None
    try:
        for seq, kind, r in rows:
            if until is not None and r["Time"] > until or sequence is not None and seq > sequence:
                break
            replay.apply(kind, r)
            last = (seq, r["Time"])
            if checks:
                checks.observe(replay, seq, r["Time"])
            if sink:
                sink.append(replay.event_record(symbol, channel, seq, kind, r))
        replay.book.assert_valid()
    finally:
        if sink:
            sink.close()
    summary = {"symbol": symbol, "channel": channel, "statistics": dict(replay.stats),
               "regular_trade_volume": replay.volume, "open_orders": len(replay.book.orders),
               "last_event": last, "final_depth": replay.book.depth(10),
               "after_hours": {"trades": len(after), "volume": sum(r["Volume"] for r in after),
                               "note": "盘后固定价格订单未发布，成交单独保存，不从竞价订单簿扣减。"}}
    if out:
        out = Path(out)
        checks.save(out / "snapshot_check.parquet")
        summary["snapshot_check"] = checks.summary()
        (out / "replay_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        if after:
            import pyarrow.parquet as pq
            pq.write_table(pa.Table.from_pylist(after), out / "after_hours_trades.parquet", compression="zstd")
    return replay, summary
