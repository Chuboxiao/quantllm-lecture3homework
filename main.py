#!/usr/bin/env python3
"""运行入口：inspect / demo / run / book / check。"""
import argparse
from dataclasses import asdict
import hashlib
import html
import json
from pathlib import Path
import platform
import sys
import time
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from exchange.book import MatchingEngine, Order, cents, clock_int, clock_text
from exchange.data import DEFAULT_DATA, symbols
from exchange.replay import replay_symbol
from exchange.simulate import simulate_symbol

ROOT = Path(__file__).resolve().parent


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def profile(data, output):
    result = {"date": "2026-09-23", "files": {}, "symbols": symbols(data),
              "price_unit": "元（源文件 float32；系统整数分）", "quantity_unit": "股，已与快照累计成交量及档位数量核对",
              "time_encoding": "HHMMSSmmm，如 93000030 = 09:30:00.030；样本逐笔时间分辨率主要为10毫秒",
              "order_encoding": {"OrderKind": {"65/A": "新增剩余委托", "68/D": "撤单", "83/S": "产品阶段状态"},
                                 "FunctionCode": {"66/B": "买", "83/S": "卖", "73/I": "开盘集合竞价", "79/O": "连续交易", "74/J": "收盘集合竞价", "67/C": "闭市", "86/V": "盘后阶段"}},
              "ordering": "同一竞价 Channel 按 BizIndex；订单使用 OrderOriNo，与 BidOrder/AskOrder 关联。此包仅包含50只股票，通道序号跳号不能直接判定丢包。"}
    for kind in ("ord", "exe", "snp"):
        path = Path(data) / f"{kind}_20260923.parquet"
        table = pq.read_table(path)
        with path.open("rb") as f:
            fingerprint = hashlib.file_digest(f, "sha256").hexdigest()
        item = {"rows": len(table), "columns": [{"name": f.name, "type": str(f.type), "nulls": table[f.name].null_count} for f in table.schema],
                "bytes": path.stat().st_size, "sha256": fingerprint,
                "time_min": clock_text(pc.min(table["Time"]).as_py()), "time_max": clock_text(pc.max(table["Time"]).as_py()),
                "symbol_count": len(pc.unique(table["Symbol"]))}
        for col in ("OrderKind", "FunctionCode", "BSFlag", "Channel"):
            if col in table.column_names:
                item[col] = pc.value_counts(table[col]).to_pylist()
        result["files"][kind] = item
    write_json(Path(output) / "data_profile.json", result)
    print(f"数据检查完成：{len(result['symbols'])}只股票；" + "，".join(f"{k} {v['rows']:,}行" for k, v in result["files"].items()))
    return result


def demo(output):
    engine = MatchingEngine()
    states = []
    actions = [("新增卖单 S1", Order(1, "S", 1000, 300)), ("新增卖单 S2", Order(2, "S", 1000, 500)),
               ("新增卖单 S3", Order(3, "S", 1001, 600)), ("新增买单 B1", Order(4, "B", 999, 400)),
               ("新增买单 B2", Order(5, "B", 998, 700)), ("买单 B3 以10元买入1000股", Order(6, "B", 1000, 1000))]
    for i, (label, order) in enumerate(actions, 1):
        order.sequence = i
        trades = engine.submit(order)
        state = {"step": label, "trades": [x.record() for x in trades], "book": engine.book.depth(10)}
        states.append(state)
        print(label + ("：" + "，".join(f"与卖单{x.sell_id}成交{x.quantity}股，价格{x.price / 100:.2f}元" for x in trades) if trades else "：进入订单簿"))
    engine.cancel(6)
    states.append({"step": "撤销 B3 剩余200股", "trades": [], "book": engine.book.depth(10)})
    engine.book.assert_valid()
    write_json(Path(output) / "demo.json", states)
    print("撤销 B3 剩余200股。逐步订单簿已保存到 output/demo.json。")


def match(input_path, output):
    """用户自备的原始订单输入，不需要任何真实成交文件。"""
    rows = json.loads(Path(input_path).read_text())
    if not isinstance(rows, list):
        raise ValueError("订单输入应为JSON列表")
    engine = MatchingEngine()
    states = []
    for i, x in enumerate(rows, 1):
        typ = x["type"]
        t = clock_int(x.get("time", 0))
        if typ == "add":
            trades = engine.submit(Order(x["order_id"], x["side"], cents(x["price_yuan"]), x["quantity"], t, i), auction=x.get("auction", False))
        elif typ == "cancel":
            engine.cancel(x["order_id"], x.get("quantity"))
            trades = []
        elif typ == "uncross":
            trades = engine.uncross(t, i)
        else:
            raise ValueError(f"未知事件类型 {typ}")
        engine.book.assert_valid()
        states.append({"step": i, "input": x, "trades": [t.record() for t in trades],
                       "depth": engine.book.depth(10), "orders": [asdict(o) for o in engine.book.orders.values()]})
        print(f"第{i}步 {typ}：生成{len(trades)}笔成交，剩余{len(engine.book.orders)}笔订单")
    write_json(Path(output) / "custom_matching.json", {"price_unit": "整数分", "states": states})


