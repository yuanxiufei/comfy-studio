"""给 5 张图像工作流各加一个 MarkdownNote，把「配方为什么长这样 + 为什么不用 2.1」留在文件里。

动机：本仓的工作流是**自带说明**的（04/06/07 都有 MarkdownNote 记权重档位与出处）。
图像这 5 张原先没有 Note，而它们恰好是最容易被误改的地方 —— 本机已经躺着一份
更新、更省显存的 Qwen-Image 2.1 int8，后来人看见多半会想换过去。所以把实测结论
写进文件本身，换配方就是换文件、说明跟着走。

Note 里的每条结论都有可复跑的事实出处：
  - 键名覆盖率  -> ComfyUI/custom_nodes/comfy_studio/tools/qwen21-lora-compat.py
  - 三件套身份  -> ComfyUI/custom_nodes/comfy_studio/tools/qwen21-weights.py
  - shift 值    -> ComfyUI/blueprints/ 里 ComfyUI 自带蓝图（逐节点读出）
  - 显存/算力   -> torch.cuda.get_device_properties（A5000 / SM8.6 / 22.5GB）

幂等：按 title 找已有 Note，更新其 content，不重复插入。
用法（在 ComfyUI 目录下跑）::  python custom_nodes/comfy_studio/tools/add-recipe-notes.py
"""
import json
import shutil
import sys

import paths

WF_DIR = None  # 由 main 填充

COMMON_TAIL = """## 本机算力约束（别踩）
RTX A5000 是 **SM 8.6 / 22.5GB**。`supports_nvfp4_compute` 在 SM 8.6 上为假（nvfp4 要 Blackwell），
所以凡 `*nvfp4*` / `*awq*` 权重档一律不要选 —— 选了不会报错，只会悄悄退化成慢路径。
int8（`int8_convrot`）是本机可用的最优量化档。
"""

QWEN_NOTE = """# 配方与选型依据（Qwen-Image 2512）

## 采样配方照官方蓝图抄，别改
- `ModelSamplingAuraFlow` **shift=3.1** —— 出处：本仓 `blueprints/Text to Image (Qwen-Image 2512).json`。
  它把 `model_sampling` 换成带 shift 的 flow-matching 实现（`comfy_extras/nodes_model_advanced.py`）。
- KSampler **euler / simple**，与官方一致。此前是 `normal`，已对齐。
- 步数 30 / cfg 4.0 是**有意保留**的差异：官方默认 50 步，而 2512 bf16 有 38GB，
  本机 22.5GB 显存必然反复 offload，50 步代价过高。

## 为什么用 2512，而不是更新的 Qwen-Image 2.1
本机已有 2.1 的 int8 档（6.76GB，比 2512 省得多），但**不能换**，两条实测理由：

1. **画风 LoRA 会丢 82% 的模块**。键名覆盖率实测（`ComfyUI/custom_nodes/comfy_studio/tools/qwen21-lora-compat.py`）：
   - `Qwen-国漫短剧3D CG质感角色V1` → 2512 命中 **720/720 = 100%**
   - 同一 LoRA → 2.1 只有 **128/720 = 17.8%**，缺的正是 `attn.add_q/k/v_proj`、`to_add_out`
     这一整套 joint-attention 分支（2.1 的 DiT 只有 265 个张量，是打包存储，细粒度注入不兼容）。
2. **版式出不了**。2.1 的正/负词与 latent 都由 `TextEncodeQwenImage21` 一个节点产出；
   不挂参考图时 latent 只能是 `resolution × resolution` 正方形，出不了本张的 4:3 定妆板。

→ 2.1 的正确定位是**参考图驱动的编辑**（它的 `images` 输入槽就是干这个的），不是替代本张。
""" + COMMON_TAIL

