from collections import OrderedDict
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from sortedcontainers import SortedDict


def cents(value):
    """Parquet 的 float32 价格先归一到分，避免比较浮点价格。"""
    if not isfinite(float(value)):
        raise ValueError("价格必须有限")
    return int(Decimal(str(float(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def clock_text(t):
    return f"{t // 10000000:02d}:{t // 100000 % 100:02d}:{t // 1000 % 100:02d}.{t % 1000:03d}"


def clock_int(s):
    if isinstance(s, int) or s.isdigit():
        t = int(s)
    else:
        h, m, seconds = s.split(":")
        sec, _, ms = seconds.partition(".")
        if len(ms) > 3 or (ms and not ms.isdigit()):
            raise ValueError("时间小数最多为三位毫秒")
        t = int(h) * 10000000 + int(m) * 100000 + int(sec) * 1000 + int(ms.ljust(3, "0"))
    if not (0 <= t // 10000000 < 24 and 0 <= t // 100000 % 100 < 60 and 0 <= t // 1000 % 100 < 60):
        raise ValueError("时间应为 HH:MM:SS.mmm")
    return t


@dataclass(slots=True)
class Order:
    order_id: int
    side: str
    price: int
    quantity: int
    time: int = 0
    sequence: int = 0


@dataclass(slots=True)
class Trade:
    buy_id: int
    sell_id: int
    price: int
    quantity: int
    time: int
    sequence: int
    phase: str = "continuous"

    def record(self):
        return asdict(self)


class OrderBook:
    """价格有序、同价 FIFO；可按订单号 O(1) 定位撤单。"""

    def __init__(self):
        self.orders = {}
        self.levels = {"B": SortedDict(), "S": SortedDict()}
        self.totals = {"B": {}, "S": {}}
        self.side_quantity = {"B": 0, "S": 0}

    def add(self, order):
        if order.side not in self.levels or not isinstance(order.price, int) or not isinstance(order.quantity, int) or order.price <= 0 or order.quantity <= 0:
            raise ValueError(f"非法订单 {order}")
        if order.order_id in self.orders:
            raise ValueError(f"重复订单号 {order.order_id}")
        self.orders[order.order_id] = order
        self.levels[order.side].setdefault(order.price, OrderedDict())[order.order_id] = order
        self.totals[order.side][order.price] = self.totals[order.side].get(order.price, 0) + order.quantity
        self.side_quantity[order.side] += order.quantity

    def reduce(self, order_id, quantity=None):
        o = self.orders.get(order_id)
        if o is None:
            raise KeyError(f"未知订单号 {order_id}")
        q = o.quantity if quantity is None else quantity
        if not isinstance(q, int) or q <= 0 or q > o.quantity:
            raise ValueError(f"订单 {order_id} 可扣减 {o.quantity}，实际要求 {q}")
        o.quantity -= q
        self.totals[o.side][o.price] -= q
        self.side_quantity[o.side] -= q
        if o.quantity == 0:
            del self.orders[order_id]
            del self.levels[o.side][o.price][order_id]
            if not self.levels[o.side][o.price]:
                del self.levels[o.side][o.price]
                del self.totals[o.side][o.price]
        return q

    def best(self, side):
        levels = self.levels[side]
        if not levels:
            return None
        _, queue = levels.peekitem(-1 if side == "B" else 0)
        return next(iter(queue.values()))

    def depth(self, n=10):
        result = {}
        for side, name in [("B", "bids"), ("S", "asks")]:
            levels = self.levels[side]
            prices = list(levels.islice(start=max(0, len(levels) - n), reverse=True)) if side == "B" else list(levels.islice(stop=n))
            result[name] = [{"price": p, "quantity": self.totals[side][p], "orders": len(self.levels[side][p])} for p in prices]
        return result

    def assert_valid(self):
        ids = set()
        for side, levels in self.levels.items():
            total = 0
            for p, queue in levels.items():
                q = sum(o.quantity for o in queue.values())
                assert q > 0 and q == self.totals[side][p]
                total += q
                for oid, o in queue.items():
                    assert oid not in ids and o.quantity > 0 and o.price == p and o.side == side
                    assert self.orders[oid] is o
                    ids.add(oid)
            assert total == self.side_quantity[side]
        assert ids == set(self.orders)


class MatchingEngine:
    """限价订单：连续竞价与集合竞价，不依赖真实成交来决定对手单。"""

    def __init__(self):
        self.book = OrderBook()
        self.seen = set()

    def submit(self, order, auction=False):
        if order.order_id in self.seen:
            raise ValueError(f"订单号重复使用 {order.order_id}")
        if order.side not in ("B", "S") or not isinstance(order.price, int) or not isinstance(order.quantity, int) or order.price <= 0 or order.quantity <= 0:
            raise ValueError("买卖方向、价格或数量无效")
        self.seen.add(order.order_id)
        trades = []
        if not auction:
            other = "S" if order.side == "B" else "B"
            while order.quantity:
                maker = self.book.best(other)
                if maker is None or (order.side == "B" and order.price < maker.price) or (order.side == "S" and order.price > maker.price):
                    break
                q = min(order.quantity, maker.quantity)
                trades.append(Trade(order.order_id if order.side == "B" else maker.order_id,
                                    maker.order_id if order.side == "B" else order.order_id,
                                    maker.price, q, order.time, order.sequence))
                self.book.reduce(maker.order_id, q)
                order.quantity -= q
        if order.quantity:
            self.book.add(order)
        return trades

    def cancel(self, order_id, quantity=None):
        return self.book.reduce(order_id, quantity)

    def auction_price(self):
        """最大成交量 -> 高买低卖全成交/同价至少一边全成交 -> 最小未成交量 -> 中间价。"""
        bids, asks = self.book.totals["B"], self.book.totals["S"]
        if not bids or not asks or max(bids) < min(asks):
            return None, 0
        prices = sorted(set(bids) | set(asks))
        demand = self.book.side_quantity["B"]
        supply = 0
        candidates = []
        for p in prices:
            supply += asks.get(p, 0)
            quantity = min(demand, supply)
            higher = demand - bids.get(p, 0)
            lower = supply - asks.get(p, 0)
            if quantity > 0 and higher <= quantity and lower <= quantity:
                candidates.append((p, quantity, abs(demand - supply)))
            demand -= bids.get(p, 0)
        maximum = max(q for _, q, _ in candidates)
        residual = min(r for _, q, r in candidates if q == maximum)
        eligible = [p for p, q, r in candidates if q == maximum and r == residual]
        # 中间价按最高、最低候选的中点，再四舍五入到一分钱。
        return (eligible[0] + eligible[-1] + 1) // 2, maximum

    def uncross(self, time, sequence, phase="auction"):
        price, remaining = self.auction_price()
        if price is None:
            return []
        trades = []
        while remaining:
            buy, sell = self.book.best("B"), self.book.best("S")
            if buy is None or sell is None or buy.price < price or sell.price > price:
                raise AssertionError("集合竞价成交数量与可成交队列不一致")
            q = min(buy.quantity, sell.quantity, remaining)
            trades.append(Trade(buy.order_id, sell.order_id, price, q, time, sequence, phase))
            self.book.reduce(buy.order_id, q)
            self.book.reduce(sell.order_id, q)
            remaining -= q
        return trades
