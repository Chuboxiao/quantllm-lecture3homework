"use strict";
// 浏览器演示版；价格用整数分，规则与 exchange/book.py 保持一致。
class DemoEngine {
  constructor() { this.orders = new Map(); this.seen = new Set(); }
  ordered(side) {
    return [...this.orders.values()].filter(o => o.side === side)
      .sort((a,b) => side === "B" ? b.price-a.price : a.price-b.price);
  }
  best(side) { return this.ordered(side)[0]; }
  cancel(id, quantity) {
    const order = this.orders.get(id);
    if (!order) throw new Error("订单不存在或已经成交");
    const q = quantity === undefined ? order.quantity : quantity;
    if (!Number.isSafeInteger(q) || q <= 0 || q > order.quantity) throw new Error("撤单数量无效");
    order.quantity -= q;
    if (!order.quantity) this.orders.delete(id);
    return q;
  }
  submit(input, auction = false) {
    const order = {...input};
    if (this.seen.has(order.order_id)) throw new Error("订单号重复使用");
    if (!["B","S"].includes(order.side) || !Number.isSafeInteger(order.price) || !Number.isSafeInteger(order.quantity) || order.price <= 0 || order.quantity <= 0) throw new Error("买卖方向、价格或数量无效");
    this.seen.add(order.order_id);
    const trades = [];
    if (!auction) {
      const other = order.side === "B" ? "S" : "B";
      while (order.quantity) {
        const maker = this.best(other);
        if (!maker || (order.side === "B" ? order.price < maker.price : order.price > maker.price)) break;
        const quantity = Math.min(order.quantity, maker.quantity);
        trades.push({buy_id:order.side === "B" ? order.order_id : maker.order_id,
          sell_id:order.side === "B" ? maker.order_id : order.order_id,
          price:maker.price, quantity});
        this.cancel(maker.order_id, quantity);
        order.quantity -= quantity;
      }
    }
    if (order.quantity) this.orders.set(order.order_id, order);
    return trades;
  }
  totals(side) {
    const levels = new Map();
    for (const o of this.ordered(side)) levels.set(o.price, (levels.get(o.price)||0)+o.quantity);
    return levels;
  }
  auctionPrice() {
    const bids = this.totals("B"), asks = this.totals("S");
    if (!bids.size || !asks.size || Math.max(...bids.keys()) < Math.min(...asks.keys())) return [null,0];
    const prices = [...new Set([...bids.keys(),...asks.keys()])].sort((a,b)=>a-b);
    let demand = [...bids.values()].reduce((a,b)=>a+b,0), supply = 0;
    const candidates = [];
    for (const p of prices) {
      supply += asks.get(p)||0;
      const quantity = Math.min(demand,supply);
      if (quantity > 0 && demand-(bids.get(p)||0) <= quantity && supply-(asks.get(p)||0) <= quantity) candidates.push([p,quantity,Math.abs(demand-supply)]);
      demand -= bids.get(p)||0;
    }
    const maximum = Math.max(...candidates.map(x=>x[1]));
    const residual = Math.min(...candidates.filter(x=>x[1]===maximum).map(x=>x[2]));
    const eligible = candidates.filter(x=>x[1]===maximum && x[2]===residual).map(x=>x[0]);
    return [Math.floor((eligible[0]+eligible.at(-1)+1)/2),maximum];
  }
  uncross() {
    let [price, remaining] = this.auctionPrice();
    const trades = [];
    if (price === null) return trades;
    while (remaining) {
      const buy = this.best("B"), sell = this.best("S");
      if (!buy || !sell || buy.price < price || sell.price > price) throw new Error("集合竞价队列不一致");
      const quantity = Math.min(buy.quantity,sell.quantity,remaining);
      trades.push({buy_id:buy.order_id,sell_id:sell.order_id,price,quantity});
      this.cancel(buy.order_id,quantity); this.cancel(sell.order_id,quantity); remaining -= quantity;
    }
    return trades;
  }
  depth(n = 10) {
    const result = {};
    for (const [side,name] of [["B","bids"],["S","asks"]]) {
      result[name] = [...this.totals(side)].slice(0,n).map(([price,quantity])=>({price,quantity,
        orders:[...this.orders.values()].filter(o=>o.side===side && o.price===price).length}));
    }
    return result;
  }
}
if (typeof module !== "undefined") module.exports = {DemoEngine};
