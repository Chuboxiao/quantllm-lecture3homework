"use strict";
const $ = id => document.getElementById(id);
const number = x => Number(x ?? 0).toLocaleString("zh-CN");
const price = x => x == null || x === 0 ? "—" : (x / 100).toFixed(2);
let simState, engine, nextId, phase, trades, side="B";
function toast(message){$("toast").textContent=message;$("toast").hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("toast").hidden=true,4500);}
function reset(seed=true){engine=new DemoEngine();nextId=1;phase="continuous";trades=[];if(seed)for(const [side,price,quantity] of [["S",1000,300],["S",1000,500],["S",1001,600],["B",999,400],["B",998,700]])engine.submit({order_id:nextId++,side,price,quantity});}
function refresh(message){const orders=[...engine.orders.values()];const [auction_price,auction_quantity]=engine.auctionPrice();simState={depth:engine.depth(),order_count:orders.length,buy_quantity:orders.filter(o=>o.side==="B").reduce((n,o)=>n+o.quantity,0),sell_quantity:orders.filter(o=>o.side==="S").reduce((n,o)=>n+o.quantity,0),trade_count:trades.length,trade_volume:trades.reduce((n,t)=>n+t.quantity,0),orders:orders.slice(0,100),trades:trades.slice(-100).reverse(),phase,next_id:nextId,auction_price,auction_quantity,message};renderSimulator();}
function simAction(body){try{let result=[],message="";switch(body.action){
case "reset":reset(body.seed);message=body.seed?"已恢复示例盘口：10元两笔卖单依次为300股和500股。":"空订单簿，等待你的第一笔委托。";break;
case "phase":{if(!["continuous","auction"].includes(body.phase))throw new Error("未知撮合方式");const b=engine.best("B"),s=engine.best("S");if(body.phase==="continuous"&&b&&s&&b.price>=s.price)throw new Error("买卖报价已相交，请先统一撮合，再切换连续竞价");phase=body.phase;message=phase==="auction"?"集合竞价：订单先排队，点击统一撮合后成交。":"连续竞价：新增订单立即按价格与时间优先撮合。";break;}
case "demo":reset();body={action:"order",side:"B",price:"10.00",quantity:1000};
case "order":{const text=String(body.price).trim();if(!/^\d+(\.\d{1,2})?$/.test(text))throw new Error("价格应为最多两位小数的正数");const p=Math.round(Number(text)*100),q=body.quantity;if(!Number.isSafeInteger(q)||q<1||q>100000000||p<1||p>10000000||!["B","S"].includes(body.side))throw new Error("请填写有效的价格、数量和买卖方向");const oid=nextId;result=engine.submit({order_id:oid,side:body.side,price:p,quantity:q},phase==="auction");nextId++;const filled=result.reduce((n,t)=>n+t.quantity,0),remaining=engine.orders.get(oid)?.quantity||0;message=`订单 #${oid}：${body.side==="B"?"买入":"卖出"} ${number(q)}股，限价 ${price(p)}元。`+(phase==="auction"?"已加入集合竞价队列，等待统一撮合。":`生成${result.length}笔成交，共${number(filled)}股；剩余${number(remaining)}股排队。`);break;}
case "cancel":{const q=engine.cancel(body.order_id);message=`订单 #${body.order_id} 已撤销剩余${number(q)}股。`;break;}
case "uncross":if(phase!=="auction")throw new Error("请先切换集合竞价");result=engine.uncross();message=result.length?`统一撮合：${result.length}笔成交，共${number(result.reduce((n,t)=>n+t.quantity,0))}股，成交价 ${price(result[0].price)}元。`:"当前没有可以成交的买卖订单。";break;
default:throw new Error("未知操作");}trades.push(...result);refresh(message);}catch(e){toast(e.message);}}
function metric(label, value, sub = "", accent = false) {
  return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value ${accent ? "accent" : ""}">${value}</div><div class="metric-sub">${sub}</div></div>`;
}
function renderBook(id, state, clickable = false) {
  const {bids, asks} = state.depth;
  const maximum = Math.max(1, ...bids.map(x => x.quantity), ...asks.map(x => x.quantity));
  let content = `<div class="book-head"><div class="book-side-head"><span>买量 / 股</span><span>买价 / 元</span></div><span></span><div class="book-side-head"><span>卖价 / 元</span><span>卖量 / 股</span></div></div>`;
  for (let i = 0; i < 10; i++) {
    const b = bids[i], a = asks[i];
    function level(item, s) {
      const klass = s === "B" ? "buy" : "sell";
      const fill = item ? Math.max(2, item.quantity / maximum * 100) : 0;
      const attr = clickable && item ? `data-queue-side="${s}" data-price="${item.price}" aria-label="查看${s === "B" ? "买" : "卖"}价${price(item.price)}的排队订单"` : `tabindex="-1"`;
      const contents = s === "B" ? `<span>${item ? number(item.quantity) : "—"}</span><b>${item ? price(item.price) : "—"}</b>` : `<b>${item ? price(item.price) : "—"}</b><span>${item ? number(item.quantity) : "—"}</span>`;
      return `<${clickable ? "button" : "div"} class="depth-level ${klass}" style="--fill:${fill}%" ${attr}>${contents}</${clickable ? "button" : "div"}>`;
    }
    content += `<div class="book-row">${level(b,"B")}<span class="level-number">${i + 1}</span>${level(a,"S")}</div>`;
  }
  const spread = bids.length && asks.length ? asks[0].price - bids[0].price : null;
  content += `<div class="book-spread"><span>买卖价差 <strong>${spread == null ? "—" : spread < 0 ? "报价相交，待统一撮合" : (spread / 100).toFixed(2) + " 元"}</strong></span><span>总挂单 <strong>${number(state.buy_quantity + state.sell_quantity)} 股</strong></span></div>`;
  $(id).innerHTML = content;
  if (clickable) $(id).querySelectorAll("[data-queue-side]").forEach(el => el.addEventListener("click", () => {
    pause(); queue = {side:el.dataset.queueSide,price:Number(el.dataset.price),offset:0}; showQueue();
  }));
}
function renderSimulator() {
  const s=simState;
  $("sim-metrics").innerHTML=metric("生成成交",number(s.trade_count),"笔")+metric("累计成交量",number(s.trade_volume),"股")+metric("待成交订单",number(s.order_count),"笔",true);
  renderBook("sim-book",s);
  $("sim-message").textContent=s.message;
  $("next-order").textContent=`#${s.next_id}`;
  $("sim-order-count").textContent=`${number(s.order_count)}笔`;
  document.querySelectorAll("[data-phase]").forEach(el=>el.classList.toggle("selected",el.dataset.phase===s.phase));
  $("auction-controls").hidden=s.phase!=="auction";
  $("auction-price").textContent=price(s.auction_price)+(s.auction_price ? "元" : "");
  $("auction-quantity").textContent=number(s.auction_quantity);
  $("rule-title").textContent=s.phase==="auction" ? "新增订单先进入队列" : "新订单可以立即成交";
  $("rule-text").textContent=s.phase==="auction" ? "统一撮合时选择可实现最大成交量的价格，全部交易使用同一成交价。" : "买价达到卖价，或卖价低至买价，就与已有对手单成交。剩余数量继续排队。";
  $("sim-orders").innerHTML=s.orders.length ? `<table><thead><tr><th>订单号</th><th>方向</th><th>限价 / 元</th><th>剩余 / 股</th><th></th></tr></thead><tbody>${s.orders.map(o=>`<tr><td>#${o.order_id}</td><td class="${o.side==="B"?"buy-text":"sell-text"}">${o.side==="B"?"买入":"卖出"}</td><td>${price(o.price)}</td><td>${number(o.quantity)}</td><td><button class="cancel-button" data-cancel="${o.order_id}">撤单</button></td></tr>`).join("")}</tbody></table>${s.order_count>100?`<p class="footnote">显示前100笔未成交订单。</p>`:""}` : `<div class="empty">订单簿是空的<br>提交一笔订单，开始观察市场</div>`;
  $("sim-orders").querySelectorAll("[data-cancel]").forEach(el=>el.onclick=()=>simAction({action:"cancel",order_id:Number(el.dataset.cancel)}));
  $("sim-trades").innerHTML=s.trades.length ? `<table><thead><tr><th>买单</th><th>卖单</th><th>成交价 / 元</th><th>数量 / 股</th></tr></thead><tbody>${s.trades.map(t=>`<tr><td>#${t.buy_id}</td><td>#${t.sell_id}</td><td>${price(t.price)}</td><td>${number(t.quantity)}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">还没有成交<br>试试以10元买入1,000股</div>`;
}

