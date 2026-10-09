"use strict";
const $ = id => document.getElementById(id);
const number = x => Number(x ?? 0).toLocaleString("zh-CN");
const price = x => x == null || x === 0 ? "—" : (x / 100).toFixed(2);
const safe = x => String(x ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let session = "", historyState = null, simState = null, series = [], busy = false, playing = false, playTimer = null, side = "B", queue = null;
const phases = {before_open:"开盘前",open_call:"开盘集合竞价",continuous:"连续竞价",close_call:"收盘集合竞价",closed:"竞价结束",after_hours:"盘后阶段"};

async function api(path, body) {
  const options = body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...body,session})};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "请求没有完成");
  return data;
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toast.timeout);
  toast.timeout = setTimeout(() => $("toast").hidden = true, 4500);
}
function setBusy(value) {
  busy = value;
  $("loading").hidden = !value;
  document.querySelectorAll(".view button, .view select, #timeline").forEach(el => {
    if (value) {el.dataset.beforeBusy = el.disabled ? "1" : "0"; el.disabled = !(el.id === "play" && playing);}
    else if (el.dataset.beforeBusy !== undefined) {el.disabled = el.dataset.beforeBusy === "1"; delete el.dataset.beforeBusy;}
  });
}
async function perform(fn) {
  if (busy) return;
  setBusy(true);
  try { await fn(); }
  catch (error) { pause(); toast(error.message); if (historyState) $("symbol").value = historyState.symbol; }
  finally { setBusy(false); }
}
function metric(label, value, sub = "", accent = false) {
  return `<div class="metric"><div class="metric-label">${label}</div><div class="metric-value ${accent ? "accent" : ""}">${value}</div><div class="metric-sub">${sub}</div></div>`;
}
function pause() {
  playing = false;
  clearTimeout(playTimer);
  $("play").innerHTML = "<span>▶</span> 播放";
}
async function historyAction(body, manual = true) {
  if (manual) pause();
  await perform(async () => {
    const state = await api("/api/history", {symbol:Number($("symbol").value),...body});
    historyState = state;
    if (state.series) series = state.series;
    renderHistory();
    $("queue-panel").hidden = true;
    queue = null;
  });
}
async function loop() {
  if (!playing) return;
  if (historyState.index >= historyState.event_count - 1) { pause(); return; }
  if (!busy) await historyAction({action:"step", count:Number($("step-size").value)}, false);
  if (playing) playTimer = setTimeout(loop, 450);
}

