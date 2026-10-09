import unittest
from webapp import Application, HistoryCursor, Simulator, order_page


def fixture():
    def add(seq, oid, side, price, quantity, time):
        return seq, "ord", {"BizIndex": seq, "OrderKind": 65, "OrderOriNo": oid, "FunctionCode": ord(side),
                            "Price": price, "Volume": quantity, "Time": time}
    return [add(1, 1, "S", 10., 500, 93000000),
            (2, "exe", {"BizIndex": 2, "AskOrder": 1, "BidOrder": 2, "Price": 10., "Volume": 300, "BSFlag": 66, "Time": 93000010}),
            add(3, 2, "B", 9.99, 100, 93000010),
            (4, "ord", {"BizIndex": 4, "OrderKind": 68, "OrderOriNo": 2, "FunctionCode": 66,
                         "Price": 9.99, "Volume": 100, "Time": 93000020})]


class WebHistoryTests(unittest.TestCase):
    def test_seek_timestamp_includes_all_same_time_events(self):
        h = HistoryCursor(fixture(), 600036, 1005)
        s = h.seek_time("09:30:00.010")
        self.assertEqual((s["index"], s["trade_volume"], s["order_count"]), (2, 300, 2))
        self.assertEqual(s["depth"]["asks"][0]["quantity"], 200)
        self.assertEqual(s["depth"]["bids"][0]["quantity"], 100)

    def test_backward_seek_rebuilds_order_quantities(self):
        h = HistoryCursor(fixture(), 600036, 1005)
        h.seek(3)
        s = h.seek(0)
        self.assertEqual((s["trade_count"], s["order_count"], s["depth"]["asks"][0]["quantity"]), (0, 1, 500))
        s = h.seek(3)
        self.assertEqual((s["trade_count"], s["order_count"], s["depth"]["asks"][0]["quantity"]), (1, 1, 200))

    def test_order_queue_is_fifo_and_paginated(self):
        s = Simulator()
        q = order_page(s.engine.book, "S", 1000, 0, 1)
        self.assertEqual((q["total"], q["orders"][0]["order_id"]), (2, 1))
        self.assertEqual(order_page(s.engine.book, "S", 1000, 1, 1)["orders"][0]["order_id"], 2)


class WebSimulatorTests(unittest.TestCase):
    def test_submit_and_cancel_updates_existing_engine(self):
        sim = Simulator()
        state = sim.act({"action": "order", "side": "B", "price": "10.00", "quantity": 1000})
        self.assertEqual((state["trade_count"], state["trade_volume"]), (2, 800))
        self.assertEqual(sim.engine.book.orders[6].quantity, 200)
        state = sim.act({"action": "cancel", "order_id": 6})
        self.assertNotIn(6, sim.engine.book.orders)
        self.assertEqual(state["trade_volume"], 800)

    def test_call_auction_is_delayed_and_clears_at_single_price(self):
        sim = Simulator()
        sim.act({"action": "reset", "seed": False})
        sim.act({"action": "phase", "phase": "auction"})
        sim.act({"action": "order", "side": "B", "price": "10.10", "quantity": 100})
        state = sim.act({"action": "order", "side": "S", "price": "10.00", "quantity": 100})
        self.assertEqual((state["trade_count"], state["auction_price"], state["auction_quantity"]), (0, 1005, 100))
        with self.assertRaises(ValueError):
            sim.act({"action": "phase", "phase": "continuous"})
        state = sim.act({"action": "uncross"})
        self.assertEqual((state["trade_count"], state["trade_volume"], state["trades"][0]["price"], state["order_count"]), (1, 100, 1005, 0))

    def test_rejected_order_does_not_change_book(self):
        sim = Simulator()
        before = sim.state()
        for quantity in [-1, 0, 1.5, True]:
            with self.assertRaises(ValueError):
                sim.act({"action": "order", "side": "B", "price": "10", "quantity": quantity})
        self.assertEqual(sim.state()["depth"], before["depth"])
        self.assertEqual(sim.state()["trade_count"], 0)

    def test_browser_sessions_do_not_share_simulated_orders(self):
        app = Application()
        a, b = app.new_session()["session"], app.new_session()["session"]
        app.request("POST", "/api/simulator", {"session": a, "action": "demo"})
        self.assertEqual(app.request("GET", f"/api/simulator?session={a}")["trade_count"], 2)
        self.assertEqual(app.request("GET", f"/api/simulator?session={b}")["trade_count"], 0)


if __name__ == "__main__":
    unittest.main()