document.querySelectorAll("[data-tab]").forEach(el=>el.onclick=()=>{document.querySelectorAll(".view").forEach(v=>v.hidden=v.id!==el.dataset.tab);document.querySelectorAll("[data-tab]").forEach(n=>{n.classList.toggle("active",n===el);n.setAttribute("aria-selected",n===el?"true":"false");});$("breadcrumb").textContent=el.dataset.tab==="simulator"?"模拟交易所":"验证结果";});
document.querySelectorAll("[data-side]").forEach(el=>el.onclick=()=>{side=el.dataset.side;document.querySelectorAll("[data-side]").forEach(b=>b.classList.toggle("selected",b===el));$("submit-order").textContent=`提交${side==="B"?"买":"卖"}单 ↗`;$("submit-order").classList.toggle("sell-button",side==="S");});
$("order-form").onsubmit=e=>{e.preventDefault();simAction({action:"order",side,price:$("order-price").value,quantity:Number($("order-quantity").value)});};
$("demo-button").onclick=()=>simAction({action:"demo"});$("seed-button").onclick=()=>simAction({action:"reset",seed:true});$("clear-button").onclick=()=>simAction({action:"reset",seed:false});document.querySelectorAll("[data-phase]").forEach(el=>el.onclick=()=>simAction({action:"phase",phase:el.dataset.phase}));$("uncross-button").onclick=()=>simAction({action:"uncross"});
$("validation-metrics").innerHTML=metric("股票覆盖","50<small>只</small>","上证50数据",true)+metric("竞价事件","10,066,831","本地Python全量处理")+metric("成交逐条一致","3,790,471","历史一致性验证")+metric("匹配快照","236,674","限定候选范围内完全一致");
reset();refresh("示例盘口已就绪：10元有300股和500股两笔卖单。试试买入1,000股，观察成交与剩余量。");
