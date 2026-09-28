"""只读校验 Music3 三件套的尺寸与 sha256（不写、不下载，可与下载脚本并存）。

尺寸/哈希取自 https://hf-mirror.com/api/models/Comfy-Org/MiniMax-Music-3?blobs=true
的 siblings[].size 与 siblings[].lfs.sha256。
注意：尺寸没对上就直接跳过哈希——文件可能正被下载脚本写入，此时算哈希只会得到错值。
"""
import hashlib
import os

import paths

POOL = paths.pool()

JOBS = [
    ("vae/minimax_music3_dav.safetensors", 216696128,
     "2a32155b769be01445fcc2a8663b910fc9e1751e18dc1c3ec528064512d9ef0c"),
    ("diffusion_models/minimax_music3_dit_fp16.safetensors", 4914197682,
     "45494a2b6b69af115902ff28eaf54118d19067aa54da01000f3e3efce7ba0e34"),
    ("text_encoders/minimax_music3_text_encoder_pruned_int8_convrot.safetensors", 9196611886,
     "010b7416d2336a08c711bc22ee65849c9623069ddb7d89bec011a75699e52014"),
]


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    for rel, want_size, want_hash in JOBS:
        path = os.path.join(POOL, rel.replace("/", os.sep))
        if not os.path.exists(path):
            print("{:<70} MISSING".format(rel))
            continue
        size = os.path.getsize(path)
        if size != want_size:
            print("{:<70} {:,}/{:,} (未完成，跳过哈希)".format(rel, size, want_size))
            continue
        got = sha256_of(path)
        verdict = "OK" if got == want_hash else "HASH MISMATCH {}".format(got[:16])
        print("{:<70} {} {:,} bytes".format(rel, verdict, size))


if __name__ == "__main__":
    main()