function renderHistory() {
  const h = historyState;
  $("history-metrics").innerHTML = metric("当前成交价", `${price(h.last_price)}<small>元</small>`, `股票 ${h.symbol}`, true)
    + metric("累计成交量", number(h.trade_volume), "股 · 当前回放时点")
    + metric("累计成交笔数", number(h.trade_count), "逐笔成交")
    + metric("簿内未成交订单", number(h.order_count), "含十档之外的订单");
  $("current-time").textContent = h.time;
  $("event-progress").textContent = `已回放 ${number(h.index + 1)} / ${number(h.event_count)} 个事件`;
  $("timeline").max = h.event_count - 1;
  $("timeline").value = h.index;
  $("phase").textContent = phases[h.phase] || h.phase;
  $("event-sequence").textContent = `序号 ${number(h.sequence)}`;
  renderBook("history-book", h, true);
  drawChart();
  $("history-events").innerHTML = h.events.length ? h.events.map(e => {
    const direction = e.side === "B" ? "买入" : e.side === "S" ? "卖出" : "";
    const label = {A:"新增委托",D:"撤销委托",T:"成交",S:"阶段变更"}[e.type];
    const icon = {A:"＋",D:"−",T:"⇄",S:"◷"}[e.type];
    const detail = e.type === "T" ? `买单 #${e.buy_id} · 卖单 #${e.sell_id}` : e.type === "S" ? ({I:"进入开盘集合竞价",O:"进入连续交易",J:"进入收盘集合竞价",C:"竞价交易结束",V:"进入盘后阶段"}[e.side] || "交易阶段更新") : `订单 #${e.order_id}`;
    return `<div class="event"><div class="event-icon ${e.side === "B" ? "buy" : e.side === "S" ? "sell" : ""}">${icon}</div><div class="event-main"><div class="event-line"><b>${label}${direction ? " · " + direction : ""}${e.type !== "S" ? ` ${number(e.quantity)}股` : ""}</b><time>${e.time}</time></div><div class="event-detail">${detail}${e.price ? ` · ${price(e.price)}元` : ""} <code> / ${e.sequence}</code></div></div></div>`;
  }).join("") : `<div class="empty">还没有发生事件<br>点击下一批开始回放</div>`;
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
async function showQueue() {
  await perform(async () => {
    const q = await api(`/api/orders?session=${encodeURIComponent(session)}&source=history&side=${queue.side}&price=${queue.price}&offset=${queue.offset}`);
    $("queue-title").textContent = `${queue.side === "B" ? "买方" : "卖方"}队列 · ${price(queue.price)}元 · ${number(q.total)}笔`;
    $("queue-content").innerHTML = `<div class="table-wrap"><table><thead><tr><th>排队顺序</th><th>订单号</th><th>剩余量 / 股</th></tr></thead><tbody>${q.orders.map((o,i) => `<tr><td>${q.offset+i+1}</td><td>#${o.order_id}</td><td>${number(o.quantity)}</td></tr>`).join("")}</tbody></table></div><div class="queue-pager"><span>${q.offset + 1}–${Math.min(q.offset + q.limit,q.total)} / ${number(q.total)}</span><div><button id="queue-prev" ${q.offset === 0 ? "disabled" : ""}>上一页</button><button id="queue-next" ${q.offset + q.limit >= q.total ? "disabled" : ""}>下一页</button></div></div>`;
    $("queue-prev").onclick = () => { if (queue.offset) {queue.offset -= 50; showQueue();} };
    $("queue-next").onclick = () => { if (queue.offset + 50 < q.total) {queue.offset += 50; showQueue();} };
    $("queue-panel").hidden = false;
  });
}

function seconds(t) {return Math.floor(t / 10000000) * 3600 + Math.floor(t / 100000) % 100 * 60 + Math.floor(t / 1000) % 100 + t % 1000 / 1000;}
function drawChart() {
  if (!series.length) {$("price-chart").innerHTML = `<div class="empty">该股票没有可显示的价格快照</div>`; return;}
  const W=1000,H=180,left=48,right=12,top=12,bottom=27;
  const first=seconds(series[0].time),last=seconds(series.at(-1).time);
  let low=Math.min(...series.map(p=>p.price)),high=Math.max(...series.map(p=>p.price));
  const padding=Math.max(2,(high-low)*.13); low-=padding; high+=padding;
  const x=t=>left+(seconds(t)-first)/Math.max(1,last-first)*(W-left-right);
  const y=p=>top+(high-p)/(high-low)*(H-top-bottom);
  const points=series.map(p=>`${x(p.time).toFixed(2)},${y(p.price).toFixed(2)}`).join(" ");
  const cursor=Math.min(W-right,Math.max(left,x(historyState.time_value)));
  let grid="";
  for(let i=0;i<3;i++){const value=low+(high-low)*i/2,yy=y(value);grid+=`<line x1="${left}" y1="${yy}" x2="${W-right}" y2="${yy}" stroke="#edf0f5" stroke-dasharray="3 5"/><text x="${left-10}" y="${yy+3}" fill="#a1abba" text-anchor="end" font-size="9">${(value/100).toFixed(2)}</text>`;}
  for(const [t,label] of [[93000000,"09:30"],[113000000,"11:30"],[130000000,"13:00"],[150000000,"15:00"]]){grid+=`<text x="${Math.min(W-right-12,Math.max(left,x(t)))}" y="${H-5}" fill="#a5afbd" text-anchor="middle" font-size="9">${label}</text>`;}
  $("price-chart").innerHTML=`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${historyState.symbol}当日成交价格，当前回放至${historyState.time}"><defs><linearGradient id="price-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#4169fa" stop-opacity=".13"/><stop offset="100%" stop-color="#4169fa" stop-opacity="0"/></linearGradient></defs>${grid}<polygon points="${left},${H-bottom} ${points} ${W-right},${H-bottom}" fill="url(#price-fill)"/><polyline points="${points}" fill="none" stroke="#5377ef" stroke-width="1.8" vector-effect="non-scaling-stroke"/><line x1="${cursor}" x2="${cursor}" y1="${top}" y2="${H-bottom}" stroke="#385be8" opacity=".8" stroke-dasharray="3 4"/>${historyState.last_price ? `<circle cx="${cursor}" cy="${y(historyState.last_price)}" r="3" fill="#375cf5" stroke="#fff" stroke-width="2"/>` : ""}</svg>`;
}

async function simAction(body) {
  await perform(async () => {simState=await api("/api/simulator",body);renderSimulator();});
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

document.querySelectorAll("[data-tab]").forEach(el=>el.addEventListener("click",()=>{
  pause();
  document.querySelectorAll(".view").forEach(v=>v.hidden=v.id!==el.dataset.tab);
  document.querySelectorAll("[data-tab]").forEach(n=>{n.classList.toggle("active",n===el);n.setAttribute("aria-selected",n===el ? "true" : "false");});
  $("breadcrumb").textContent={history:"历史行情回放",simulator:"模拟交易所",validation:"验证结果"}[el.dataset.tab];
}));
$("symbol").onchange=()=>historyAction({time:$("seek-time").value});
$("seek-button").onclick=()=>historyAction({time:$("seek-time").value});
$("seek-time").onkeydown=e=>{if(e.key==="Enter")historyAction({time:$("seek-time").value});};
$("next").onclick=()=>historyAction({action:"step",count:Number($("step-size").value)});
$("previous").onclick=()=>historyAction({action:"step",count:-Number($("step-size").value)});
$("play").onclick=()=>{if(playing){pause();return;}if(busy)return;playing=true;$("play").innerHTML="<span>Ⅱ</span> 暂停";loop();};
$("timeline").onchange=()=>historyAction({index:Number($("timeline").value)});
$("close-queue").onclick=()=>$("queue-panel").hidden=true;
document.querySelectorAll("[data-side]").forEach(el=>el.onclick=()=>{
  side=el.dataset.side;
  document.querySelectorAll("[data-side]").forEach(b=>b.classList.toggle("selected",b===el));
  $("submit-order").textContent=`提交${side==="B"?"买":"卖"}单 ↗`;
  $("submit-order").classList.toggle("sell-button",side==="S");
});
$("order-form").onsubmit=e=>{e.preventDefault();simAction({action:"order",side,price:$("order-price").value,quantity:Number($("order-quantity").value)});};
$("demo-button").onclick=()=>simAction({action:"demo"});
$("seed-button").onclick=()=>simAction({action:"reset",seed:true});
$("clear-button").onclick=()=>simAction({action:"reset",seed:false});
document.querySelectorAll("[data-phase]").forEach(el=>el.onclick=()=>simAction({action:"phase",phase:el.dataset.phase}));
$("uncross-button").onclick=()=>simAction({action:"uncross"});

async function init(){
  setBusy(true);
  try{
    const [meta,newSession]=await Promise.all([api("/api/meta"),api("/api/session",{})]);session=newSession.session;
    $("symbol").innerHTML=meta.symbols.map(s=>`<option value="${s}" ${s===600036?"selected":""}>${s}</option>`).join("");
    const a=meta.aggregate;
    $("validation-metrics").innerHTML=metric("股票覆盖","50<small>只</small>","上证50成分股",true)+metric("竞价事件",number(a.events),"新增、撤单、成交与状态")+metric("成交逐条一致",number(a.trades),"含开盘与收盘集合竞价")+metric("匹配快照",number(a.snapshot_exact),"按累计成交量与笔数寻找候选");
    simState=await api(`/api/simulator?session=${encodeURIComponent(session)}`);renderSimulator();
    historyState=await api("/api/history",{symbol:600036,time:"09:30:00"});series=historyState.series;renderHistory();
  }catch(error){toast(error.message);document.querySelector(".side-bottom").textContent="连接中断，请刷新页面重试";}
  finally{setBusy(false);}
}
init();
