"""给 06（r2v 多镜连贯）补上 ref2v turbo LoRA，并把种子控制对齐到 04/05。

修的是**漏配**，不是加新玩法：

1. 三张视频工作流导演台的步数控件（widgets_values[13]）实测都是 8。
   04/05 的 8 步是靠名字里带 8step 的 turbo LoRA 才成立的（该 LoRA 的作用就是
   把采样压到 8 步），而 06 用了同样的 8 步却完全没有 LoRA 节点 ——
   拿 8 步直接跑 ref2va 基座必然掉质。这是同一批交付物里的不一致。

2. 种子控制：04/05 已由 patch-h3-workflows.py 从 randomize 改成 fixed，
   理由是「固定种子，否则换参数无法归因」；06 没被那次改动覆盖（JOBS 只列了
   04/05），所以还停在 randomize，三张里唯一一张无法归因的。
   本条与实际值 widgets_values[4] = 42 配合才有意义（randomize 会让 42 失效）。

选哪个 ref2v turbo LoRA（池里有两个，二选一）：
    minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors   <- 选它
    minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors
依据：① 步数控件是 8，与 8step 版对齐（4step 版对不上）；
      ② 画布 1344×768 属 768p 档，与文件名里的 768p 对齐；
      ③ v1.0 晚于 v0.1（08-31），且与 04/05 在用的 fl2v_turbo_8step_v1.0 同代同款。

接线照 04 的既有形状（UNET -> LoRA -> BSA -> Director）：
    改：link 1   1 -> 12     变成  1 -> 13
    加：link 13  13 -> 12
    不动：link 12  12 -> 5   （BSA -> Director）
节点号/序号沿用 04 的约定（order = id - 1，且 LoRA 的 id/order 小于 BSA）。

只改这一个文件；改动前备份到 .cache/h3-workflow-backup/（带后缀命名，
避免覆盖 switch-h3-weights.py 依赖的那两份 9/1 快照）。
"""
import json
import shutil

import paths

WORKFLOWS = paths.workflows()
BACKUP = paths.backup()
POOL = paths.pool()

TARGET = "06_视频_r2v_多镜连贯.json"
LORA_NAME = "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"

NEW_NODE_ID = 13
NEW_LINK_ID = 13
UNET_ID = 1
BSA_ID = 12

OLD_NOTE_HEAD = "1. UNET 请使用 **ref2va** 权重（与 fl2va 不同）"
NEW_NOTE_ITEM = (
    "2. 必须挂 **ref2v turbo LoRA**（图中 `LoraLoaderModelOnly` 节点）\n"
    "   `minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors`\n"
    "   导演台步数 8 是 turbo 档；不挂 LoRA 直接跑 8 步必然掉质。\n"
)


def make_lora_node(doc):
    """按 04 的 LoraLoaderModelOnly 节点形状构造，位置放在 06 左侧加载列的空白处。"""
    return {
        "id": NEW_NODE_ID,
        "type": "LoraLoaderModelOnly",
        "pos": [-720, 560],
        "size": [360, 82],
        "flags": {},
        "order": NEW_NODE_ID - 1,
        "mode": 0,
        "inputs": [
            {"name": "model", "type": "MODEL", "link": 1},
            {"name": "lora_name", "type": "COMBO"},
            {"name": "strength_model", "type": "FLOAT"},
        ],
        "outputs": [{"name": "MODEL", "type": "MODEL", "links": [NEW_LINK_ID]}],
        "properties": {"Node name for S&R": "LoraLoaderModelOnly"},
        "widgets_values": [LORA_NAME, 1.0],
        "title": "H3 Turbo LoRA (8-step)",
    }


