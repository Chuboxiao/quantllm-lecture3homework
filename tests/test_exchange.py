import random
import unittest
from exchange.book import Order, MatchingEngine, OrderBook, cents, clock_int
from exchange.replay import HistoricalReplay
from exchange.simulate import reconstruct_inputs


class MatchingTests(unittest.TestCase):
    def test_price_then_time_and_partial_fill(self):
        e = MatchingEngine()
        e.submit(Order(1, "S", 1001, 100))
        e.submit(Order(2, "S", 1000, 300))
        e.submit(Order(3, "S", 1000, 500))
        trades = e.submit(Order(4, "B", 1000, 1000))
        self.assertEqual([(t.sell_id, t.price, t.quantity) for t in trades], [(2, 1000, 300), (3, 1000, 500)])
        self.assertEqual(e.book.orders[4].quantity, 200)
        self.assertEqual(e.book.best("S").order_id, 1)
        e.book.assert_valid()

    def test_seller_takes_existing_buy_price(self):
        e = MatchingEngine()
        e.submit(Order(1, "B", 1005, 100))
        e.submit(Order(2, "B", 1004, 200))
        t = e.submit(Order(3, "S", 1000, 200))
        self.assertEqual([(x.buy_id, x.price, x.quantity) for x in t], [(1, 1005, 100), (2, 1004, 100)])
        self.assertEqual(e.book.orders[2].quantity, 100)

    def test_cancel_partial_and_remove_level(self):
        e = MatchingEngine()
        e.submit(Order(1, "B", 1000, 300))
        e.submit(Order(2, "B", 1000, 100))
        e.cancel(1, 200)
        self.assertEqual(e.book.totals["B"][1000], 200)
        e.cancel(1)
        self.assertEqual(e.book.best("B").order_id, 2)
        e.cancel(2)
        self.assertIsNone(e.book.best("B"))
        e.book.assert_valid()

    def test_invalid_events_fail_without_mutation(self):
        e = MatchingEngine()
        e.submit(Order(1, "B", 1000, 100))
        with self.assertRaises(ValueError):
            e.cancel(1, 101)
        with self.assertRaises(KeyError):
            e.cancel(100)
        with self.assertRaises(ValueError):
            e.submit(Order(1, "S", 1000, 100))
        self.assertEqual(e.book.orders[1].quantity, 100)

    def test_depth_selects_highest_bids_and_lowest_asks(self):
        b = OrderBook()
        for i in range(20):
            b.add(Order(i + 1, "B", 900 + i, 100))
            b.add(Order(i + 21, "S", 1000 + i, 200))
        self.assertEqual([x["price"] for x in b.depth(3)["bids"]], [919, 918, 917])
        self.assertEqual([x["price"] for x in b.depth(3)["asks"]], [1000, 1001, 1002])

    def test_auction_no_immediate_match_and_midpoint(self):
        e = MatchingEngine()
        self.assertEqual(e.submit(Order(1, "B", 1010, 100), auction=True), [])
        self.assertEqual(e.submit(Order(2, "S", 1000, 100), auction=True), [])
        self.assertEqual(e.auction_price(), (1005, 100))
        t = e.uncross(92500000, 10)
        self.assertEqual([(x.buy_id, x.sell_id, x.price, x.quantity) for x in t], [(1, 2, 1005, 100)])
        self.assertFalse(e.book.orders)

    def test_auction_volume_priority_and_same_price_fifo(self):
        e = MatchingEngine()
        for o in [Order(1, "B", 1000, 300), Order(2, "B", 1000, 200), Order(3, "S", 990, 100), Order(4, "S", 1000, 300), Order(5, "S", 1010, 200)]:
            e.submit(o, auction=True)
        self.assertEqual(e.auction_price(), (1000, 400))
        t = e.uncross(150000000, 100)
        self.assertEqual([(x.buy_id, x.sell_id, x.quantity) for x in t], [(1, 3, 100), (1, 4, 200), (2, 4, 100)])
        self.assertEqual(e.book.orders[2].quantity, 100)
        self.assertEqual(e.book.orders[5].quantity, 200)
        e.book.assert_valid()

    def test_auction_half_cent_rounds_up(self):
        e = MatchingEngine()
        e.submit(Order(1, "B", 1001, 100), auction=True)
        e.submit(Order(2, "S", 1000, 100), auction=True)
        self.assertEqual(e.auction_price(), (1001, 100))

    def test_randomized_conservation_and_naive_reference(self):
        rng = random.Random(20260923)
        e = MatchingEngine()
        naive = []
        submitted = executed = canceled = 0
        for oid in range(1, 1501):
            if naive and rng.random() < .2:
                item = rng.choice(naive)
                q = rng.randint(1, item[3])
                e.cancel(item[0], q)
                item[3] -= q
                if item[3] == 0:
                    naive.remove(item)
                canceled += q
            else:
                side, price, q = rng.choice(["B", "S"]), rng.randint(995, 1005), rng.randint(1, 1000)
                submitted += q
                expected = []
                remaining = q
                while remaining:
                    options = [x for x in naive if x[1] != side and (x[2] <= price if side == "B" else x[2] >= price)]
                    if not options:
                        break
                    maker = min(options, key=lambda x: (x[2] if side == "B" else -x[2], x[0]))
                    qty = min(remaining, maker[3])
                    expected.append((oid if side == "B" else maker[0], maker[0] if side == "B" else oid, maker[2], qty))
                    remaining -= qty
                    maker[3] -= qty
                    if not maker[3]:
                        naive.remove(maker)
                if remaining:
                    naive.append([oid, side, price, remaining])
                actual = e.submit(Order(oid, side, price, q))
                self.assertEqual([(x.buy_id, x.sell_id, x.price, x.quantity) for x in actual], expected)
                executed += sum(x.quantity for x in actual)
            self.assertEqual(submitted, 2 * executed + canceled + sum(x.quantity for x in e.book.orders.values()))
            e.book.assert_valid()


