from pathlib import Path
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "sse50_20260923"
DATE = "20260923"


def load_symbol(data, kind, symbol):
    return pq.read_table(Path(data) / f"{kind}_{DATE}.parquet", filters=[("Symbol", "=", symbol)])


def symbols(data=DEFAULT_DATA):
    return sorted(pc.unique(pq.read_table(Path(data) / f"ord_{DATE}.parquet", columns=["Symbol"])["Symbol"]).to_pylist())


def events(data, symbol):
    """订单只在一个竞价通道；盘后固定价格成交单独返回，不混入竞价簿。"""
    orders = load_symbol(data, "ord", symbol)
    channels = pc.unique(orders["Channel"]).to_pylist()
    if len(channels) != 1:
        raise ValueError(f"{symbol} 的竞价订单涉及多个通道：{channels}")
    channel = channels[0]
    trades = load_symbol(data, "exe", symbol)
    regular = trades.filter(pc.equal(trades["Channel"], channel))
    after = trades.filter(pc.not_equal(trades["Channel"], channel))
    all_rows = [(r["BizIndex"], "ord", r) for r in orders.to_pylist()]
    all_rows.extend((r["BizIndex"], "exe", r) for r in regular.to_pylist())
    all_rows.sort(key=lambda x: x[0])
    previous = -1
    previous_time = -1
    for seq, _, r in all_rows:
        if seq <= previous:
            raise ValueError(f"{symbol} 通道 {channel} 重复业务序号 {seq}")
        if r["Time"] < previous_time:
            raise ValueError(f"{symbol} 业务序号和事件时间不单调，需单独处理")
        previous, previous_time = seq, r["Time"]
    return all_rows, after.to_pylist(), channel


class ParquetSink:
    """分批落盘，避免全日逐事件状态占用内存。"""

    def __init__(self, path, schema, batch_size=20000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.schema = schema
        self.writer = pq.ParquetWriter(self.path, schema, compression="zstd")
        self.rows = []
        self.batch_size = batch_size
        self.count = 0

    def append(self, row):
        self.rows.append(row)
        self.count += 1
        if len(self.rows) >= self.batch_size:
            self.flush()

    def flush(self):
        if self.rows:
            self.writer.write_table(pa.Table.from_pylist(self.rows, schema=self.schema))
            self.rows.clear()

    def close(self):
        self.flush()
        self.writer.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