def make_report(summary, output):
    aggregate = summary["aggregate"]
    rows = []
    for x in summary["results"]:
        if "error" in x:
            rows.append(f"<tr><td>{x['symbol']}</td><td colspan='5'>失败：{html.escape(x['error'])}</td></tr>")
            continue
        r, s = x["replay"], x["simulation"]
        snap = r["snapshot_check"]
        exact = all(c["ordered_trade_pairs_exact"] for c in s["comparisons"].values())
        rows.append(f"<tr><td>{x['symbol']}</td><td>{r['statistics']['events']:,}</td><td>{r['statistics']['trades']:,}</td><td>{'完全一致' if exact else '存在差异'}</td><td>{snap['depth10_exact']:,} / {snap['eligible']:,}</td><td>{'一致' if x['final_book_exact'] else '有差异'}</td></tr>")
    body = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>第三讲实践课 · 验证报告</title>
<style>body{{font-family:system-ui,-apple-system,sans-serif;background:#f4f6f8;color:#17232b;max-width:1080px;margin:40px auto;padding:0 24px;line-height:1.65}}h1{{font-size:30px}}.card{{background:white;border:1px solid #dbe2e7;border-radius:12px;padding:24px;margin:18px 0}}.metrics{{display:flex;gap:36px;flex-wrap:wrap}}.metrics b{{font-size:28px;display:block;color:#087f69}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;text-align:right;border-bottom:1px solid #edf0f2}}th:first-child,td:first-child{{text-align:left}}code{{background:#edf1f4;padding:2px 5px}}a{{color:#086b98}}footer{{font-size:13px;color:#596771}}</style>
<h1>第三讲实践课：订单簿与模拟撮合</h1><p>上证50 · 数据日期 2026-09-23 · {summary['completed_symbols']} / {summary['requested_symbols']} 只股票处理完成</p>
<div class="card metrics"><div><b>{aggregate['events']:,}</b>竞价行情事件</div><div><b>{aggregate['trades']:,}</b>竞价成交</div><div><b>{aggregate['snapshot_exact']:,} / {aggregate['snapshot_eligible']:,}</b>十档快照找到完全对应状态</div><div><b>{aggregate['all_trade_pairs_exact_symbols']}</b>成交顺序与配对完全一致的股票</div></div>
<div class="card"><h2>怎么理解结果</h2><p>原始委托是撮合后的剩余量。历史回放将新增、撤单和成交按同一通道的业务序号合并；模拟撮合先借助历史主动成交补回订单数量，再按价格优先、时间优先选择对手订单。集合竞价价格由订单簿计算。</p><p><strong>这项验证证明撮合与数据的一致性。</strong>主动委托的补回使用了真实成交信息；完全成交订单的原始限价和市价类型不能唯一恢复，采用能够复现已发生交易的等价限价。</p><p>快照没有业务序号。本报告在相同累计成交量和笔数、前后3秒内搜索候选事件状态，并核对40个十档价量字段以及买卖总委托量。该比例不能解释为“按快照时间直接查询”的准确率。集合竞价期间的虚拟盘口不纳入此项核对。</p><p>盘后固定价格交易的委托未在文件中提供，{aggregate['after_hours_trades']:,}笔盘后成交单独保存。集合竞价数据在阶段结束后批量发布；盘中集合竞价状态只能作事后重建，不能当作当时实时可见信息。</p></div>
<div class="card"><h2>逐股票核对</h2><table><thead><tr><th>股票</th><th>事件数</th><th>成交数</th><th>模拟成交</th><th>十档快照</th><th>完整最终订单簿</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<div class="card"><h2>课堂演示</h2><p><code>.venv/bin/python main.py demo</code>：逐步展示限价、排队、部分成交和撤单。</p><p><code>.venv/bin/python main.py book --symbol 600036 --time 10:00:00 --orders --save output/book_1000.json</code>：查询10点之后下一事件尚未到达前的完整订单簿。</p><p><code>.venv/bin/python main.py book --symbol 600036 --sequence 378781</code>：按确定的业务序号查询状态，消除相同时间戳内的顺序歧义。</p><p>价格内部以整数分存储；展示价格为元。每只股票目录包含事件日志、补回后的模拟输入、引擎生成的成交及逐快照差异。</p></div>
<footer>Python {summary['environment']['python']} / PyArrow {summary['environment']['pyarrow']} · 运行耗时 {summary['elapsed_seconds']:.1f} 秒 · 详细操作见项目 README.md</footer></html>"""
    (Path(output) / "report.html").write_text(body, encoding="utf-8")


def run(data, output, selected):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    results = []
    for i, symbol in enumerate(selected, 1):
        folder = output / str(symbol)
        try:
            replay, rs = replay_symbol(data, symbol, folder)
            engine, ss = simulate_symbol(data, symbol, folder)
            # 完整逐订单状态验证，远强于只比较买一卖一或十档。
            state = lambda b: {(oid, o.side, o.price, o.quantity) for oid, o in b.orders.items()}
            exact = state(replay.book) == state(engine.book)
            order_queue_exact = all([[o.order_id for o in q.values()] for q in replay.book.levels[s].values()] == [[o.order_id for o in q.values()] for q in engine.book.levels[s].values()] for s in ("B", "S"))
            result = {"symbol": symbol, "replay": rs, "simulation": ss, "final_book_exact": exact, "final_queue_order_exact": order_queue_exact}
            results.append(result)
            write_json(folder / "validation.json", result)
            all_trades = all(c["ordered_trade_pairs_exact"] for c in ss["comparisons"].values())
            print(f"[{i}/{len(selected)}] {symbol}：{rs['statistics']['events']:,}事件，成交{'一致' if all_trades else '存在差异'}，十档快照 {rs['snapshot_check']['depth10_exact']}/{rs['snapshot_check']['eligible']}，最终订单簿{'一致' if exact and order_queue_exact else '有差异'}", flush=True)
            del replay, engine
        except Exception as e:
            results.append({"symbol": symbol, "error": f"{type(e).__name__}: {e}"})
            print(f"[{i}/{len(selected)}] {symbol} 失败：{e}", flush=True)
        write_json(output / "progress.json", {"processed": len(results), "requested": len(selected), "results": [{"symbol": x["symbol"], "error": x.get("error")} for x in results]})
    good = [x for x in results if "error" not in x]
    aggregate = {"events": sum(x["replay"]["statistics"]["events"] for x in good),
                 "trades": sum(x["replay"]["statistics"]["trades"] for x in good),
                 "snapshot_exact": sum(x["replay"]["snapshot_check"]["depth10_exact"] for x in good),
                 "snapshot_eligible": sum(x["replay"]["snapshot_check"]["eligible"] for x in good),
                 "all_trade_pairs_exact_symbols": sum(all(c["ordered_trade_pairs_exact"] for c in x["simulation"]["comparisons"].values()) for x in good),
                 "full_final_book_exact_symbols": sum(x["final_book_exact"] and x["final_queue_order_exact"] for x in good),
                 "after_hours_trades": sum(x["replay"]["after_hours"]["trades"] for x in good)}
    passed = (len(good) == len(selected) and aggregate["all_trade_pairs_exact_symbols"] == len(selected)
              and aggregate["full_final_book_exact_symbols"] == len(selected)
              and all(x["replay"]["snapshot_check"]["depth10_and_totals_exact"] == x["replay"]["snapshot_check"]["eligible"] for x in good))
    summary = {"requested_symbols": len(selected), "completed_symbols": len(good), "passed": passed,
               "elapsed_seconds": time.monotonic() - start, "environment": {"python": platform.python_version(), "pyarrow": pa.__version__},
               "aggregate": aggregate, "results": results}
    write_json(output / "summary.json", summary)
    make_report(summary, output)
    print(f"结果已保存到 {output / 'report.html'}；核对{'通过' if passed else '存在未通过项目'}。")
    return 0 if passed else 1


def query(data, args):
    until = clock_int(args.time) if args.time else None
    replay, summary = replay_symbol(data, args.symbol, until=until, sequence=args.sequence)
    last = summary["last_event"]
    print(f"股票 {args.symbol} · 最后事件 {clock_text(last[1]) if last else '无'} · 序号 {last[0] if last else '无'} · 未成交订单 {len(replay.book.orders):,}笔")
    print("档位      买价(元)       买量(股)      卖价(元)       卖量(股)")
    depth = replay.book.depth(args.depth)
    for i in range(max(len(depth["bids"]), len(depth["asks"]))):
        b = depth["bids"][i] if i < len(depth["bids"]) else {"price": 0, "quantity": 0}
        a = depth["asks"][i] if i < len(depth["asks"]) else {"price": 0, "quantity": 0}
        print(f"{i + 1:>2} {b['price'] / 100:>14.2f} {b['quantity']:>14,} {a['price'] / 100:>14.2f} {a['quantity']:>14,}")
    summary["requested_time"] = until
    summary["requested_sequence"] = args.sequence
    summary["depth"] = depth
    summary["units"] = {"price": "整数分", "quantity": "股"}
    if args.orders:
        summary["orders"] = [asdict(o) for o in replay.book.orders.values()]
    if args.save:
        write_json(args.save, summary)
        print(f"已保存 {Path(args.save).resolve()}")


def check(data, output):
    summary = json.loads((Path(output) / "summary.json").read_text())
    issues = []
    if summary["completed_symbols"] != summary["requested_symbols"]:
        issues.append("存在未处理成功的股票")
    for x in summary["results"]:
        if "error" in x:
            issues.append(f"{x['symbol']}：{x['error']}")
            continue
        folder = Path(output) / str(x["symbol"])
        files_ok = True
        for file in ("events.parquet", "simulation_inputs.parquet", "simulated_trades.parquet", "snapshot_check.parquet"):
            if not (folder / file).is_file():
                issues.append(f"缺少 {folder / file}")
                files_ok = False
        if not files_ok:
            continue
        # 重新读取落盘结果，与源成交逐行比对，避免只信赖汇总或文件存在。
        source = pq.read_table(Path(data) / "exe_20260923.parquet", filters=[("Symbol", "=", x["symbol"]), ("Channel", "=", x["replay"]["channel"])]).sort_by([("BizIndex", "ascending")])
        expected = [(r["BidOrder"], r["AskOrder"], cents(r["Price"]), r["Volume"], r["Time"]) for r in source.to_pylist()]
        actual = [(r["buy_id"], r["sell_id"], r["price"], r["quantity"], r["time"]) for r in pq.read_table(folder / "simulated_trades.parquet").to_pylist()]
        if expected != actual:
            issues.append(f"{x['symbol']} 落盘成交与源数据逐行不一致")
        ev = pq.read_table(folder / "events.parquet", columns=["sequence", "time", "trade_volume", "trade_count"])
        if len(ev) != x["replay"]["statistics"]["events"] or pc.max(ev["trade_count"]).as_py() != len(source):
            issues.append(f"{x['symbol']} 事件日志行数/累计成交笔数不一致")
        snapshots = pq.read_table(folder / "snapshot_check.parquet").to_pylist()
        if not all(r["candidate_found"] and r["expected"] == r["actual"] and r["totals_match"] for r in snapshots):
            issues.append(f"{x['symbol']} 落盘快照候选状态不一致")
        if not x["final_book_exact"] or not x["final_queue_order_exact"]:
            issues.append(f"{x['symbol']} 最终订单簿或队列存在差异")
        if not all(c["ordered_trade_pairs_exact"] for c in x["simulation"]["comparisons"].values()):
            issues.append(f"{x['symbol']} 成交存在差异")
        snap = x["replay"]["snapshot_check"]
        if snap["depth10_and_totals_exact"] != snap["eligible"]:
            issues.append(f"{x['symbol']} 有快照未完全匹配，需要检查 snapshot_check.parquet")
    print("\n".join(issues) if issues else f"通过：{summary['completed_symbols']}只股票，成交、完整最终簿与候选快照状态均一致。")
    return 1 if issues else 0


def main():
    parser = argparse.ArgumentParser(description="第三讲实践课：模拟撮合与上证50订单簿")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect", help="查看数据字段、编码、范围与文件指纹")
    commands.add_parser("demo", help="课堂例子的逐步撮合")
    m = commands.add_parser("match", help="用自备原始订单模拟撮合，无需真实成交")
    m.add_argument("--input", type=Path, required=True)
    r = commands.add_parser("run", help="回放、模拟、核对并生成报告")
    group = r.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--symbol", type=int)
    b = commands.add_parser("book", help="按时间或业务序号查询订单簿")
    b.add_argument("--symbol", required=True, type=int)
    when = b.add_mutually_exclusive_group(required=True)
    when.add_argument("--time")
    when.add_argument("--sequence", type=int)
    b.add_argument("--depth", type=int, default=10)
    b.add_argument("--orders", action="store_true", help="保存完整逐订单状态")
    b.add_argument("--save", type=Path)
    commands.add_parser("check", help="检查已生成结果与核对记录")
    args = parser.parse_args()
    if args.command in ("book", "run") and not getattr(args, "all", False) and args.symbol not in symbols(args.data):
        parser.error("该股票不在本数据包中")
    if args.command == "book" and args.depth <= 0:
        parser.error("depth 必须为正整数")
    if args.command == "inspect":
        profile(args.data, args.output)
    elif args.command == "demo":
        demo(args.output)
    elif args.command == "match":
        match(args.input, args.output)
    elif args.command == "run":
        return run(args.data, args.output, symbols(args.data) if args.all else [args.symbol])
    elif args.command == "book":
        query(args.data, args)
    else:
        return check(args.data, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