def main():
    path = WORKFLOWS / TARGET
    lora_path = POOL / "loras" / LORA_NAME
    if not lora_path.is_file():
        raise SystemExit("缺少 LoRA 权重，先下载：{}".format(lora_path))
    print("LoRA 在位: {:,} 字节  {}".format(lora_path.stat().st_size, LORA_NAME))

    doc = json.loads(path.read_text(encoding="utf-8"))

    # 先断言现状，避免结构变了之后盲写。
    if any(n.get("type") == "LoraLoaderModelOnly" for n in doc["nodes"]):
        raise SystemExit("{}: 已经存在 LoRA 节点，本脚本只用于补漏配".format(TARGET))
    if doc["last_node_id"] != BSA_ID or doc["last_link_id"] != BSA_ID:
        raise SystemExit(
            "{}: 预期 last_node_id/last_link_id 均为 {}，实际 {}/{}".format(
                TARGET, BSA_ID, doc["last_node_id"], doc["last_link_id"]
            )
        )
    unet = [n for n in doc["nodes"] if n["id"] == UNET_ID][0]
    bsa = [n for n in doc["nodes"] if n["id"] == BSA_ID][0]
    if unet["type"] != "UNETLoader" or bsa["type"] != "BlockSparseAttention":
        raise SystemExit("{}: 节点 1/{} 的类型不是预期值".format(TARGET, BSA_ID))
    link1 = [l for l in doc["links"] if l[0] == 1]
    if len(link1) != 1 or link1[0][:5] != [1, UNET_ID, 0, BSA_ID, 0]:
        raise SystemExit("{}: link 1 不是 UNET -> BSA，实际 {}".format(TARGET, link1))
    if bsa["inputs"][0]["link"] != 1:
        raise SystemExit("{}: BSA 的 model 输入不是 link 1".format(TARGET))

    director = [n for n in doc["nodes"] if n.get("type") == "MiniMaxH3Director"][0]
    steps = director["widgets_values"][13]
    if steps != 8:
        raise SystemExit("{}: 导演台步数不是 8，实际 {!r}，不要按 8step LoRA 处理".format(TARGET, steps))
    if director["widgets_values"][5] != "randomize":
        raise SystemExit("{}: 种子控制不是 randomize，实际 {!r}".format(TARGET, director["widgets_values"][5]))

    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, BACKUP / (path.stem + ".pre-r2v-turbo.json"))

    # 1) 插入 LoRA 节点
    doc["nodes"].append(make_lora_node(doc))
    # 2) 把 link 1 的终点从 BSA 改到 LoRA，BSA 的输入改接到新 link 13
    link1[0][3] = NEW_NODE_ID
    bsa["inputs"][0]["link"] = NEW_LINK_ID
    doc["links"].append([NEW_LINK_ID, NEW_NODE_ID, 0, BSA_ID, 0, "MODEL"])
    # 3) 计数器
    doc["last_node_id"] = NEW_NODE_ID
    doc["last_link_id"] = NEW_LINK_ID
    # 4) 步数 8 是 turbo 档，种子固定才可归因
    director["widgets_values"][5] = "fixed"

    # 5) 说明卡补一条（否则图里挂着 LoRA、卡上不写，下一个人会当成可选项删掉）
    note = [n for n in doc["nodes"] if n.get("type") == "MarkdownNote"][0]
    text = note["widgets_values"][0]
    if OLD_NOTE_HEAD not in text:
        raise SystemExit("{}: 说明卡里找不到预期标题行".format(TARGET))
    for old, new in (("2. 在导演台参考图槽位", "3. 在导演台参考图槽位"),
                     ("3. 提示词中使用官方标签", "4. 提示词中使用官方标签"),
                     ("4. Queue Prompt", "5. Queue Prompt")):
        if old not in text:
            raise SystemExit("{}: 说明卡里找不到 {!r}".format(TARGET, old))
        text = text.replace(old, new, 1)
    anchor = "   `minimax_h3_ref2va_pruned_int8_convrot.safetensors`\n"
    if anchor not in text:
        raise SystemExit("{}: 说明卡里找不到 UNET 权重那行".format(TARGET))
    note["widgets_values"][0] = text.replace(anchor, anchor + NEW_NOTE_ITEM, 1)

    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== {}".format(TARGET))
    print("    + 节点 {} {}".format(NEW_NODE_ID, "LoraLoaderModelOnly"))
    print("    + link {} {} -> {}".format(NEW_LINK_ID, NEW_NODE_ID, BSA_ID))
    print("    link 1  {} -> {}".format(UNET_ID, NEW_NODE_ID))
    print("    导演台步数 {} ｜ 种子控制 randomize -> fixed".format(steps))
    print("    说明卡已补 turbo LoRA 条目")
    print("=== DONE ===")


if __name__ == "__main__":
    main()
