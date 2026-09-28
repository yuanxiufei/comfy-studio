"""静态核对：工作流里挂的权重在不在模型池里、是不是完整的。

为什么需要：JSON 能解析、连线也自洽，只说明**图**是对的；「权重指向哪里」是另一回事。
2026-09-28 这次同时踩到两种：
  * 06（r2v）的 turbo LoRA 整块没接（漏配，8 步跑基座必然掉质）
  * 06 的 DiT / 文本编码器与 04/05 不同档（同一批交付物里两张升级档、一张原始档）
这两种在 UI 里只表现为「加载器上显示的文件名不一样」，看不出「在不在」「是不是下了一半」。

核对口径：
  * 加载器节点的 widgets_values[0] 当文件名，到 paths.model_roots() 现算的模型根里找
    （ComfyUI 自己的 models/ 与 extra_model_paths.yaml 指的共享池都要查）。
  * H3 的权重在 h3_weights.FILES 里有上游尺寸事实，连尺寸一起核对：尺寸不符按
    「未下完或截断」报错，不当成在位（下载是直接写最终路径的，半成品很常见）。
  * 其余权重（Z-Image / Qwen-Image 那几张）没有上游事实，只做「存在」检查。
  * 表里没有的加载器类型不静默跳过：打印出来，让人看到缺口在哪。
  * 最后单独核一遍「同档」：h3_weights.WORKFLOWS 里的三张视频工作流必须落在同一档。
    2026-09-28 的漏配正是这样产生的 —— 04/05 升到 24GB 档，06 不在 switch 脚本的名单里，
    留在原始档；单看每张都「正常」，合起来是两张升级档配一张原始档，而图里看不出来。

退出码：0 = 全部通过；1 = 存在失败项。
"""
import json
import sys

import h3_weights
import paths

WORKFLOWS = paths.workflows()

# 加载器类型 -> 该类型在 ComfyUI 里会搜的子目录（按 ComfyUI 自己的 folder_paths 名字）
LOADER_DIRS = {
    "UNETLoader": ("diffusion_models", "unet", "checkpoints"),
    "CLIPLoader": ("text_encoders", "clip"),
    "VAELoader": ("vae",),
    "LoraLoaderModelOnly": ("loras",),
    "LoraLoader": ("loras",),
    "CheckpointLoaderSimple": ("checkpoints",),
}

# 这些节点看着像带权重、其实不带（widgets_values 首位不是文件名），显式排除，
# 免得它们落进「未覆盖」名单里淹没真正的缺口。
IGNORED = {"MiniMaxH3Director", "VAEDecode", "MarkdownNote", "Note"}


def find(roots, dirs, name):
    for root in roots:
        for directory in dirs:
            path = root / directory / name
            if path.is_file():
                return path
    return None


def check(path, roots):
    """返回 (问题列表, 未覆盖的加载器, {UNETLoader/CLIPLoader: 文件名})。"""
    problems = []
    uncovered = []
    picked = {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    for node in doc.get("nodes", []):
        node_type = node.get("type") or ""
        if node_type in IGNORED:
            continue
        dirs = LOADER_DIRS.get(node_type)
        values = node.get("widgets_values") or []
        if dirs is None or not values:
            # 名字里带 Loader 却没进表（或没 widget）的，打印出来，不静默跳过。
            if "Loader" in node_type:
                uncovered.append(node_type)
            continue
        name = values[0]
        if not isinstance(name, str) or not name.endswith(".safetensors"):
            uncovered.append("{}({!r})".format(node_type, name))
            continue
        if node_type in ("UNETLoader", "CLIPLoader"):
            picked[node_type] = name
        hit = find(roots, dirs, name)
        if hit is None:
            problems.append("{}: 找不到 {}".format(node_type, name))
            continue
        # 有上游尺寸事实的，连尺寸一起核对
        if name in h3_weights.FILES:
            want = h3_weights.FILES[name][1]
            got = hit.stat().st_size
            if got != want:
                problems.append("{}: {} 尺寸 {:,}/{:,}（未下完或截断）".format(
                    node_type, name, got, want))
            else:
                print("       [ ok ] {:<10} {}".format(node_type, name))
        else:
            print("       [ ok ] {:<10} {}  (无上游尺寸事实，仅查存在)".format(node_type, name))
    return problems, uncovered, picked


def mode_of(unet, clip):
    """把 (DiT, 文本编码器) 这一对映射回档位名；对不上任何一档就返回 None。"""
    for mode in h3_weights.MODES:
        if clip == h3_weights.CLIP[mode] and unet in h3_weights.UNET[mode].values():
            return mode
    return None


def check_modes(picked_by_file):
    """同一批视频工作流必须同档。

    本次就是这样漏的：04/05 升到 24GB 档，06 因为不在 switch 脚本的名单里而留在原始档 ——
    单看每张都「正常」，合起来是两张升级档、一张原始档，而图里看不出来。
    """
    problems = []
    modes = {}
    for name, info in picked_by_file.items():
        unet, clip = info.get("UNETLoader"), info.get("CLIPLoader")
        if not unet or not clip:
            problems.append("{}: 缺 UNETLoader 或 CLIPLoader，无法判定档位".format(name))
            continue
        mode = mode_of(unet, clip)
        if mode is None:
            problems.append(
                "{}: {} + {} 不属于任何已知档位（DiT 与文本编码器不成对？）".format(
                    name, unet, clip))
        else:
            modes[name] = mode
    if len(set(modes.values())) > 1:
        for name in sorted(modes):
            problems.append("{}: 档位 {}（与其它不一致）".format(name, modes[name]))
    elif modes:
        only = set(modes.values()).pop()
        print("=== H3 视频工作流档位一致性")
        for name in sorted(modes):
            print("       [ ok ] {:<34} {}".format(name, modes[name]))
        print("       一致：{}".format(only))
    return problems


def main():
    paths_list = sorted(WORKFLOWS.glob("*.json"))
    if not paths_list:
        raise SystemExit("没找到工作流：{}".format(WORKFLOWS))
    roots = paths.model_roots()
    print("模型根（按搜索顺序）:")
    for root in roots:
        print("    {}".format(root))

    bad = 0
    picked = {}
    for path in paths_list:
        print("=== {}".format(path.name))
        problems, uncovered, found = check(path, roots)
        for node_type in sorted(set(uncovered)):
            print("       [skip] {} 没在核对表里，未校验".format(node_type))
        if problems:
            bad += 1
            for problem in problems:
                print("       [FAIL] {}".format(problem))
        if path.name in h3_weights.WORKFLOWS:
            picked[path.name] = found

    # 只对档位表里认得的那三张做一致性核对
    problems = check_modes(picked)
    if problems:
        bad += 1
        for problem in problems:
            print("       [FAIL] {}".format(problem))

    print("--- {} 张工作流，{} 处有问题 ---".format(len(paths_list), bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
