"""将浏览器撮合结果与 Python 引擎逐步比较；需要 Node.js。"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from exchange.book import MatchingEngine, Order


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    if not args.node:
        parser.error("请安装 Node.js 或通过 --node 提供路径")
    rng = random.Random(20260923)
    cases, expected = [], []

    def run(actions):
        engine = MatchingEngine()
        states = []
        for a in actions:
            if a["type"] == "A":
                trades = engine.submit(Order(a["id"], a["side"], a["price"], a["quantity"]), auction=a.get("auction", False))
            elif a["type"] == "D":
                engine.cancel(a["id"], a["quantity"])
                trades = []
            else:
                trades = engine.uncross(150000000, 0)
            engine.book.assert_valid()
            states.append({"trades": [{k: v for k, v in asdict(t).items() if k in ("buy_id", "sell_id", "price", "quantity")} for t in trades],
                           "orders": sorted([[o.order_id, o.side, o.price, o.quantity] for o in engine.book.orders.values()]),
                           "depth": engine.book.depth(10), "auction": list(engine.auction_price())})
        cases.append(actions)
        expected.append(states)
        return engine

    # 连续竞价包含随机部分撤单，以独立 Python 状态选择当前可撤订单。
    engine, actions = MatchingEngine(), []
    for oid in range(1, 1001):
        if engine.book.orders and rng.random() < .2:
            order = rng.choice(list(engine.book.orders.values()))
            q = rng.randint(1, order.quantity)
            actions.append({"type": "D", "id": order.order_id, "quantity": q})
            engine.cancel(order.order_id, q)
        else:
            side, price, q = rng.choice(["B", "S"]), rng.randint(990, 1010), rng.randint(1, 1000)
            actions.append({"type": "A", "id": oid, "side": side, "price": price, "quantity": q})
            engine.submit(Order(oid, side, price, q))
    run(actions)
    # 多个集合竞价簿检查定价、成交顺序和剩余队列。
    for _ in range(100):
        actions = [{"type": "A", "id": oid, "side": rng.choice(["B", "S"]), "price": rng.randint(990, 1010),
                    "quantity": rng.randint(1, 1000), "auction": True} for oid in range(1, 51)]
        actions.append({"type": "U"})
        run(actions)
    script = r'''
const {DemoEngine}=require(process.argv[1]);
const cases=JSON.parse(require('fs').readFileSync(0,'utf8'));
const output=cases.map(actions=>{const engine=new DemoEngine();return actions.map(a=>{
 let trades=[];
 if(a.type==='A')trades=engine.submit({order_id:a.id,side:a.side,price:a.price,quantity:a.quantity},a.auction||false);
 else if(a.type==='D')engine.cancel(a.id,a.quantity);else trades=engine.uncross();
 return {trades,orders:[...engine.orders.values()].map(o=>[o.order_id,o.side,o.price,o.quantity]).sort((a,b)=>a[0]-b[0]),depth:engine.depth(),auction:engine.auctionPrice()};
});});
process.stdout.write(JSON.stringify(output));
'''
    result = subprocess.run([args.node, "-e", script, str(ROOT / "docs/engine.js")], input=json.dumps(cases), capture_output=True, text=True, check=True)
    actual = json.loads(result.stdout)
    for i, (want, got) in enumerate(zip(expected, actual)):
        for j, (a, b) in enumerate(zip(want, got)):
            if a != b:
                raise AssertionError(f"第{i + 1}组第{j + 1}步的成交或订单簿不一致")
    assert len(actual) == len(expected) and all(len(a) == len(b) for a, b in zip(actual, expected))
    print(f"通过：{len(cases)}组，{sum(map(len, cases))}步，浏览器版与Python版的成交、剩余订单、十档盘口及竞价价格逐步一致。")


if __name__ == "__main__":
    main()
