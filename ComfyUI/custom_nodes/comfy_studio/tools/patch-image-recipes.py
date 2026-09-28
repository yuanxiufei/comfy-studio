"""把 5 张图像工作流的采样配方对齐 ComfyUI 自带蓝图（一次性脚本，放在 tools/ 下）。

事实出处（本仓 `ComfyUI/blueprints/` 里 ComfyUI 自带的官方蓝图，逐项实测读出）：

    Text to Image (Qwen-Image 2512).json  -> ModelSamplingAuraFlow shift=3.1  KSampler euler   / simple
    Text to Image (Z-Image-Base).json     -> ModelSamplingAuraFlow shift=3    KSampler res_multistep / simple
    Text to Image (Z-Image-Turbo).json    -> ModelSamplingAuraFlow shift=3    KSampler res_multistep / simple

本仓 5 张图像工作流（01/02/03_Qwen2512 + 01/02_ZImage）与上面三处不一致：
缺 ModelSamplingAuraFlow 整个节点、scheduler 用 `normal`、ZImage 用 `euler`。
补 AuraFlow 与换 scheduler 是**纯对齐官方配方**，不加步数、不加显存。

为什么 AuraFlow 不能省：它是 flow-matching 的 shift 参数（`comfy_extras/nodes_model_advanced.py:151`
的 `ModelSamplingAuraFlow(ModelSamplingSD3)`，直接把 `model_sampling` 换成带 shift 的实现），
官方蓝图三套全挂、且 Qwen 与 ZImage 的 shift 值不同（3.1 vs 3）—— 按架构分开给，不套用。

不动步数与 cfg：官方 Qwen2512 是 50 步 / cfg 4，本仓 30 步 / cfg 4。50 步在 22.5GB 显存上跑
38GB 的 bf16 DiT 要反复 offload，代价太高，30 步是成本折中，属有意保留的差异，不在这里偷改。

用法（在 ComfyUI 目录下、用 .venv 的 python 跑）::

    python custom_nodes/comfy_studio/tools/patch-image-recipes.py            # 应用
    python custom_nodes/comfy_studio/tools/patch-image-recipes.py --check    # 只报告差异，不写文件

路径不写死：ComfyUI 根 / 工作流目录 / 模型池由 `paths` 现算。
"""
import copy
import json
import math
import shutil
import sys

import paths

# 配方表：shift 来自对应架构的官方蓝图；sampler 为 None 表示「本仓已是官方值，不动」。
RECIPES = {
    "01_角色定妆板_Qwen2512.json": {"shift": 3.1, "sampler": None,             "scheduler": "simple"},
    "02_场景设定卡_Qwen2512.json": {"shift": 3.1, "sampler": None,             "scheduler": "simple"},
    "03_分镜首帧_Qwen2512.json":   {"shift": 3.1, "sampler": None,             "scheduler": "simple"},
    "01_角色定妆板_ZImage.json":   {"shift": 3.0, "sampler": "res_multistep",  "scheduler": "simple"},
    "02_场景设定卡_ZImage.json":   {"shift": 3.0, "sampler": "res_multistep",  "scheduler": "simple"},
}

AURA = "ModelSamplingAuraFlow"
SAMPLER_TYPES = ("KSampler", "KSamplerAdvanced")
# KSampler 的 widget 顺序（本仓实测：seed, steps, cfg, sampler_name, scheduler, denoise）
KS_WIDGETS = ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")
LATENT_TYPES = ("EmptySD3LatentImage", "EmptyLatentImage", "EmptyLatentImagePresets", "EmptyLatentImageSDXL")


