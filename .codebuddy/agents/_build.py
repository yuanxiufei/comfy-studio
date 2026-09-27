# -*- coding: utf-8 -*-
"""把 `智能体搭建参考md/` 的 6 份智能体规格，**逐字移植**成 CodeBuddy 子智能体。

═══════════════════════════════════════════════════════════════════
为什么是"逐字移植"而不是"改写"
═══════════════════════════════════════════════════════════════════
那 6 份规格**本身就是按 System Prompt 设计的**（它们自己写着
「适用：Custom GPT / Agent / System Prompt / 工作流编排器」）。
所以正确做法是**加一层 CodeBuddy 的 frontmatter**，正文**原样搬运** ——
改写只会引入偏差，还要对付"哪份是最新"的问题。

⚠️ 这些智能体**不依赖** `AI漫剧智能体工作流/` 那套 Python 运行时 ——
它们把规则**内联**在 System Prompt 里，因此在 CodeBuddy 里**开箱可用**
（这正是"完全融合"的意思：不靠外部项目跑起来）。

| 源规格 | 生成 | 内联与否 |
|---|---|---|
| 给"没有工具的模型" | **本目录的 6 个智能体** | ⭐ 规则**全文内联**（模型读不到文件，必须内联） |
| 给"有工具的 agent" | `AI漫剧智能体工作流/` 那套 | 只给路径（避免同一知识两处维护） |

两种形态**各有用途**，不是谁替代谁：上面这套**独立可用**；
工作流那套**与本仓库的代码联动**（ID 分配 / 一致性 Gate / 漂移检测由代码判）。

═══════════════════════════════════════════════════════════════════
用法
═══════════════════════════════════════════════════════════════════
    python .codebuddy/agents/_build.py            # 重新生成 6 个智能体
    python .codebuddy/agents/_build.py --预览      # 只看清单，不写文件

校验：`python AI漫剧智能体工作流/07-智能体运行时/tests/test_agents.py`
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent             # `<仓库根>/.codebuddy/agents/`
REPO_ROOT = HERE.parent.parent                     # comfy-studio 仓库根（workspace 根）

# ⚠️ 同 `_install_user.py`：本仓唯一一处写死的「仓库内相对落点」（不是机器绝对路径）。
#    项目级 agent 必须住 workspace 根才生效，业务数据却在引擎侧扩展位下 —— 两者隔着
#    四级目录，无法用「向上找」连起来。改布局时三处一起改（这里 / 安装器 / 测试）。
MANJU_REL = "ComfyUI/custom_nodes/comfy_studio/manju"
ROOT = REPO_ROOT / MANJU_REL                       # 漫剧数据根
SRC_DIR = ROOT / "智能体搭建参考md"

# ⚠️ `description` 是**主 Agent 决定何时调用你**的唯一依据（官方文档），
#    故每条都必须写清「**当…时使用**」。不要写成 "一个有用的助手"。
# ⚠️ YAML 安全：值里**不能出现 ASCII 的 `冒号+空格`**（会被解析成映射），
#    中文「：」不受影响 —— 故本表统一用全角。
SOURCES: list[dict[str, str]] = [
    {
        "src": "AI剧本创作_完整迁移配置.md",
        "name": "manju-script-creator",
        "desc": "AI 漫剧剧本创作（2 分钟工业化短剧）- 当需要把原始故事 / 小说 / 一句话创意做成**可投产的 2 分钟 AI 漫剧剧本**时使用，覆盖工业化分集、10 大记忆点角色、每角色 10 项记忆资产、爆款标签、群像差异化、情绪线与黑化/成长/反转路线。例：「把这部小说改编成 AI 漫剧」「给我一份 40 集分集大纲」「这个主角怎么做出记忆点」。产出剧本 + 全人物总建模 + 分集结构 + 视觉统一方案。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "module": "01", "mode": "agentic",
    },
    # ⚠️ **本行的来由**（值得记，因为判据变过一次）：
    #    · 规格**旧版**（`…_FULL_PORTABLE_AGENT_SPEC_V2.md`）与工作流
    #      `02-服化道/00-主控智能体.md` 曾**100% 同一份**（滑窗互含率 100%/100%）
    #      → 当时判定"再生成一份内联副本 = 同一知识两处维护"，**故不移植**。
    #    · 2026-09-26 用户**重写并改名**为 `AI漫剧服化道智能体_完整迁移配置.md`
    #      （2093 → 2028 行；与工作流 02 的**主控与全部 23 份规则**互含率均为 **0.0%**）
    #      → **不再是副本，而是独立内容** ⇒ **判据失效、重新移植**。
    #    ⚠️ 教训：**判据依赖的事实会变**（源文件一更新，结论就得重算）。
    #       故把"为什么"写在这里，而不是只留一个结果。
    #    ⚠️ 仍设 `manual`：模块 02 的自动入口留给 `manju-02-asset` ——
    #       它是**唯一能"用代码强制"一致性**的（ID / 版本 / Gate / 参考图链 / 漂移），
    #       而本规格只能"描述"这些规则。**待用户确认哪份更权威后可再调**。
    {
        "src": "AI漫剧服化道智能体_完整迁移配置.md",
        "name": "manju-costume-prop-engine",
        "desc": "AI 漫剧服化道引擎（完整迁移配置）—— 当需要把小说 / 剧本视觉化成**世界观 + 角色 + 服装 + 道具 + 场景**资产时使用，覆盖固定模块结构、图像生成标准、标准三视图模板、人物一致性规则、色彩与材质系统、时代一致性、双语规则、四套 Prompt 模板（角色 / 服装 / 道具 / 场景）、Negative 规则、视觉 Bible 模板与最终质量检查清单。例：「女刺客，黑衣，赛博朋克」「给这个角色出三视图」「按我这段小说出全套服化道」。产出视觉 Bible + 资产设定 + 提示词 + 图像。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir, image_gen",
        "module": "02", "mode": "manual",
    },
    {
        "src": "AI漫剧资产库角色道具_完整迁移配置.md",
        "name": "manju-asset-library",
        "desc": "AI 漫剧资产库（角色 / 道具设定图）- 当需要生成**标准化、可复用、高一致性**的角色或道具设定图时使用，覆盖自动补全（年龄 / 面部 / 发型 / 服装材质 / 配色 / 装备 / 特殊身体特征）与固定版式（16:9，左侧人物特写 + 右侧正侧背三视图）。例：「红发女骑士角色设定图」「出一把赛博朋克武士刀的道具设定图」。产出补全后的设定 + 标准画布 + 提示词 + 图像。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir, image_gen",
        "module": "02", "mode": "manual",
    },
    {
        "src": "Suno歌词大师_完整迁移配置.md",
        "name": "manju-suno-lyric-master",
        "desc": "Suno 歌词大师 - 当需要为 AI 漫剧 / 短剧写**可直接投给 Suno 的完整歌曲**时使用，覆盖歌词结构、押韵、Hook 与副歌规则、Suno 标记、Style Prompt 组成与禁忌、曲风模板、情绪递进、中英混写与商业流行优化。例：「给这部剧写一首主题曲」「一句话主题扩写成完整歌曲」「帮这段歌词配 Style Prompt」。产出歌词 + 结构标记 + Style Prompt。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "module": "05", "mode": "agentic",
    },
    {
        "src": "分镜导演助手_完整迁移配置.md",
        "name": "manju-storyboard-director",
        "desc": "AI 漫剧分镜导演【先出分镜再出图】- 当需要把文字内容转成**可拍摄的视觉设计**时使用，按三阶段走：纯视觉 Storyboard → 专业镜头拆解 → AI 图像提示词，覆盖景别 / 机位 / 构图 / 运镜 / 光影 / 颜色 / 氛围，以及人物 Identity Lock 与场景 Environment Lock。例：「把这一场做成分镜」「这场戏需要几个镜头」「按分镜出图提示词」。产出视觉分镜 + 镜头拆解 + AI 提示词。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "module": "03", "mode": "agentic",
    },
    {
        "src": "调音大师班_完整迁移配置.md",
        "name": "manju-audio-tuning-master",
        "desc": "AI 漫剧调音大师班（声音设计）- 当需要做人物声线设计、环境声音、道具 Foley 或剧情声音表现时使用，覆盖年龄感 / 气息 / 颗粒感 / 情绪张力 / 语速 / 停顿 / 空间与收音 / 低频 / 特殊音色，以及标准化声音提示词结构。例：「给女主选个声线」「这段该配什么环境声」「这个人物的人声提示词怎么写」。产出声音设计方案 + 声音提示词。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "module": "05", "mode": "agentic",
    },
]

FRONT_KEYS = ("name", "description", "tools", "agentMode", "enabled", "enabledAutoRun")
# ⚠️ `description` 是**官方规定**的字段名（不是 `desc`）—— 写错会静默失效：
#    主 Agent 拿不到调用依据 → 这个智能体**永远不会被自动选中**。
FIELD_MAP = {"name": "name", "desc": "description", "tools": "tools"}


def yaml_value(v: str) -> str:
    """安全地写一个 YAML 标量（含冒号/引号时加引号）。"""
    if re.search(r":\s|^[#&*!|>%@`\"'\[{]", v) or v != v.strip():
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def render(item: dict) -> tuple[str, int, int]:
    """纯函数：按声明**算出**该智能体的完整文件内容 → `(内容, 正文字符数, 标题数)`。

    ⭐ 单独抽出来是为了让 **校验器复用同一份渲染逻辑** —— `tests/test_agents.py`
    会用它重算一遍并与磁盘上的文件比对，于是能同时抓出两类静默问题：
      · **改了规格却忘了重生成**（源变了、生成物没变）
      · **手改了生成物**（生成物变了、源没变）
    这两件事都不会让任何东西报错，但会让"规则"与"实际部署的 agent"不一致。
    """
    src = SRC_DIR / item["src"]
    if not src.is_file():
        raise FileNotFoundError(f"源规格不存在：{src}")
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")

    # 正文 = 源规格**逐字**（保留其 H1 与「用途/适用」元信息 —— 那是给智能体自己看的）
    body = text.rstrip() + "\n"

    # 出处注记放**正文最前**（两行）—— 便于追源，且让"这个 agent 是自动还是手动"**可见**。
    # ⚠️ 「服务模块」与「模式」写成**机器可读**的形式（`服务模块 **01** ｜ agentMode: manual），
    #    供 `tests/test_agents.py` 校验「**自动入口名册**」——
    #    不另立一张映射表（那会与"单一权威"冲突，且必然漂移）。
    manual = item["mode"] == "manual"
    tail = ("（**手动选** —— 同模块已有一个自动可调用的 agent，两者职责重叠，"
            "同时参与自动调用会让同一句话走两条路、**行为不确定**）"
            if manual else "（**自动可调用**）")
    prov = (f"> 生成自 `智能体搭建参考md/{src.name}`"
            f"（由 `.codebuddy/agents/_build.py` 逐字移植）。**改规则请改源规格后重新生成。**\n"
            f"> 服务模块 **{item['module']}** ｜ `agentMode: {item['mode']}`{tail}\n\n")

    vals = {FIELD_MAP[k]: item[k] for k in FIELD_MAP}
    vals.update({"agentMode": item["mode"], "enabled": "true",
                 "enabledAutoRun": "true"})
    fm = "\n".join(f"{k}: {yaml_value(str(vals[k]))}" for k in FRONT_KEYS)
    return (f"---\n{fm}\n---\n\n{prov}{body}",
            len(body), len([l for l in lines if l.startswith("#")]))


def build_one(item: dict, preview: bool) -> tuple[str, int, int]:
    out, n, secs = render(item)
    if not preview:
        (HERE / (item["name"] + ".md")).write_text(out, encoding="utf-8", newline="\n")
    return item["name"], n, secs


def main() -> int:
    ap = argparse.ArgumentParser(description="移植 智能体搭建参考md → CodeBuddy 子智能体")
    ap.add_argument("--预览", dest="preview", action="store_true",
                    help="只打印清单，不写文件")
    a = ap.parse_args()

    print(f"  源目录：{SRC_DIR}")
    print(f"  源规格 {len(SOURCES)} 份 → 生成 {len(SOURCES)} 个智能体")
    print()
    total = 0
    for it in SOURCES:
        name, n, secs = build_one(it, a.preview)
        total += n
        flag = "（预览）" if a.preview else ""
        tag = "手动" if it["mode"] == "manual" else "自动"
        print(f"  ✅ {name:30s} 模块{it['module']} {tag} 正文 {n:6d} 字符 "
              f"｜ {secs:3d} 个标题 {flag}")
    print()
    print(f"  合计正文 {total} 字符（≈ {total / 1024:.0f} KB）")
    auto = sum(1 for it in SOURCES if it["mode"] == "agentic")
    print(f"  自动可调用 {auto} 个 · 手动 {len(SOURCES) - auto} 个"
          f"（自动入口须与联动型一起对上「自动入口名册」，见 test_agents.py）")
    print(f"  校验：python AI漫剧智能体工作流/07-智能体运行时/tests/test_agents.py")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
