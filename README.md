# 第三讲实践课：熟悉高频数据，模拟交易所撮合

这个项目用课堂提供的上证50数据，完成逐笔委托、撤单、成交回放，维护完整订单簿；再补回未披露的主动订单，由撮合引擎生成成交，并与真实成交和行情快照核对。

## 在线模拟撮合演示

**[直接打开在线交易所](https://chuboxiao-lecture3-exchange.pkucoecourse.chatgpt.site)**，无需安装Python。支持买卖限价订单、撤单、连续竞价、集合竞价，以及验证结果和作业报告入口。每位访客的模拟盘口互相独立，刷新恢复示例。

在线版源码位于 `docs/`，撮合逻辑在浏览器内执行。其成交、剩余订单、十档盘口和竞价价格已通过101组、6,100步事件与Python引擎逐步对比。完整历史回放仍通过下面的本地Python服务运行。在线版也可以作为静态网站托管到GitHub Pages。

```bash
# 可选：需要Node.js，对比在线版与Python撮合结果
python tests/check_online_engine.py
```

## 提交内容

本仓库用于[第三节实践课 Issue 6](https://github.com/aslan9/pku_quantllm/issues/6)，包含完整Python代码、模拟交易所网页、作业报告和全量验证摘要。

- **[阅读作业报告](reports/作业报告.md)**：任务理解、字段语义、撮合实现、验证口径、实际结果与局限。
- **[查看全量验证摘要](reports/results/summary.json)**：50只股票的逐股票核对记录。
- **[查看验证报告HTML源文件](reports/results/report.html)**：下载后可在浏览器打开；启动服务后也可访问 `/report`。
- **[查看网页代码](web/)**：界面直接调用 `webapp.py` 中的Python服务。

GitHub本身展示代码、报告和截图；可交互网页需要按下面步骤启动本地Python服务。

## 快速开始

需要Python 3.12或以上。原始课堂数据不放入Git仓库，下载脚本从课程官方Release获取并校验SHA-256。老师已有课堂数据时，将三个Parquet文件放在仓库根目录的 `sse50_20260923/`，即可启动全部功能。

```bash
git clone https://github.com/Chuboxiao/quantllm-lecture3homework.git
cd quantllm-lecture3homework
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# 将老师已有的三个Parquet文件放入 sse50_20260923/ 后启动
python webapp.py --open
```

Windows PowerShell使用 `python -m venv .venv` 和 `.venv\Scripts\Activate.ps1` 建立并激活环境，其余Python命令相同。仓库地址以上传脚本最终输出为准。

如果其他使用者还没有数据，可用下面的可选命令下载：

```bash
python scripts/download_data.py
```

已经下载压缩包时可使用 `python scripts/download_data.py --zip /path/to/sse50_20260923.zip`。也可以手动将三个原始Parquet文件放入仓库根目录的 `sse50_20260923/`。

![历史回放网页预览](reports/assets/history-web.jpg)

## 网页操作

完成依赖安装后可以直接用网页操作。在macOS中双击 **`打开模拟交易所.command`**，会启动网页并打开浏览器。保持启动窗口打开，停止时按 Ctrl+C。若网页已经启动，直接访问 [本机模拟交易所](http://127.0.0.1:8890)。

网页有三个入口：

- **历史行情回放**：选择50只股票中的任意一只，跳转到指定时间、拖动事件进度、逐批前进或自动播放，查看十档盘口、最近事件与当日价格图。点击盘口价位可以查看同价位的订单排队顺序。
- **模拟交易所**：提交买卖限价单、撤销剩余订单，实时查看撮合引擎生成的成交。支持连续竞价和集合竞价，并可一键演示之前讲解的买入1000股例子。
- **验证结果**：查看全量核对统计及原有详细报告。

网页与Python引擎在同一台电脑上运行，所有交互都调用实际引擎。模拟盘口和历史盘口各自独立，浏览器会话之间也各自独立。历史价格图展示全日快照，当前回放状态以事件时间为准。刷新页面会重置该浏览器的模拟会话。

也可以通过终端启动：

```bash
.venv/bin/python webapp.py --open
```

`webapp.py`为网页服务；`web/`中的HTML、CSS和JavaScript为界面。没有新增第三方依赖。

- `output/report.html`：适合课堂展示的验证报告，可直接在浏览器打开。
- `output/summary.json`：全部股票的统计和验证结果。
- `output/data_profile.json`：数据字段、编码、时间范围及各文件 SHA-256。
- `output/demo.json`：之前讲解的“买入1000股、成交800股、撤销剩余200股”逐步状态。

报告必须与本次运行的真实核对结果一起阅读。`main.py check` 会重新读取生成的成交文件，与源成交逐行比对，并检查落盘快照状态。

## 运行方法

在本文件夹内打开终端。已经配置好的环境使用 `.venv/bin/python`。首次在其他机器使用时：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

使用 Python 3.12 或以上。所有命令默认读取当前项目下的 `sse50_20260923`，并写入 `output`。路径从脚本位置计算，不依赖启动位置；`examples` 等手动给出的相对路径仍按终端位置解析。

```bash
# 查看三张表的字段和数据范围
.venv/bin/python main.py inspect

# 逐步演示价格优先、时间优先、部分成交、撤单
.venv/bin/python main.py demo

# 用自己写的原始订单进行撮合，不读取真实成交
.venv/bin/python main.py match --input examples/orders.json

# 处理一只股票，或全量50只
.venv/bin/python main.py run --symbol 600036
.venv/bin/python main.py run --all

# 核对已生成的全量结果
.venv/bin/python main.py check

# 查询10点的完整订单簿，同时导出所有未成交订单
.venv/bin/python main.py book --symbol 600036 --time 10:00:00 --orders --save output/book_1000.json

# 按业务序号定位，同一毫秒内也能区分事件顺序
.venv/bin/python main.py book --symbol 600036 --sequence 378781

# 运行撮合、数据语义与随机守恒测试
.venv/bin/python -m unittest discover -s tests -v
```

单股票运行会更新该输出目录的汇总报告。若想保留全量报告，同时重新试一只股票，可指定另一个输出目录：

```bash
.venv/bin/python main.py --output output/single run --symbol 600036
```

## 三份数据怎么用

| 文件 | 用途 |
| --- | --- |
| `ord_20260923.parquet` | 新增剩余委托、撤单和产品阶段状态 |
| `exe_20260923.parquet` | 已发生的成交，包括双方原始订单号 |
| `snp_20260923.parquet` | 十档价量、累计成交量、成交笔数、总委托量等，用作核对 |

本包实际有50只股票，覆盖主板及科创板。不要把股票代码当成指数点位；每只股票有独立订单簿。

| 字段 | 本项目中的解释 |
| --- | --- |
| `Symbol` | 六位证券代码，源数据存为整数 |
| `Time` | `HHMMSSmmm`，例如 `93000030` 为09:30:00.030 |
| `Channel` + `BizIndex` | 通道与业务序号，同一竞价通道按序号回放 |
| `OrderOriNo` | 原始订单号，用于新增、撤单以及关联成交 |
| `OrderNumber` | 此包与逐笔消息序号对应，不作原始订单标识 |
| `OrderKind` | ASCII整数：65=`A`新增、68=`D`撤单、83=`S`状态 |
| `FunctionCode` | 新增/撤单中66=`B`买、83=`S`卖；状态中承载阶段标记 |
| `BidOrder` / `AskOrder` | 成交的买方/卖方原始订单号 |
| `BSFlag` | 成交中66主动买、83主动卖、0无主动方向，样本对应集合竞价 |
| `Price` | 源文件为元和float32；内部转换为整数分 |
| `Volume` | 股；不同事件中分别是剩余委托量、撤销量或成交量 |

本包仅筛选上证50，所以同一个通道的业务序号会跳号。其他股票的消息没有包含在包里，不能仅据此认定丢包。

## 系统如何工作

`exchange/book.py` 保存每一笔未成交订单。买价从高到低，卖价从低到高；同价格使用先入先出的队列。按订单号可以直接找到撤单对象。每个价位还有汇总数量，供行情展示。系统内部使用整数分，数量使用整数股。

连续竞价：新订单与最优对手报价比较。买价达到卖价、或卖价低至买价，即按已有对手报价成交。数量取两单剩余量的较小者；完全成交的订单移除，未完全成交的量继续撮合或排队。一个大订单可以生成多笔成交。

集合竞价：先将订单放入簿中，统一计算成交价。依次考虑最大成交量、高买低卖全成交、同价至少一方全成交、最小未成交量；仍存在多个候选时取候选价格范围的中间价，并按最小价位四舍五入。全部集合竞价成交使用同一价格，分配仍按价格与时间优先。程序处理开盘和收盘集合竞价。

引擎接受的是已经通过交易所申报合法性检查的限价订单。账户、资金、交收、涨跌停和动态有效申报范围不属于此次历史已受理订单的撮合环节；自备输入也是该层级的订单，不模拟报单前的账户与申报风控。

## 为什么不能直接拿 ord 来撮合

上交所竞价Level-2接口明确规定：连续竞价新增委托在首次撮合后发布，数量是首次撮合后的剩余量；一次全部成交的订单没有剩余新增委托消息。同一主动订单的成交在剩余新增消息之前发布。集合竞价订单集中发送，然后发送成交与状态消息。

本项目因此有两个流程：

1. **历史订单簿回放**（`exchange/replay.py`）：新增消息只加入其披露的剩余数量；撤单扣减对应订单；真实成交扣减已经在簿中的被动单，集合竞价成交扣减双方。主动单尚未入簿时不制造一笔虚假剩余单。缺失被动订单、超量扣减、重复业务序号等会报错。
2. **补回订单后模拟撮合**（`exchange/simulate.py`）：同一主动订单的初始量 = 主动成交量之和 + 首次剩余量。补回的订单放在首次主动成交之前；其后剩余新增消息不再重复入簿。没有披露剩余委托的完全成交订单，以最差成交价构造可等价执行的限价。随后引擎自行选择对手订单和成交数量；参考成交不再用于扣减。

撮合引擎本身可以直接处理自备的原始订单，`match` 命令无需 `exe`。真实数据流程使用历史成交补回缺失输入，因此所得验证属于**撮合与订单簿一致性验证**，不能称作从独立原始输入预测真实成交。完全成交订单的原始限价、市价类型、保护价无法从本包唯一恢复。

盘后固定价格成交在独立通道，且未提供对应委托。项目单独保存其成交，不错误扣减竞价订单簿，不声称重建了缺失的盘后委托队列。

## 订单簿的任意时点查询

`book --time` 从开盘事件开始重放至指定时间，返回该时间内全部已记录事件处理后的状态。同一时间戳可能有多笔事件；要定位到某一事件之后，使用 `--sequence`。

`--orders --save` 保存所有未成交订单，包括十档之外的订单。只指定 `--depth` 是显示深度，内部仍维护完整簿。事件日志记录了所有增量变化，所以不必为每个时点存一份巨大完整副本。

数据时间有有限分辨率，“任意时点”指所提供事件序列可以确定的状态，不能解释成恢复交易所内部未披露的微秒顺序。集合竞价订单是在阶段结束后集中发布的，事后按原始事件时间重建的竞价过程，不能用于声称盘中实时已经获得同样信息。

## 核对的口径

成交：分别核对连续、开盘集合、收盘集合成交。逐行比较买卖订单号、价格、数量和顺序；`check` 还从落盘文件重新比较时间。并比较每个价位成交量与每个订单成交量。

完整订单簿：回放簿与模拟簿的最终订单号、方向、价格、剩余数量及同价队列顺序全部核对。撮合时还检查数量不能为负、价位数量与订单数量一致。

快照：快照没有`BizIndex`，样本显示它的时间戳不能直接用来获得精确的事件边界。例如600036的09:30:00快照对应09:30:00.450附近的事件状态。核对时要求累计成交量、累计成交笔数相同，在前后3秒的事件候选中比较40个十档价量字段及买卖总委托量。完整候选结果、业务序号和时间偏移都会保存。

因此，报告中的快照比例表示**在规定候选范围内找到完全一致状态的比例**，不是时间戳直接对齐的准确率。匹配也不保证状态唯一。只核对连续竞价和竞价结束后的快照；集合竞价阶段快照的虚拟撮合盘口不同于未成交委托簿，未纳入这一指标。其他约1.6万条快照仍保留在原始文件中。

## 输出文件

每只股票在`output/股票代码/`下有：

| 文件 | 内容 |
| --- | --- |
| `events.parquet` | 每笔原始行情事件及其后的买一卖一、买卖总量、累计成交量；价格为整数分 |
| `simulation_inputs.parquet` | 送给模拟引擎的订单与撤单、竞价清算事件，标明来源和是否推断限价 |
| `simulated_trades.parquet` | 引擎实际生成的成交；买卖订单号、价格（分）、数量（股）、时间、阶段 |
| `snapshot_check.parquet` | 逐快照候选状态、差异、序号和时间偏移；价量数组按买1…买10、卖1…卖10排列 |
| `after_hours_trades.parquet` | 有盘后成交时单独保存源记录，价格仍按源数据为元 |
| `replay_summary.json` / `simulation_summary.json` / `validation.json` | 统计、分阶段对比及完整最终簿的核对 |

## 可核查的资料

- [老师的第三节实践课通知](https://github.com/aslan9/pku_quantllm/issues/6)
- [本次数据Release](https://github.com/aslan9/pku_quantllm/releases/tag/data-sse50-20260923)
- [上交所交易规则（2026年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)：3.5节价格时间优先、集合与连续竞价定价；本数据日期适用该版本。
- [上交所LDDS竞价Level-2接口说明书2.0.9](https://bsp.sseinfo.com/admin/static/public/2024-06-07/13f94744fb6244d5a21ee42bddcec9f6/%E4%B8%8A%E6%B5%B7%E8%AF%81%E5%88%B8%E4%BA%A4%E6%98%93%E6%89%80LDDS%E7%B3%BB%E7%BB%9F%E7%AB%9E%E4%BB%B7Level-2%E8%A1%8C%E6%83%85%E6%8E%A5%E5%8F%A3%E8%AF%B4%E6%98%8E%E4%B9%A6.pdf)：4.3和4.4节的剩余量与发布顺序；这份公开文档是数据处理口径的参考，不是课程提供的字段字典。具体字段映射还通过本包样本及全量核对确认。

## 仓库结构

```text
exchange/                  订单簿、撮合、历史回放与输入补回
web/                       HTML、CSS、JavaScript网页
webapp.py                  本地网页服务
main.py                    命令行处理与全量核对
examples/orders.json       自备原始订单示例
tests/                     20项自动测试
scripts/download_data.py   官方数据下载与哈希校验
scripts/upload_github.sh   在本人账号创建并上传公开仓库
reports/作业报告.md         正式作业报告
reports/results/           提交时的验证摘要与HTML报告
reports/assets/            实际网页截图
.github/workflows/         GitHub自动测试
sse50_20260923/             原始课堂数据，Git忽略
output/                    重新运行产生的日志和结果，Git忽略
```

网页优先展示本地 `output/` 中的新结果；未重新运行时使用仓库内 `reports/results/` 的提交基线。基线摘要可阅读，但全量 `check` 需要先运行 `run --all` 生成完整Parquet结果。

## 上传与提交

在本地作业目录执行 `bash scripts/upload_github.sh`。脚本在需要时安装GitHub CLI并引导网页登录，在登录账号下创建公开的 `quantllm-lecture3homework` 仓库，推送已提交的 `main` 分支并输出链接。它不会自动向课程Issue发布评论。上传前如修改文件，请先提交修改。

原始数据和运行结果保留在本地；仓库提供官方数据下载入口和可重新生成结果的代码。
