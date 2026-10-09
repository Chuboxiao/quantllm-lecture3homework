#!/usr/bin/env python3
"""下载课程官方数据，验证压缩包与三个 Parquet 文件后写入数据目录。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parent.parent
URL = "https://github.com/aslan9/pku_quantllm/releases/download/data-sse50-20260923/sse50_20260923.zip"
SHA256 = "18c0e124a9c68eb2f77b965ca1f29c93bb30339d7db45245e1af3c0420c6c947"


def fingerprint(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="使用已经下载的官方压缩包")
    args = parser.parse_args()
    profile = json.loads((ROOT / "reports/results/data_profile.json").read_text())
    expected = {f"{kind}_20260923.parquet": item["sha256"] for kind, item in profile["files"].items()}
    destination = ROOT / "sse50_20260923"
    if all((destination / name).is_file() and fingerprint(destination / name) == digest for name, digest in expected.items()):
        print("三个数据文件已存在且 SHA-256 正确，无需重复下载。")
        return
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sse50-", dir=ROOT) as folder:
        temporary = Path(folder)
        archive = args.zip or temporary / "sse50_20260923.zip"
        if args.zip is None:
            print("正在从课程 Release 下载约216 MiB的数据……", flush=True)
            with urlopen(URL, timeout=120) as response, archive.open("wb") as target:
                shutil.copyfileobj(response, target)
        if fingerprint(archive) != SHA256:
            raise ValueError("压缩包 SHA-256 不符，请重新下载官方文件")
        with zipfile.ZipFile(archive) as package:
            for name, digest in expected.items():
                members = [m for m in package.infolist() if not m.is_dir() and Path(m.filename).name == name and not m.filename.startswith("__MACOSX/")]
                if len(members) != 1:
                    raise ValueError(f"压缩包内缺少或重复文件：{name}")
                target = temporary / name
                with package.open(members[0]) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                if fingerprint(target) != digest:
                    raise ValueError(f"数据文件 SHA-256 不符：{name}")
            # 三个文件全部验证后才替换，不改写用户提供的压缩包。
            for name in expected:
                (temporary / name).replace(destination / name)
    print(f"数据已验证并保存到 {destination}")


if __name__ == "__main__":
    main()
