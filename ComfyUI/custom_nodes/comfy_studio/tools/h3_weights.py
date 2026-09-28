"""MiniMax H3 权重：档位定义与文件事实（唯一事实源，供 fetch / switch 脚本共用）。

事实出处：上游仓库 Comfy-Org/MiniMax-H3 的 API 清单
    https://hf-mirror.com/api/models/Comfy-Org/MiniMax-H3?blobs=true
的 siblings[].size 与 siblings[].lfs.sha256（本机缓存见 .cache/h3-api.json），
不是估算值。跑 `python custom_nodes/comfy_studio/tools/h3_weights.py` 会拿缓存清单逐条机械核对本表。

为什么切换档位也要校验尺寸：下载是**直接写最终路径**的（`curl -C - -o <dest>`），
所以「文件存在」可能只是半个文件。只用 is_file() 判断，就会把工作流指向截断的
DiT/文本编码器，而错误要到真正加载时才暴露——显式校验，不静默兜底。

一个「档」是 DiT 与文本编码器**成对**的，不是单换其中一个：文本编码器是「读提示词」
那一环，压到 4bit 直接损害提示词理解（还原度）。
    baseline（= 官方蓝图档）  剪枝 int8 DiT 20.97GB + nvfp4_awq 文本编码器 15.69GB
    upgraded（24GB 档）      未剪枝 int8 DiT 34.04GB + int8_convrot 文本编码器 27.14GB

⚠️ **本机（RTX A5000 / SM 8.6）只该用 upgraded**：baseline 的文本编码器是 `nvfp4_awq` 档，
而 nvfp4 需要 Blackwell（`supports_nvfp4_compute` 在 SM 8.6 为假）—— 选它**不会报错**，
只是拿不到 TensorCore 加速，白背 15.69GB。留 baseline 只为 A/B 对照**剪枝 DiT vs 未剪枝 DiT**
这一个变量，不是为了省显存。

DiT 必须按**家族**分开：04/05 是 fl2va（首尾帧），06 是 ref2va（参考生视频），两者
权重不同、不可互换（连尺寸都不同：34,038,892,334 vs 34,038,894,550）。文本编码器与
VAE 则是两个家族共用的同一份。

VAE 不参与档位切换：官方蓝图 blueprints/Image to Video (MiniMax H3).json 用的就是
video_vae_fp16 + audio_vae_fp32。上游另有 video_vae_int8_convrot（2.81GB）属于低显存
可选项，换它影响的是解码侧画质，与「文本编码器档位」是两码事，故不在本表两档内。
"""
import hashlib
from pathlib import Path

import paths

# 文件名 -> (模型池内相对路径, 字节数, lfs sha256)
# sha256 为 None 表示上游清单里已没有这份文件，只能校验尺寸（见文末 NOTE）。
FILES = {
    # ---- 文本编码器：Qwen3-VL 32B，fl2va / ref2va 两家族共用 ----
    "qwen3vl_32b_minimax_h3_int8_convrot.safetensors": (
        "text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
        27141342152,
        "bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923",
    ),
    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors": (
        "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        15687142551,
        "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6",
    ),
    # ---- DiT：fl2va（04/05 首尾帧）----
    "minimax_h3_fl2va_int8_convrot.safetensors": (
        "diffusion_models/minimax_h3_fl2va_int8_convrot.safetensors",
        34038892334,
        "7ad4c73e6e378b822ffd1629f27f632d3787d95f5e468e3af958f98c58df96a5",
    ),
    "minimax_h3_fl2va_pruned_int8_convrot.safetensors": (
        "diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        20970379616,
        "e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a",
    ),
    # ---- DiT：ref2va（06 参考生视频）----
    "minimax_h3_ref2va_int8_convrot.safetensors": (
        "diffusion_models/minimax_h3_ref2va_int8_convrot.safetensors",
        34038894550,
        "9eef934046a0671bc8a5daf87100705e1478419c574cfde70c50fbe6885f76a9",
    ),
    "minimax_h3_ref2va_pruned_int8_convrot.safetensors": (
        "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors",
        20970379616,
        "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779",
    ),
    # ---- VAE 与 turbo LoRA：不随档位变，列在这里是为了让体检脚本能一并核对 ----
    "minimax_h3_video_vae_fp16.safetensors": (
        "vae/minimax_h3_video_vae_fp16.safetensors",
        5207808496,
        "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522",
    ),
    "minimax_h3_audio_vae_fp32.safetensors": (
        "vae/minimax_h3_audio_vae_fp32.safetensors",
        605254808,
        "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48",
    ),
    "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors": (
        "loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
        1956193000,
        "2339acdf19bfe123f46b971ea35d367a84adb85de43627e1eceafa5a5b2b111e",
    ),
    "minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors": (
        "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors",
        1956193000,
        "5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c",
    ),
    # NOTE: 06 正在用的这份 8step ref2v LoRA 在**上游现行清单里不存在**（只有 4step 版）。
    # 本机这份与 4step 版尺寸相同、safetensors 头部键/形状/__metadata__ 全同（同一次转换
    # 产物），但 sha256 不同，即张量值确实不同、不是改名副本；来源无从比对，换机不可复现。
    "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors": (
        "loras/minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors",
        1956193000,
        None,
    ),
}

