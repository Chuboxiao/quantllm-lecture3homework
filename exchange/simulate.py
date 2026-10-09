"""从剩余订单与主动成交推断可等价撮合的订单输入，再独立选择对手单。"""
from collections import Counter, defaultdict
from pathlib import Path
import json
import pyarrow as pa
from .book import Order, MatchingEngine, cents
from .data import events, ParquetSink

TRADE_SCHEMA = pa.schema([("buy_id", pa.int64()), ("sell_id", pa.int64()), ("price", pa.int32()),
                         ("quantity", pa.int64()), ("time", pa.int32()), ("sequence", pa.int64()), ("phase", pa.string())])
INPUT_SCHEMA = pa.schema([("sequence", pa.int64()), ("time", pa.int32()), ("type", pa.string()),
                         ("order_id", pa.int64()), ("side", pa.string()), ("price", pa.int32()),
                         ("quantity", pa.int64()), ("provenance", pa.string()), ("price_inferred", pa.bool_())])


def reconstruct_inputs(rows):
    adds = {r["OrderOriNo"]: r for _, kind, r in rows if kind == "ord" and r["OrderKind"] == 65}
    active = defaultdict(list)
    auctions = defaultdict(list)
    reference = []
    for seq, kind, r in rows:
        if kind != "exe":
            continue
        phase = "continuous" if r["BSFlag"] else ("open_auction" if r["Time"] < 93000000 else "close_auction")
        reference.append((r["BidOrder"], r["AskOrder"], cents(r["Price"]), r["Volume"], phase))
        if r["BSFlag"]:
            side = chr(r["BSFlag"])
            oid = r["BidOrder"] if side == "B" else r["AskOrder"]
            active[(side, oid)].append(r)
        else:
            auctions[r["Time"]].append(r)
    inputs = []
    inferred_ids = set()
    for (side, oid), trades in active.items():
        first = trades[0]
        residual = adds.get(oid)
        if residual and residual["BizIndex"] <= first["BizIndex"]:
            raise ValueError(f"主动订单 {oid} 的剩余委托出现在主动成交之前")
        if residual and chr(residual["FunctionCode"]) != side:
            raise ValueError("主动方向与剩余委托方向不一致")
        # 未披露限价时，使用最差成交价作为可等价执行的边界。原始限价/订单类型无法唯一识别。
        price = cents(residual["Price"]) if residual else (max if side == "B" else min)(cents(t["Price"]) for t in trades)
        inputs.append({"sequence": first["BizIndex"], "time": first["Time"], "type": "A", "order_id": oid,
                       "side": side, "price": price,
                       "quantity": sum(t["Volume"] for t in trades) + (residual["Volume"] if residual else 0),
                       "provenance": "active_trades_plus_residual" if residual else "active_trades_only",
                       "price_inferred": residual is None})
        inferred_ids.add(oid)
    for seq, kind, r in rows:
        if kind != "ord":
            continue
        typ = chr(r["OrderKind"])
        if typ == "A" and r["OrderOriNo"] in inferred_ids:
            continue  # 已补回最初数量；不再将剩余委托重复加入。
        if typ in ("A", "D"):
            inputs.append({"sequence": seq, "time": r["Time"], "type": typ, "order_id": r["OrderOriNo"],
                           "side": chr(r["FunctionCode"]), "price": cents(r["Price"]), "quantity": r["Volume"],
                           "provenance": "published_order", "price_inferred": False})
        elif typ == "S" and r["FunctionCode"] in (79, 67):
            # 即使竞价没有成交，也要在竞价结束计算清算价；正常情况由首笔竞价成交触发。
            auction_time = 92500000 if r["FunctionCode"] == 79 else 150000000
            if auction_time not in auctions:
                inputs.append({"sequence": seq, "time": auction_time, "type": "U", "order_id": 0,
                               "side": "", "price": 0, "quantity": 0, "provenance": "phase_boundary", "price_inferred": False})
    for time, trades in auctions.items():
        inputs.append({"sequence": trades[0]["BizIndex"], "time": time, "type": "U", "order_id": 0,
                       "side": "", "price": 0, "quantity": 0, "provenance": "phase_boundary", "price_inferred": False})
    inputs.sort(key=lambda x: x["sequence"])
    return inputs, reference


def simulate_symbol(data, symbol, out):
    rows, _, channel = events(data, symbol)
    inputs, reference = reconstruct_inputs(rows)
    engine = MatchingEngine()
    generated = []
    auction_prices = []
    out = Path(out)
    with ParquetSink(out / "simulation_inputs.parquet", INPUT_SCHEMA) as ins, ParquetSink(out / "simulated_trades.parquet", TRADE_SCHEMA) as trades:
        for x in inputs:
            ins.append(x)
            if x["type"] == "A":
                t = x["time"]
                auction = t < 92500000 or 145700000 <= t < 150000000
                result = engine.submit(Order(x["order_id"], x["side"], x["price"], x["quantity"], t, x["sequence"]), auction=auction)
            elif x["type"] == "D":
                engine.cancel(x["order_id"], x["quantity"])
                result = []
            else:
                phase = "open_auction" if x["time"] < 93000000 else "close_auction"
                p, q = engine.auction_price()
                auction_prices.append({"phase": phase, "price": p, "quantity": q})
                result = engine.uncross(x["time"], x["sequence"], phase)
            for trade in result:
                trades.append(trade.record())
                generated.append((trade.buy_id, trade.sell_id, trade.price, trade.quantity, trade.phase))
        engine.book.assert_valid()
    comparisons = {}
    for phase in ("continuous", "open_auction", "close_auction"):
        expected = [x for x in reference if x[-1] == phase]
        actual = [x for x in generated if x[-1] == phase]
        pair_expected, pair_actual = Counter(expected), Counter(actual)
        price_expected = Counter()
        price_actual = Counter()
        order_expected = Counter()
        order_actual = Counter()
        for values, prices, orders in [(expected, price_expected, order_expected), (actual, price_actual, order_actual)]:
            for b, s, p, q, _ in values:
                prices[p] += q
                orders[("B", b)] += q
                orders[("S", s)] += q
        comparisons[phase] = {"reference_trades": len(expected), "generated_trades": len(actual),
                              "reference_volume": sum(x[3] for x in expected), "generated_volume": sum(x[3] for x in actual),
                              "ordered_trade_pairs_exact": expected == actual,
                              "trade_pairs_multiset_exact": pair_expected == pair_actual,
                              "price_volume_exact": price_expected == price_actual,
                              "per_order_executed_quantity_exact": order_expected == order_actual,
                              "different_trade_pairs": sum((pair_expected - pair_actual).values()) + sum((pair_actual - pair_expected).values()),
                              "examples_missing": [list(x) for x in (pair_expected - pair_actual).keys()][:5],
                              "examples_extra": [list(x) for x in (pair_actual - pair_expected).keys()][:5]}
    summary = {"symbol": symbol, "channel": channel, "input_events": len(inputs),
               "reconstructed_active_orders": sum(x["provenance"].startswith("active") for x in inputs),
               "unidentifiable_original_limit_orders": sum(x["price_inferred"] for x in inputs),
               "auctions": auction_prices, "comparisons": comparisons,
               "final_depth": engine.book.depth(10), "open_orders": len(engine.book.orders),
               "validation_scope": "使用真实成交补回缺失的主动委托量和等价限价；撮合对手单由引擎选择。属于订单簿/撮合一致性验证，不是独立预测，也不能唯一恢复原始市价类型或限价。"}
    (out / "simulation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return engine, summary