def ratio_label(w, h):
    """把宽高化到最简比，形如 `4:3` —— 只用整数，避免浮点误差把 16:9 判成别的。"""
    g = math.gcd(int(w), int(h)) or 1
    return "{}:{}".format(int(w) // g, int(h) // g)


def _by_type(nodes, types):
    return [n for n in nodes if n.get("type") in types]


def _next_id(nodes, links, key, current):
    ids = [n.get("id") or 0 for n in nodes] + [l[0] for l in links if l]
    return max(ids + [current or 0]) + 1


def patch(path, recipe, apply_changes, backup):
    print("=== {}".format(path.name))
    doc = json.loads(path.read_text(encoding="utf-8"))
    nodes, links = doc["nodes"], doc["links"]
    changes = []

    # ① 找采样器与其 model 上游（靠连线，不靠 id）
    sampler = _by_type(nodes, SAMPLER_TYPES)
    if len(sampler) != 1:
        raise SystemExit("{}: 期望 1 个采样器，实际 {}".format(path.name, len(sampler)))
    ks = sampler[0]
    ks_inputs = ks.get("inputs") or []
    model_in = next((i for i in ks_inputs if i.get("name") == "model"), None)
    if model_in is None or model_in.get("link") is None:
        raise SystemExit("{}: 采样器 model 输入没连线".format(path.name))
    old_link = model_in["link"]
    link_row = next((l for l in links if l and l[0] == old_link), None)
    if link_row is None:
        raise SystemExit("{}: links 表里找不到 link {}".format(path.name, old_link))
    # links 行格式：[id, from_node, from_slot, to_node, to_slot, type]
    from_node, from_slot = link_row[1], link_row[2]
    upstream = next((n for n in nodes if n["id"] == from_node), None)
    if upstream is None:
        raise SystemExit("{}: link {} 的源节点 {} 不在 nodes 里".format(path.name, old_link, from_node))
    outs = upstream.get("outputs") or []
    if from_slot >= len(outs):
        raise SystemExit("{}: {} 没有输出槽 {}".format(path.name, upstream.get("type"), from_slot))

    # ② ModelSamplingAuraFlow：幂等 —— 已有就更新 shift，并**补齐缺失的 shift widget 输入项**
    #    （早一版脚本漏了这一项，shift 进不了 API；自愈分支保证重跑即可修好，不必手工回滚）
    existing = _by_type(nodes, (AURA,))
    if existing:
        af = existing[0]
        old = (af.get("widgets_values") or [None])[0]
        if old != recipe["shift"]:
            af["widgets_values"][0] = recipe["shift"]
            changes.append("{}: shift {} -> {}".format(AURA, old, recipe["shift"]))
        if not any(i.get("name") == "shift" for i in (af.get("inputs") or [])):
            af["inputs"] = list(af.get("inputs") or []) + [
                {"name": "shift", "type": "FLOAT", "widget": {"name": "shift"}, "link": None}]
            changes.append("{}: 补上 shift widget 输入项（否则 API 报文缺 shift，会退回默认 1.73）".format(AURA))
    else:
        new_id = _next_id(nodes, links, "node", doc.get("last_node_id"))
        new_link = _next_id(nodes, links, "link", doc.get("last_link_id"))
        ux, uy = (upstream.get("pos") or [0, 0])[:2]
        af = {
            "id": new_id,
            "type": AURA,
            "pos": [ux + 320, uy + 120],
            "size": [280, 58],
            "flags": {},
            "order": ks.get("order", 0),
            "mode": 0,
            # ⚠️ `shift` 必须作为**无 link 的 widget 输入**列在 inputs 里：
            #    `graph_to_api` 正是「按 inputs 里无 link 项的顺序取 widgets_values[i]」
            #    （src/image_provider.py:404-405）。只写 widgets_values 不写 inputs，
            #    shift 就进不了 API 报文，ComfyUI 会退回节点默认 1.73 —— 改动静默失效。
            #    结构照官方蓝图同节点的 inputs 抄（多一个 `widget` 键，不影响映射）。
            "inputs": [
                {"name": "model", "type": "MODEL", "link": old_link},
                {"name": "shift", "type": "FLOAT", "widget": {"name": "shift"}, "link": None},
            ],
            "outputs": [{"name": "MODEL", "type": "MODEL", "links": [new_link], "slot_index": 0}],
            "properties": {"Node name for S&R": AURA},
            "widgets_values": [recipe["shift"]],
        }
        nodes.append(af)
        # 原 link 改指新节点；KSampler.model 换到新 link
        link_row[3], link_row[4] = new_id, 0
        links.append([new_link, new_id, 0, ks["id"], 0, "MODEL"])
        model_in["link"] = new_link
        doc["last_node_id"] = max(doc.get("last_node_id") or 0, new_id)
        doc["last_link_id"] = max(doc.get("last_link_id") or 0, new_link)
        changes.append("插入 {} (shift={}) #{}: {} -> {}".format(
            AURA, recipe["shift"], new_id, upstream.get("type"), ks.get("type")))

    # ③ KSampler 的 sampler / scheduler
    wv = ks.get("widgets_values")
    if not isinstance(wv, list) or len(wv) < len(KS_WIDGETS):
        # 首项可能是 seed 的 "randomize" 包裹值，长度仍应够
        raise SystemExit("{}: KSampler widgets 异常 {}".format(path.name, wv))
    for want_key, want in (("sampler_name", recipe["sampler"]), ("scheduler", recipe["scheduler"])):
        if want is None:
            continue
        idx = KS_WIDGETS.index(want_key)
        if wv[idx] != want:
            changes.append("KSampler.{} {} -> {}".format(want_key, wv[idx], want))
            wv[idx] = want

    # ④ latent 标题：与实际尺寸比对，不符才改（01 的 2048x1536 被误标成 16:9）
    for ln in _by_type(nodes, LATENT_TYPES):
        lw = ln.get("widgets_values") or []
        if len(lw) < 2:
            continue
        real = ratio_label(lw[0], lw[1])
        title = ln.get("title") or ""
        if real in title:
            continue
        want = "空潜空间 {}x{} ({})".format(lw[0], lw[1], real)
        if title != want:
            changes.append("latent 标题 {!r} -> {!r}（实际 {}x{} = {}）".format(
                title, want, lw[0], lw[1], real))
            ln["title"] = want

    if not changes:
        print("    已是最新，无需改动")
        return 0
    for c in changes:
        print("    " + c)
    if not apply_changes:
        return len(changes)

    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup / path.name)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(changes)


def main():
    check_only = "--check" in sys.argv[1:]
    wf_dir = paths.workflows()
    print("工作流目录: {}".format(wf_dir))
    print("模式      : {}".format("只检查" if check_only else "应用"))
    print()
    total = 0
    for name, recipe in RECIPES.items():
        p = wf_dir / name
        if not p.is_file():
            raise SystemExit("缺工作流文件: {}".format(p))
        total += patch(p, recipe, not check_only, paths.backup())
    print()
    print("=== {} {} 项改动 ===".format("发现" if check_only else "应用", total))
    if check_only and total:
        print("（--check 没有写任何文件；去掉该参数即应用）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
