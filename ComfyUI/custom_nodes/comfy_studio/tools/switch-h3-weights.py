"""在 H3 漫剧工作流之间切换权重档位（一次性脚本，放在 tools/ 下）。

用法（在 ComfyUI 目录下、用 .venv 的 python 跑）：
    python custom_nodes/comfy_studio/tools/switch-h3-weights.py                        # 切到升级档
    python custom_nodes/comfy_studio/tools/switch-h3-weights.py baseline               # 切回原档，用于 A/B 对照
    python custom_nodes/comfy_studio/tools/switch-h3-weights.py upgraded 06_视频_r2v_多镜连贯.json
                                                             # 只动指定的那几张

要改两处而不是一处：UNETLoader / CLIPLoader 的 widgets_values[0] 决定实际加载哪个
权重，而 properties.models[].name 是 ComfyUI 记录的节点引用模型（用于缺失提示与
模型列表），只改前者会留下不一致。

档位定义与权重尺寸、哈希的事实出处统一在 h3_weights.py，本脚本不再自带一份。
切换前按尺寸逐份核对：下载是直接写最终路径的（curl -C - -o <dest>），只看
is_file() 会把半个文件当成到位——显式报错，不静默兜底。而且是「先全部查完再动手」，
缺任何一个就不写任何文件，不留升一半的混档。

路径不写死：ComfyUI 根与工作流目录由 `paths` 现算，模型池读 extra_model_paths.yaml。
"""
import json
import shutil
import sys

import h3_weights
import paths

LOADERS = {"UNETLoader": "unet", "CLIPLoader": "clip"}


def patch(path, config, backup):
    print("=== {}".format(path.name))
    doc = json.loads(path.read_text(encoding="utf-8"))
    touched = 0
    for node in doc["nodes"]:
        slot = LOADERS.get(node.get("type"))
        if not slot:
            continue
        name = config[slot]
        before = node["widgets_values"][0]
        node["widgets_values"][0] = name
        for entry in node.get("properties", {}).get("models", []):
            entry["name"] = name
            entry["directory"] = h3_weights.FILES[name][0].split("/")[0]
        print("    {:<10} {} -> {}".format(node["type"], before, name))
        touched += 1
    if touched != 2:
        raise SystemExit("{}: 期望改到 2 个加载器，实际 {}".format(path.name, touched))

    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup / path.name)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    args = sys.argv[1:]
    mode = args[0] if args else "upgraded"
    if mode not in h3_weights.MODES:
        raise SystemExit(
            "未知档位 {!r}，可选：{}".format(mode, " / ".join(h3_weights.MODES))
        )

    pool = paths.pool()
    plan = h3_weights.targets(mode)
    wanted = args[1:] or sorted(plan)
    unknown = [n for n in wanted if n not in plan]
    if unknown:
        raise SystemExit("不认识的工作流文件 {}；可选的：{}".format(
            " / ".join(unknown), " / ".join(sorted(plan))))

    print("目标档位: {}".format(mode))
    print("模型池  : {}".format(pool))

    # 两个家族共用同一份文本编码器，去重后每份只报一次。
    weights = []
    for name in wanted:
        for weight in plan[name].values():
            if weight not in weights:
                weights.append(weight)
    # 先把要动的文件全部查一遍再动手：缺一个就不写任何文件，避免只升一半留下混档。
    h3_weights.require(pool, weights)

    backup = paths.backup()
    for name in wanted:
        patch(paths.workflows() / name, plan[name], backup)
    print("=== DONE ({}) ===".format(mode))


if __name__ == "__main__":
    main()