SHORT_QWEN = """# 配方与选型依据（Qwen-Image 2512）

采样配方与选型理由**同 `01_角色定妆板_Qwen2512.json` 的 Note**，要点复述：
- `ModelSamplingAuraFlow` shift=**3.1**、KSampler **euler / simple**（照官方 2512 蓝图）。
- 步数 30 / cfg 4.0 有意保留（官方 50 步，本机 22.5GB 显存跑 38GB bf16 太贵）。
- **不要**换成 Qwen-Image 2.1：画风 LoRA 对该架构只命中 17.8%，且无参考图时 latent 只能出正方形。
""" + COMMON_TAIL

ZIMAGE_NOTE = """# 配方与选型依据（Z-Image）

## 采样配方照官方蓝图抄
- `ModelSamplingAuraFlow` **shift=3** —— 出处：`blueprints/Text to Image (Z-Image-Base).json`
  与 `Text to Image (Z-Image-Turbo).json`（ZImage 的两张官方蓝图都是 shift=3）。
- sampler **res_multistep** / scheduler **simple**，与官方一致。此前是 `euler` / `normal`，已对齐。

## 什么时候选这张、什么时候选 Qwen 2512
- **ZImage 省显存**：`z_image_bf16` 11.46GB，2512 bf16 有 38GB。显存紧 / 批量试片走这张。
- **Qwen 2512 画风更足**：`Z-国漫短剧3D CG质感角色V1` 只有 0.148GB，
  而 Qwen 那份 `Qwen-国漫短剧3D CG质感角色V1` 是 0.879GB —— 画风 LoRA 的容量差 6 倍。
  **要角色质感统一到漫剧风格时，用 2512 那版。**
""" + COMMON_TAIL

NOTES = {
    "01_角色定妆板_Qwen2512.json": ("配方与选型依据（2512）", QWEN_NOTE),
    "02_场景设定卡_Qwen2512.json": ("配方与选型依据（2512）", SHORT_QWEN),
    "03_分镜首帧_Qwen2512.json":   ("配方与选型依据（2512）", SHORT_QWEN),
    "01_角色定妆板_ZImage.json":   ("配方与选型依据（ZImage）", ZIMAGE_NOTE),
    "02_场景设定卡_ZImage.json":   ("配方与选型依据（ZImage）", ZIMAGE_NOTE),
}


def main():
    wf = paths.workflows()
    print("工作流目录: {}".format(wf))
    total = 0
    for name, (title, text) in NOTES.items():
        p = wf / name
        print("=== {}".format(name))
        if not p.is_file():
            raise SystemExit("缺工作流文件: {}".format(p))
        doc = json.loads(p.read_text(encoding="utf-8"))
        nodes = doc["nodes"]
        hit = next((n for n in nodes if n.get("type") in ("MarkdownNote", "Note")
                    and (n.get("title") or "").startswith("配方与选型依据")), None)
        if hit:
            if hit.get("widgets_values") == [text]:
                print("    已是最新")
                continue
            hit["widgets_values"] = [text]
            print("    更新已有 Note #{}（{} 字）".format(hit["id"], len(text)))
        else:
            new_id = max([n.get("id") or 0 for n in nodes] + [doc.get("last_node_id") or 0]) + 1
            xs = [n["pos"][0] for n in nodes if n.get("pos")]
            ys = [n["pos"][1] for n in nodes if n.get("pos")]
            note = {
                "id": new_id,
                "type": "MarkdownNote",
                "pos": [min(xs) - 580, min(ys)],
                "size": [540, 520],
                "flags": {},
                "order": 0,
                "mode": 0,
                "inputs": [],
                "outputs": [],
                "title": title,
                "properties": {},
                "color": "#432",
                "bgcolor": "#653",
                "widgets_values": [text],
            }
            nodes.append(note)
            doc["last_node_id"] = max(doc.get("last_node_id") or 0, new_id)
            print("    插入 MarkdownNote #{}（{} 字）".format(new_id, len(text)))
        backup = paths.backup()
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, backup / p.name)
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        total += 1
    print()
    print("=== {} 张已更新 ===".format(total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
