"""把 H3 漫剧工作流的画布与提示词改到官方档位（一次性脚本，放在 tools/ 下）。

全部依据均为实测源码/权威清单，不是记忆：

1. ComfyUI_MiniMaxH3_Director/lib/image_prep.py
     snap_dimension(v) = round(v / 32) * 32
     assert_minimax_canvas 要求宽高都是 32 的倍数（VAE ÷16 后再 2×2 patch）。
   1080 / 32 = 33.75 → 被就近取整成 1088，所以原「1920×1080」实际生成的是
   1920×1088，既不是短边 768 档也不是短边 1440 档，属离分布分辨率。

2. 官方 blueprint「Image to Video (MiniMax H3)」与节点默认画布都是 1344×768
   （短边 768，约 1M 像素），本次统一到这一档。

3. director/gen_timeline.py
     prompt = global_block.get("prompt") or global_prompt or ""
   即 timeline_data 里的 global.prompt 优先于控件 global_prompt，两处必须同时改，
   只改控件不生效。

4. 同文件在 editMode == "global" 时 seg_prompt = prompt，
   所以往 segments[].prompt 里填内容是不生效的（上一轮建议已作废）。

5. MiniMax-H3-资料汇总.md：官方要求「少写比喻句，多写看得见的画面」，
   并明确「不要写『不要字幕』这类负向描述」；fl2v 要写清中间运动过程。
   原文结尾的 "No text or watermarks." 正属被点名的负向写法，本次删除。
"""
import json
import shutil

import paths

WORKFLOWS = paths.workflows()
BACKUP = paths.backup()

OLD_PROMPT = (
    "Smooth cinematic motion between the first and last keyframes. Natural camera "
    "move, consistent subject identity, soft ambient soundscape. No text or watermarks."
)

# 三段式：参考素材说明 + 核心创意 + 画面过程说明。通用模板，具体镜头请按实拍内容替换。
NEW_PROMPT = (
    "参考素材：@图片1 为首帧，@图片2 为尾帧。以这两张图里的人物长相、发型、服饰、"
    "场景与光线为准，全程保持同一人物、同一服装、同一场景不变。\n"
    "核心创意：镜头基本固定，人物在原有场景里把首尾帧之间的动作连贯做完，"
    "画面风格、色调与光源方向从首帧平滑过渡到尾帧。\n"
    "画面过程：从首帧姿态自然起步，衣摆与发丝随动作轻微摆动，"
    "手臂与身体朝向逐帧推进到尾帧姿态，动作幅度均匀、自然衔接、不要切镜，"
    "画面内不新增人物或道具。"
)

# 文件名 -> (目标宽, 目标高)
JOBS = {
    "04_视频_768p试片_fl2v.json": (1344, 768),
    "05_视频_1080p正片_fl2v.json": (1344, 768),
}


def scan_dimensions(obj, path="timeline", found=None):
    """递归找出 timeline 里所有名为 width/height 的键，用于确认没有漏改的地方。"""
    if found is None:
        found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = "{}.{}".format(path, key)
            if key in ("width", "height", "longEdge", "refMaxSize") and isinstance(value, int):
                found.append((here, value))
            scan_dimensions(value, here, found)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            scan_dimensions(value, "{}.{}".format(path, index), found)
    return found


def patch(path, width, height):
    print("=== {}".format(path.name))
    doc = json.loads(path.read_text(encoding="utf-8"))
    nodes = [n for n in doc["nodes"] if n.get("type") == "MiniMaxH3Director"]
    if len(nodes) != 1:
        raise SystemExit("{}: 期望 1 个 MiniMaxH3Director，实际 {}".format(path.name, len(nodes)))
    node = nodes[0]
    widgets = node["widgets_values"]

    # 先断言现状，避免在结构变了之后盲写。
    if widgets[1] != OLD_PROMPT:
        raise SystemExit("{}: 控件提示词与预期不符: {!r}".format(path.name, widgets[1]))
    if widgets[3] != 1.0:
        raise SystemExit("{}: cfg 不是 1.0，实际 {!r}".format(path.name, widgets[3]))
    if widgets[5] != "randomize":
        raise SystemExit("{}: 种子控制不是 randomize，实际 {!r}".format(path.name, widgets[5]))

    timeline = json.loads(widgets[11])
    if timeline["global"]["prompt"] != OLD_PROMPT:
        raise SystemExit("{}: timeline 里的 global.prompt 与预期不符".format(path.name))

    print("    控件  : 宽 {} 高 {} 种子 {} cfg {}".format(widgets[7], widgets[8], widgets[5], widgets[3]))

    # 备份到 .cache（不放在工作流目录，免得 ComfyUI 把 .bak 也当工作流列出来）。
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, BACKUP / path.name)

    widgets[1] = NEW_PROMPT
    widgets[5] = "fixed"          # 固定种子，否则换参数无法归因
    widgets[7] = width
    widgets[8] = height
    widgets[9] = width            # ref_max_size 与长边一致（对齐 04 的做法）

    timeline["global"]["prompt"] = NEW_PROMPT
    for holder in (timeline, timeline["output"]):
        holder["width"] = width
        holder["height"] = height
    timeline["output"]["longEdge"] = width
    timeline["refMaxSize"] = width
    widgets[11] = json.dumps(timeline, ensure_ascii=False)

    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print("    改后  : 宽 {} 高 {} 种子 fixed".format(width, height))
    print("    timeline 中所有尺寸字段：")
    for where, value in scan_dimensions(timeline):
        print("        {:<34} {}".format(where, value))


def main():
    for name, (width, height) in JOBS.items():
        patch(WORKFLOWS / name, width, height)
    print("=== DONE ===")


if __name__ == "__main__":
    main()
