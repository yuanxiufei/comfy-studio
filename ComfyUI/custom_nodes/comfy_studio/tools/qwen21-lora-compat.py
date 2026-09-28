"""核对 LoRA 能否套到某代 DiT 上 —— 只读 safetensors 头的键名/形状，不加载权重。

为什么这是决定 01/02/03 用哪代的**前置事实**：LoRA 按键名逐张量注入，架构一换代
（2.1 的 DiT 与 2512 打包方式不同），键名对不上就**静默不生效**或报 missing keys ——
那样换基座等于把画风丢了，看着「跑通了」却不是最优组合。

两组候选、两种用途：
- **画风**：国漫短剧 3D CG 质感（本套漫剧的核心视觉资产）→ 决定基座该用哪一代。
- **加速**：Qwen-Image Lightning（4steps / 8steps）。它发布时只有原始 Qwen-Image v1.0，
  这里是**跨代核对**——对 2512 命中率高才敢用来压步数，否则只能退回多步。
  共享池没有 v1.0 基座，故只列本机实际存在的两代。

判定口径：LoRA 键名去容器前缀/去 LoRA 后缀后，与目标 DiT 键名做**同名率**统计。
同名率高 = 同一架构可直接套；低 = 不可混用。

用法:: python custom_nodes/comfy_studio/tools/qwen21-lora-compat.py
"""
import json
import struct
import sys
from collections import Counter

import paths

LORA_GROUPS = {
    "画风": [
        "Qwen-国漫短剧3D CG质感角色V1_Qwen-国漫短剧3D CG质感角色V1.safetensors",
        "Z-国漫短剧3D CG质感角色V1_Z-国漫短剧3D CG质感角色V1.safetensors",
    ],
    "加速（Lightning，为原始 Qwen-Image v1.0 发布）": [
        "Qwen-Image-Lightning-4steps-V1.0.safetensors",
        "Qwen-Image-Lightning-8steps-V1.1-bf16.safetensors",
    ],
}
DIT_TARGETS = [
    "qwen_image_2512_bf16.safetensors",
    "qwen_image_2.1_bf16.safetensors",
    "z_image_bf16.safetensors",
]


def locate(rel, kind=None):
    for root in paths.model_roots():
        p = root / rel
        if p.is_file():
            return p
    return None


def find_lora(name):
    for root in paths.model_roots():
        for sub in ("loras", "LoRA", "lora"):
            p = root / sub / name
            if p.is_file():
                return p
    return None


def find_dit(name):
    for root in paths.model_roots():
        for sub in ("diffusion_models", "unet"):
            p = root / sub / name
            if p.is_file():
                return p
    return None


def header(path):
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        raw = json.loads(f.read(n).decode("utf-8"))
    raw.pop("__metadata__", None)
    return raw


LORA_SUFFIXES = (
    ".lora_A.default.weight", ".lora_B.default.weight",
    ".lora_A.weight", ".lora_B.weight",
    ".lora_down.weight", ".lora_up.weight",
    ".alpha", ".lora_alpha",
)
# 只去这些「承载容器」前缀，**不动**键名内部的 `_` —— 实测 LoRA 用的是 kohya 风格
# `transformer_blocks.0.attn.add_k_proj.lora_A.default.weight`，`add_k_proj` 里的下划线是
# 模块名的一部分；上一版把 `_` 一律换成 `.` 造成了 100% 假阴性。
LORA_PREFIXES = ("diffusion_model.", "model.diffusion_model.", "lora_unet_", "lora_te_")


def norm(key):
    """LoRA / DiT 键名 → 可比的模块路径（去容器前缀、去 LoRA 后缀，保留键名内部下划线）。"""
    k = key
    for pre in LORA_PREFIXES:
        if k.startswith(pre):
            k = k[len(pre):]
            break
    for suf in LORA_SUFFIXES:
        if k.endswith(suf):
            k = k[: -len(suf)]
            break
    return k


def top_prefixes(tensors, n=6):
    c = Counter()
    for k in tensors:
        parts = k.split(".")
        c[".".join(parts[:2]) if len(parts) > 1 else parts[0]] += 1
    return c.most_common(n)


def main():
    dits = {}
    for name in DIT_TARGETS:
        p = find_dit(name)
        if p:
            dits[p.name] = header(p)
        else:
            print("[-] 缺 DiT:", name)
    if not dits:
        print("[-] 一个目标 DiT 都没找到，无法核对。")
        return 1

    missing = []
    for group, names in LORA_GROUPS.items():
        print("#" * 78)
        print("## {} 组".format(group))
        for name in names:
            lp = find_lora(name)
            if not lp:
                missing.append(name)
                print("[-] 缺 LoRA: {}".format(name))
                continue
            lt = header(lp)
            lora_keys = {norm(k) for k in lt}
            print("=" * 78)
            print("LoRA:", lp.name)
            print("  张量 {}  顶层前缀 {}".format(len(lt), top_prefixes(lt)))
            print()
            for dn, dt in dits.items():
                dit_keys = set(dt)                  # DiT 侧保留原始键（含 .weight/.bias）
                hit = [k for k in lora_keys if k + ".weight" in dit_keys]
                miss = sorted(k for k in lora_keys if k + ".weight" not in dit_keys)
                print("  vs {:<34} DiT张量 {:<5} 命中 {:<5} 覆盖率 {:.1%}".format(
                    dn, len(dt), len(hit), len(hit) / max(1, len(lora_keys))))
                if miss:
                    print("      未命中前几个: {}".format(miss[:4]))
                    # 拿 DiT 侧「同类键」作对照：能立刻看出是命名体系不同，还是这一支根本不存在。
                    stem = miss[0].split(".")[-2] if len(miss[0].split(".")) > 1 else ""
                    same = [k for k in sorted(dit_keys) if stem and stem in k]
                    print("      对照（DiT 侧含 {!r} 的键）: {}".format(
                        stem, same[:3] or "（DiT 里没有含该名的键）"))
            print()
    if missing:
        print("[-] 下列 LoRA 在本机模型池找不到，未核对：")
        for n in missing:
            print("    " + n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
