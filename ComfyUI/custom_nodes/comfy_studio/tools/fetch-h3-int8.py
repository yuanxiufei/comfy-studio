"""把 H3 的文本编码器与 DiT 升到官方「24GB 档」（一次性脚本，放在 tools/ 下）。

为什么升档：官方蓝图（blueprints/Image to Video (MiniMax H3).json）用的是剪枝 int8 DiT
（20.97GB）+ nvfp4 文本编码器（15.69GB），属于官方分级里的最低一档；而文本编码器正是
「读提示词」的那一环，压到 4bit 会直接损害提示词理解（也就是还原度）。本机 24GB 显存 +
93.6GB 内存对应官方 24GB 档：int8（未剪枝）DiT + int8 文本编码器。

要下哪几份、尺寸与 sha256 都取自 h3_weights.py（唯一事实源，出处写在那里），
本脚本不再自带一份，免得两处数字走偏。两个 DiT 家族都要拿：04/05 用 fl2va，
06（r2v）用 ref2va，只补 fl2va 会让 06 落单。

下载落地目录不写死 —— 由 `paths.pool()` 读 extra_model_paths.yaml 现算。

下载策略与 fetch-music3.py 相同：curl 的 --speed-limit/--speed-time 负责掐断
「连上但字节不涨」的僵死连接，外层 Python 循环负责续传与 sha256 收尾校验。
"""
import os
import subprocess
import sys
import time

import h3_weights
import paths

POOL = paths.pool()
BASE = "https://hf-mirror.com/Comfy-Org/MiniMax-H3/resolve/main"

# 文本编码器放前面，它对还原度影响最直接。顺序与目标清单见 h3_weights.FETCH_ORDER。
JOBS = [
    (h3_weights.FILES[name][0], h3_weights.FILES[name][1], h3_weights.FILES[name][2])
    for name in h3_weights.FETCH_ORDER
]

MAX_ATTEMPTS = 300


def verify(path, want_size, want_hash):
    """返回 (是否完整, 说明)。只有尺寸先对上才做哈希，避免每轮重算几十 GB 的 sha256。"""
    if not os.path.exists(path):
        return False, "missing"
    size = os.path.getsize(path)
    if size != want_size:
        return False, "size {:,}/{:,}".format(size, want_size)
    got = h3_weights.sha256_of(path)
    if got != want_hash:
        return False, "sha256 {}\u2026 != {}".format(got[:16], want_hash[:16])
    return True, "ok"


def fetch(rel, want_size, want_hash):
    name = os.path.basename(rel)
    dest = os.path.join(POOL, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print("=== {}".format(name), flush=True)

    ok, why = verify(dest, want_size, want_hash)
    if ok:
        print("    already complete ({:,} bytes, sha256 ok)".format(want_size), flush=True)
        return
    print("    currently: {}".format(why), flush=True)

    # curl -C - 要求目标文件已存在，否则直接报错；先落一个空文件占位。
    if not os.path.exists(dest):
        open(dest, "wb").close()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        have = os.path.getsize(dest)
        print(
            "    attempt {}: have {:,}/{:,} bytes".format(attempt, have, want_size),
            flush=True,
        )
        subprocess.run(
            [
                "curl", "-L", "--fail",
                "--retry", "3", "--retry-delay", "5", "--retry-all-errors",
                "--connect-timeout", "20",
                # 低于 30KB/s 持续 25 秒即判定停滞，掐断连接让外层续传。
                "--speed-limit", "30000", "--speed-time", "25",
                "-C", "-", "-o", dest, "{}/{}".format(BASE, rel),
            ],
            check=False,
        )
        ok, why = verify(dest, want_size, want_hash)
        if ok:
            print("    verified: {:,} bytes, sha256 ok".format(want_size), flush=True)
            return
        if why.startswith("sha256"):
            # 尺寸对上了但哈希不对：已有前缀本身是坏的，续传只会一直复现同样的错误，
            # 必须从零重来（显式处理，不静默继续）。
            print("    hash mismatch on complete size -> restarting from 0", flush=True)
            os.remove(dest)
            open(dest, "wb").close()
        else:
            print("    not done: {}".format(why), flush=True)
        time.sleep(3)

    print("!!! gave up on {} after {} attempts".format(name, MAX_ATTEMPTS), flush=True)
    sys.exit(1)


def main():
    print("pool: {}".format(POOL), flush=True)
    for rel, want_size, want_hash in JOBS:
        fetch(rel, want_size, want_hash)
    print("=== ALL FILES VERIFIED ===", flush=True)


if __name__ == "__main__":
    main()
