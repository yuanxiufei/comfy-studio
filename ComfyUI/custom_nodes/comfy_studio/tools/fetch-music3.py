"""把 MiniMax Music3 的三件套权重拉进共享模型池（一次性脚本，放在 tools/ 下）。

为什么不用 huggingface_hub.snapshot_download：
    本次的失败模式是「TCP 连上后卡死、进程活着但字节数不涨」，hf_hub 没有对应的
    停滞检测；curl 的 --speed-limit/--speed-time 能直接掐断这种连接并让外层循环续传。
为什么还要 Python 包一层：
    续传循环 + 收尾的 sha256 校验用 batch 写又长又脆（证书工具输出还得正则抠），
    Python 里 hashlib 一把梭。两者组合兼顾「治卡死」与「防静默截断」。

尺寸与 sha256 取自 https://hf-mirror.com/api/models/Comfy-Org/MiniMax-Music-3?blobs=true
的 siblings[].size 与 siblings[].lfs.sha256，不是估算值。
"""
import hashlib
import os
import subprocess
import sys
import time

import paths

POOL = paths.pool()
BASE = "https://hf-mirror.com/Comfy-Org/MiniMax-Music-3/resolve/main"

# (仓库内相对路径, 字节数, lfs sha256)
JOBS = [
    (
        "vae/minimax_music3_dav.safetensors",
        216696128,
        "2a32155b769be01445fcc2a8663b910fc9e1751e18dc1c3ec528064512d9ef0c",
    ),
    (
        "diffusion_models/minimax_music3_dit_fp16.safetensors",
        4914197682,
        "45494a2b6b69af115902ff28eaf54118d19067aa54da01000f3e3efce7ba0e34",
    ),
    (
        "text_encoders/minimax_music3_text_encoder_pruned_int8_convrot.safetensors",
        9196611886,
        "010b7416d2336a08c711bc22ee65849c9623069ddb7d89bec011a75699e52014",
    ),
]

MAX_ATTEMPTS = 300


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path, want_size, want_hash):
    """返回 (是否完整, 说明)。只有尺寸先对上才做哈希，避免每轮重算 9GB 的 sha256。"""
    if not os.path.exists(path):
        return False, "missing"
    size = os.path.getsize(path)
    if size != want_size:
        return False, "size {:,}/{:,}".format(size, want_size)
    got = sha256_of(path)
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