class DataSemanticsTests(unittest.TestCase):
    def test_float32_and_clock_normalization(self):
        self.assertEqual(cents(40.83000183105469), 4083)
        self.assertEqual(clock_int("09:30:00.030"), 93000030)
        with self.assertRaises(ValueError):
            clock_int("25:00:00")

    def test_unpublished_active_order_is_not_double_decremented(self):
        r = HistoricalReplay()
        def add(oid, side, q):
            return {"OrderKind": 65, "OrderOriNo": oid, "FunctionCode": ord(side), "Price": 10., "Volume": q, "Time": 93000000, "BizIndex": oid}
        r.apply("ord", add(1, "S", 500))
        r.apply("exe", {"BidOrder": 2, "AskOrder": 1, "BSFlag": 66, "Price": 10., "Volume": 300, "Time": 93000010, "BizIndex": 3})
        r.apply("ord", add(2, "B", 100))
        self.assertEqual(r.book.orders[1].quantity, 200)
        self.assertEqual(r.book.orders[2].quantity, 100)
        self.assertEqual(r.volume, 300)

    def test_missing_passive_order_is_error(self):
        r = HistoricalReplay()
        with self.assertRaises(ValueError):
            r.apply("exe", {"BidOrder": 2, "AskOrder": 1, "BSFlag": 66, "Volume": 100, "BizIndex": 1})

    def test_reconstruct_initial_volume_and_skip_residual(self):
        trade = {"BidOrder": 2, "AskOrder": 1, "BSFlag": 66, "Price": 10., "Volume": 300, "Time": 93000010, "BizIndex": 3}
        residual = {"OrderKind": 65, "OrderOriNo": 2, "FunctionCode": 66, "Price": 10.01, "Volume": 100, "Time": 93000010, "BizIndex": 4}
        inputs, _ = reconstruct_inputs([(3, "exe", trade), (4, "ord", residual)])
        self.assertEqual(len(inputs), 1)
        self.assertEqual((inputs[0]["quantity"], inputs[0]["price"], inputs[0]["sequence"]), (400, 1001, 3))
        self.assertFalse(inputs[0]["price_inferred"])


if __name__ == "__main__":
    unittest.main()
