"""核对 Qwen-Image 2.1 全链三件套与 2512 / ZImage 的权重身份 —— 只读 safetensors 头，不加载张量。

为什么要读头而不是看文件名：
`ComfyUI/comfy/sd.py:1964` 的分支条件是「CLIPLoader 的 type=qwen_image **且** 权重被
`comfy/sd.py:1711` 检测成 QWEN3VL_8B」。也就是说 2.1 的文本编码器判定完全是靠权重内容，
文件名里带不带 "2.1" 根本不参与。所以这里复核的是**内容事实**：

  - text encoder 必须含 `model.visual.deepstack_merger_list.0.norm.weight`（DeepStack 是 Qwen3-VL 独有，
    见 comfy/sd.py:1711 的注释），且 `merger.linear_fc2.weight` 输出维 4096 = 8B（2560 则会被判成 4B）。
  - VAE 必须是 Wan2.2 layout / temporal kernel 1 / RGBA（comfy/sd.py:835 对 2.1 VAE 的描述）。
  - UNet 两档（bf16 / int8_convrot）应当同架构，只有量化差异。

用法:: python custom_nodes/comfy_studio/tools/qwen21-weights.py
"""
import json
import struct
import sys

import paths

# 候选清单：键是用途，值是「模型根下的相对路径」，逐个根去找，找不到就报缺。
TARGETS = {
    "unet(2.1/bf16)": "diffusion_models/qwen_image_2.1_bf16.safetensors",
    "unet(2.1/int8)": "diffusion_models/qwen_image_2.1_int8_convrot.safetensors",
    "unet(2512/bf16)": "diffusion_models/qwen_image_2512_bf16.safetensors",
    "te(2.1/qwen3vl_8b/int8)": "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
    "te(2512/qwen2.5vl_7b/fp8)": "text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
    "vae(2.1)": "vae/qwen_image_2.1_vae_bf16.safetensors",
    "vae(2512)": "vae/qwen_image_vae.safetensors",
}


def locate(rel):
    for root in paths.model_roots():
        p = root / rel
        if p.is_file():
            return p
    return None


def read_header(path):
    """返回 (metadata, {tensor_name: (dtype, shape)}) —— safetensors 前 8 字节是头长（小端 u64）。"""
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        raw = json.loads(f.read(n).decode("utf-8"))
    meta = raw.pop("__metadata__", {}) or {}
    return meta, raw


def classify(meta, tensors):
    keys = tensors.keys()
    dtype = {}
    for k, v in tensors.items():
        dtype[v["dtype"]] = dtype.get(v["dtype"], 0) + 1

    facts = []
    # Qwen3-VL 独有标记（comfy/sd.py:1711）
    if "model.visual.deepstack_merger_list.0.norm.weight" in keys:
        out = tensors["model.visual.merger.linear_fc2.weight"]["shape"][0]
        facts.append("Qwen3-VL 系, merger out={} -> {}".format(out, "8B" if out == 4096 else "4B" if out == 2560 else "?"))
    elif any(k.startswith("visual.") and "deepstack_merger_list" in k for k in keys):
        out = next(tensors[k]["shape"][0] for k in keys if k.endswith("visual.merger.linear_fc2.weight"))
        facts.append("Qwen3-VL 系(已改前缀), merger out={}".format(out))
    if any("deepstack" in k for k in keys):
        facts.append("含 DeepStack")
    # Qwen-Image 文本侧特征
    if any("qwen2.5" in k.lower() or "qwen25" in k.lower() for k in keys):
        facts.append("Qwen2.5 系")
    # VAE：Wan2.2 layout（3D 卷积、temporal kernel）
    conv3d = sum(1 for v in tensors.values() if len(v["shape"]) == 5)
    if conv3d:
        facts.append("含 {} 个 5D 卷积 -> 视频式 VAE(Wan2.2 layout)".format(conv3d))
    # 量化标记
    for mark in ("weight_scale", "scaled_fp8", "weight_scale_2"):
        if any(mark in k for k in keys):
            facts.append("量化标记:{}".format(mark))
    return dtype, facts


def main():
    print("模型根（按 ComfyUI 搜索顺序）:")
    for r in paths.model_roots():
        print("   ", r, "" if r.is_dir() else "(不存在)")
    print()
    missing = []
    for label, rel in TARGETS.items():
        p = locate(rel)
        if p is None:
            missing.append(rel)
            print("[-] {:26} 缺失: {}".format(label, rel))
            continue
        meta, tensors = read_header(p)
        dtype, facts = classify(meta, tensors)
        print("[+] {:26} {}".format(label, p.name))
        print("      大小 {:.2f}GB  张量 {}  dtype {}".format(p.stat().st_size / 1024**3, len(tensors), dtype))
        if meta:
            interesting = {k: v for k, v in meta.items() if k in ("modelspec.architecture", "modelspec.title", "modelspec.implementation", "format")}
            if interesting:
                print("      metadata: {}".format(interesting))
        print("      事实: {}".format("; ".join(facts) if facts else "（无标记命中）"))
        print()
    if missing:
        print("缺 {} 个文件，清单见上。".format(len(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