# 档位 -> DiT 家族 -> 文件名
UNET = {
    "baseline": {
        "fl2va": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
        "ref2va": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    },
    "upgraded": {
        "fl2va": "minimax_h3_fl2va_int8_convrot.safetensors",
        "ref2va": "minimax_h3_ref2va_int8_convrot.safetensors",
    },
}
# 档位 -> 文本编码器文件名
CLIP = {
    "baseline": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "upgraded": "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
}

MODES = sorted(UNET)

# 工作流文件名 -> 它的 DiT 家族。三张视频工作流都要在表里，否则就会像 06 那样被漏掉，
# 留下「同一批交付物里两张升级档、一张原始档」这种看不出原因的不一致。
WORKFLOWS = {
    "04_视频_768p试片_fl2v.json": "fl2va",
    "05_视频_1080p正片_fl2v.json": "fl2va",
    "06_视频_r2v_多镜连贯.json": "ref2va",
}

# 升档要下载的三份，按优先级排：文本编码器对还原度影响最直接，放前面；
# 两个 DiT 家族都要拿，只补 fl2va 会让 06 落单。
FETCH_ORDER = [
    "qwen3vl_32b_minimax_h3_int8_convrot.safetensors",
    "minimax_h3_fl2va_int8_convrot.safetensors",
    "minimax_h3_ref2va_int8_convrot.safetensors",
]


def targets(mode):
    """返回 {工作流文件名: {"unet": 权重名, "clip": 权重名}}。"""
    return {
        name: {"unet": UNET[mode][family], "clip": CLIP[mode]}
        for name, family in WORKFLOWS.items()
    }


def path_of(pool, name):
    return Path(pool) / FILES[name][0]


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check(pool, name, full=False):
    """返回 (是否可用, 说明)。full=True 才做 sha256，几十 GB 的哈希不必每轮都算。"""
    _, want_size, want_hash = FILES[name]
    path = Path(pool) / FILES[name][0]
    if not path.is_file():
        return False, "缺文件"
    size = path.stat().st_size
    if size != want_size:
        return False, "尺寸 {:,}/{:,}（未下完或截断）".format(size, want_size)
    if full and want_hash:
        got = sha256_of(path)
        if got != want_hash:
            return False, "sha256 {}… != {}…".format(got[:16], want_hash[:16])
    return True, "{:,} 字节 ok".format(want_size)


def require(pool, names, full=False):
    """全部查完再动手：缺任何一个就抛 SystemExit，不留升一半的混档。"""
    problems = []
    for name in names:
        ok, why = check(pool, name, full=full)
        print("    {:<4} {:<58} {}".format("OK" if ok else "MISS", name, why))
        if not ok:
            problems.append("{}: {}".format(name, why))
    if problems:
        raise SystemExit(
            "权重不可用，先下载/修复完再继续：\n  " + "\n  ".join(problems)
        )


def _selftest():
    """拿缓存的上游清单机械核对本表，防手抄错一个数字。"""
    import json
    # 清单是上游 API 的**临时缓存**（.cache/ 被 .gitignore 忽略，批量重下时才生成），
    # 所以按 <ComfyUI>/.cache/ 找，而不是按本文件所在目录 —— 本文件已搬进 tools/ 入库。
    manifest = paths.comfy_root() / ".cache" / "h3-api.json"
    if not manifest.is_file():
        raise SystemExit("没有 {}，无法核对；先跑同目录的 fetch-h3-int8.py 拉清单".format(manifest))
    api = json.loads(manifest.read_text(encoding="utf-8-sig"))
    # 非 LFS 的小文件（README 等）没有 lfs 字段，取不到哈希就只比尺寸。
    upstream = {
        s["rfilename"]: (s["size"], s.get("lfs", {}).get("sha256"))
        for s in api["siblings"]
    }
    bad = 0
    for name, (rel, size, digest) in sorted(FILES.items()):
        if rel not in upstream:
            print("  [不在上游] {}".format(name))
            continue
        want_size, want_hash = upstream[rel]
        if size != want_size or (digest is not None and digest != want_hash):
            bad += 1
            print("  [不一致] {}".format(name))
            print("      本表 {}, {}   上游 {}, {}".format(size, digest, want_size, want_hash))
        else:
            print("  [ ok ] {:<58} {:,}".format(name, size))
    # 档位表只能引用本表里有的文件，否则切换时会 KeyError
    for mode in MODES:
        for weight in list(UNET[mode].values()) + [CLIP[mode]]:
            if weight not in FILES:
                bad += 1
                print("  [悬空] {} 档引用 {}，但它不在 FILES 里".format(mode, weight))
    for name in FETCH_ORDER:
        if name not in FILES:
            bad += 1
            print("  [悬空] FETCH_ORDER 引用 {}，但它不在 FILES 里".format(name))
    print("=== {}".format("FAIL {} 处不一致".format(bad) if bad else "OK"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
