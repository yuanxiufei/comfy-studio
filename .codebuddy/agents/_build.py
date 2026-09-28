# -*- coding: utf-8 -*-
"""把宿主包 `agent/presets/` 的智能体规格，**逐字移植**成 CodeBuddy 子智能体。

═══════════════════════════════════════════════════════════════════
口径：这批智能体是**通用内容生产**的 —— 与题材无关
═══════════════════════════════════════════════════════════════════
剧本 / 服化道 / 资产库 / 分镜 / 视频生成 / 音频 —— 这些职责**任何题材都用得上**。
题材（世界设定、人物谱系、ID 规范、门禁判据）住在**具体项目的规则**里，
不住在 agent 里：换个项目 = 换一份规则，agent 本身不改一个字。

⚠️ 故 **name / description / 角色段里不许出现具体题材**（"漫剧""赛博朋克"…）：
写窄了，主 Agent 就会在别的题材上**不选它** —— 而这件事**不报错**。

⚠️ 这批 agent 一律**自包含**：规格正文把规则**全文内联**在 System Prompt 里，
正文里**不出现任何仓库内路径**。同一份在本仓库、在别的项目、在别的平台都能直接跑。

═══════════════════════════════════════════════════════════════════
为什么是"逐字移植"而不是"改写"
═══════════════════════════════════════════════════════════════════
那几份规格**本身就是按 System Prompt 设计的**（它们自己写着
「适用：Custom GPT / Agent / System Prompt / 工作流编排器」）。
所以正确做法是**加一层 CodeBuddy 的 frontmatter**，正文**原样搬运** ——
改写只会引入偏差，还要对付"哪份是最新"的问题。

⚠️ 这批智能体**不依赖任何运行时**：规则**全文内联**在 System Prompt 里，
正文里**不出现任何仓库内路径**，因此在 CodeBuddy 里**开箱可用**，
搬到别的项目、别的平台也是同一份。

═══════════════════════════════════════════════════════════════════
「谁是自动入口」只看一个字段：`agentMode`
═══════════════════════════════════════════════════════════════════
| agent | agentMode | 对应职责 |
|---|---|---|
| `studio-script-creator` | `agentic` | 剧本文本 |
| `studio-costume-prop-engine` | `agentic` | 服化道（世界视觉设定，主控） |
| `studio-storyboard-director` | `agentic` | 分镜导演 |
| `studio-video` | `agentic` | 视频生成（分镜 → 提示词与生成脚本） |
| `studio-suno-lyric-master` | `agentic` | 词曲 |
| `studio-audio-tuning-master` | `agentic` | 声音设计 |
| `studio-asset-library` | `manual` | 服化道的**专项工具**（单件设定图） |

⚠️ 服化道方向有**两个** agent，只留**一个**自动入口：两者都能响应"出一套视觉设定"，
同时参与自动调用会让同一句话走两条路、**行为不确定**。自动位留给
`costume-prop-engine`（主控：世界观 + 角色 + 服装 + 道具 + 场景），
`asset-library` 作为专项工具**手动**叫（单件角色 / 道具的标准设定图）。
判据只有 `agentMode` 一处 —— 不另立"后台名册"（那份名册会与文件本身漂移）。

═══════════════════════════════════════════════════════════════════
源在**宿主包**里，本脚本只做一条派生
═══════════════════════════════════════════════════════════════════
| 角色 | 落点 | 谁读它 |
|---|---|---|
| **源规格**（唯一权威，写作地） | `Comfy-Desktop/lib/comfy_studio/agent/presets/*.md` | 宿主 `agent/catalog.py` 的 `PRESET_AGENTS`（面板下拉）**直接读**，零转换 |
| 派生（本脚本生成） | `.codebuddy/agents/studio-<职责>.md` | CodeBuddy 主 Agent（加一层 frontmatter，**正文逐字**，见 :func:`render`） |

⚠️ 为什么源就住在**宿主包**里，而不是像从前那样另存一份在引擎侧
（`manju/智能体搭建参考md/`）：

* 宿主包要**随桌面壳分发** —— cwd 是壳自带的 lib，猜不到用户的 ComfyUI 装在哪，
  所以这些正文**必须**住在包内，删不掉；
* 既然它必须在，再在别处留一份"权威源"就是**同一知识两处维护**，而"改了源、
  忘了同步"既不报错也不复现（症状只是面板下拉里那个智能体按旧人设说话）；
* 引擎侧那棵树整体删除后，那个"别处"本身也没了 —— 源就此收敛到这一处。

⚠️ 本脚本**不再同步任何"预置快照"**：源就是预置本身，派生只有 `.codebuddy/agents/`
一条。（从前它管两个落点，是因为源另在引擎侧；现在写回预置等于自己抄自己。）

═══════════════════════════════════════════════════════════════════
用法
═══════════════════════════════════════════════════════════════════
    python .codebuddy/agents/_build.py           # 生成全部智能体
    python .codebuddy/agents/_build.py --预览     # 只看清单，一个字都不写

校验：`cd ComfyUI/custom_nodes && python -m unittest comfy_studio.tests.test_agent_presets -t .`
（宿主侧另有一套：`cd Comfy-Desktop/lib` 后跑
`python -m unittest comfy_studio.tests.test_agents_tools`）
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent             # `<仓库根>/.codebuddy/agents/`
REPO_ROOT = HERE.parent.parent                     # comfy-studio 仓库根（workspace 根）

# ⚠️ 源规格住在**宿主包**里：宿主面板下拉直接读它当角色段（`agent/catalog.py` 的
#    `PRESET_AGENTS`），本脚本另生成一份 CodeBuddy 子智能体 —— **一处源、两个消费者**。
#    这条相对落点是「仓库内落点」，不是机器绝对路径（禁的是 `D:\…` 那种换台机器就
#    静默失效的写法）：它由 `__file__` 推出仓库根后再拼，布局不变它就永远对得上。
HOST_AGENT_REL = "Comfy-Desktop/lib/comfy_studio/agent"
SRC_DIR = REPO_ROOT / HOST_AGENT_REL / "presets"     # 源规格（唯一权威源）
CATALOG = REPO_ROOT / HOST_AGENT_REL / "catalog.py"  # 宿主侧清单 PRESET_AGENTS 就在这份里

#: 不许出现在 name / description / 角色段 / 下拉说明里的**具体题材**。
#:
#: 口径见本文件顶部：这批智能体是通用内容生产的，题材住在**具体项目的规则**里。
#: 写窄了的后果是**静默的** —— 主 Agent 在别的题材上不选它，没有任何报错。
#: 词表就是"实际泄漏过的那几个"：2026-09-28 之前 4 份规格把 agent 焊在
#: 「2分钟AI漫剧短剧」上（剧本 27 处、服化道 9 处、资产库 7 处、下拉说明 1 处），
#: 而注释里的这条口径**一个守卫都没有**。形态/能力的中性说法照旧用，
#: 具体数值保留为「默认档」并声明项目规则优先。
FORBIDDEN_TOPIC = ("漫剧", "短剧")

#: 判据用正则而不是 `in`：中文没有词边界，素材来源枚举里的 `动漫剧情` 里就嵌着一个
#: 「漫剧」—— 首跑时它被报成"剧本规格的角色段里有「漫剧」"，是个假警报。
#: （`FORBIDDEN_TOPIC` 与 `TOPIC_RE` 必须一致；测试里有逐词往返检查。）
TOPIC_RE = re.compile(r"(?<!动)漫剧|短剧")


def topic_hits(text: str) -> list[str]:
    """文本里命中的题材词（去重，按出现顺序）。"""
    return list(dict.fromkeys(m.group(0) for m in TOPIC_RE.finditer(text)))


# ⚠️ `description` 是**主 Agent 决定何时调用你**的唯一依据（官方文档），
#    故每条都必须写清「**当…时使用**」。不要写成 "一个有用的助手"。
# ⚠️ YAML 安全：值里**不能出现 ASCII 的 `冒号+空格`**（会被解析成映射），
#    中文「：」不受影响 —— 故本表统一用全角。
SOURCES: list[dict[str, str]] = [
    {
        "src": "AI剧本创作_完整迁移配置.md",
        "name": "studio-script-creator",
        "desc": "剧本创作（连载剧集 / 长篇改编）- 当需要把原始故事 / 小说 / 一句话创意做成**可投产的剧本**时使用，覆盖工业化分集、10 大记忆点角色、每角色 10 项记忆资产、爆款标签、群像差异化、情绪线与黑化/成长/反转路线。例：「把这部小说改编成连载剧集」「给我一份分集大纲」「这个主角怎么做出记忆点」。产出剧本 + 全人物总建模 + 分集结构 + 视觉统一方案。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "mode": "agentic",
    },
    # ⚠️ 模块 02 有**两个** agent（本份 = 模块主控 + `studio-asset-library` = 专项工具）。
    #    两者都能响应"出一套视觉设定" ⇒ 只留**一个**自动入口，本份占它
    #    （它管全套：世界观 + 角色 + 服装 + 道具 + 场景）。
    #    `studio-asset-library` 设 `manual`：手动叫去出单件设定图。
    {
        "src": "AI服化道智能体_完整迁移配置.md",
        "name": "studio-costume-prop-engine",
        "desc": "服化道引擎（世界视觉设定）- 当需要把故事 / 小说视觉化成**世界观 + 角色 + 服装 + 道具 + 场景**资产时使用，覆盖固定模块结构、图像生成标准、标准三视图模板、人物一致性规则、色彩与材质系统、时代一致性、双语规则、四套 Prompt 模板（角色 / 服装 / 道具 / 场景）、Negative 规则、视觉 Bible 模板与最终质量检查清单。例：「一位黑衣女刺客」「给这个角色出三视图」「按我这段小说出全套服化道」。产出视觉 Bible + 资产设定 + 提示词 + 图像。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir, image_gen",
        "mode": "agentic",
    },
    {
        "src": "AI资产库角色道具_完整迁移配置.md",
        "name": "studio-asset-library",
        "desc": "资产库（角色 / 道具设定图）- 当需要生成**标准化、可复用、高一致性**的角色或道具设定图时使用，覆盖自动补全（年龄 / 面部 / 发型 / 服装材质 / 配色 / 装备 / 特殊身体特征）与固定版式（16:9，左侧人物特写 + 右侧正侧背三视图）。例：「红发女骑士角色设定图」「出一把武士刀的道具设定图」。产出补全后的设定 + 标准画布 + 提示词 + 图像。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir, image_gen",
        "mode": "manual",
    },
    {
        "src": "Suno歌词大师_完整迁移配置.md",
        "name": "studio-suno-lyric-master",
        "desc": "Suno 歌词大师 - 当需要为任意内容形态（剧集 / 动画 / 广告 / 主题曲…）写**可直接投给 Suno 的完整歌曲**时使用，覆盖歌词结构、押韵、Hook 与副歌规则、Suno 标记、Style Prompt 组成与禁忌、曲风模板、情绪递进、中英混写与商业流行优化。例：「给这部剧写一首主题曲」「一句话主题扩写成完整歌曲」「帮这段歌词配 Style Prompt」。产出歌词 + 结构标记 + Style Prompt。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "mode": "agentic",
    },
    {
        "src": "分镜导演助手_完整迁移配置.md",
        "name": "studio-storyboard-director",
        "desc": "分镜导演【先出分镜再出图】- 当需要把文字内容转成**可拍摄的视觉设计**时使用，按三阶段走：纯视觉 Storyboard → 专业镜头拆解 → AI 图像提示词，覆盖景别 / 机位 / 构图 / 运镜 / 光影 / 颜色 / 氛围，以及人物 Identity Lock 与场景 Environment Lock。例：「把这一场做成分镜」「这场戏需要几个镜头」「按分镜出图提示词」。产出视觉分镜 + 镜头拆解 + AI 提示词。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "mode": "agentic",
    },
    {
        "src": "AI视频生成_完整迁移配置.md",
        "name": "studio-video",
        "desc": "视频生成（分镜 → 可投产提示词）- 当需要把**分镜表**转成可直接投产的视频提示词与生成脚本时使用，覆盖平台适配（Seedance / 可灵 / Vidu / 即梦 / Sora / Runway，各家的提示词形态与时长上限不同）、视频提示词公式（五段式与镜头四维参数）、时长与运动强度控制、多镜连贯性（尾帧链 + 场景双锚定 + 跨场景处理 + 8 项一致性校验）、情绪过渡（一镜之内的三段弧线）与动作戏视觉手法（12 条手法 + 起势-过程-结果三件套）、生成失败的重试顺序与失败修复表。例：「把这几个镜头写成视频提示词」「用可灵生成第 3 镜」「多镜之间怎么接」。产出逐镜视频提示词 + 转场衔接 + 尾帧链登记 + 生成后校验。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "mode": "agentic",
    },
    {
        "src": "调音大师班_完整迁移配置.md",
        "name": "studio-audio-tuning-master",
        "desc": "调音大师班（声音设计）- 当需要做人物声线设计、环境声音、道具 Foley 或剧情声音表现时使用，覆盖年龄感 / 气息 / 颗粒感 / 情绪张力 / 语速 / 停顿 / 空间与收音 / 低频 / 特殊音色，以及标准化声音提示词结构。例：「给女主选个声线」「这段该配什么环境声」「这个人物的人声提示词怎么写」。产出声音设计方案 + 声音提示词。",
        "tools": "read_file, write_to_file, replace_in_file, search_file, search_content, list_dir",
        "mode": "agentic",
    },
]

#: frontmatter 的字段与顺序。依据是 CodeBuddy 官方 Subagents 文档
#: （https://www.codebuddy.ai/docs/zh/ide/Features/Subagents）的字段表 + 两个示例：
#: `name` / `description` / `tools` / `agentMode` / `enabled` / `enabledAutoRun`。
#: `agentMode` 取 `agentic`（主 Agent 自动判断调用时机）或 `manual`（用户手动选）——
#: 它才是"自动入口"的**唯一**判据。
#: ⚠️ `enabledAutoRun` 是字段表里的 **Auto Run**：「调用工具时**是否需要用户的同意**」。
#:    官方 agentic 与 manual 两个示例都是 `true`。关掉它不会让 agent "更保守"，只会让它在
#:    每一步工具调用上都要用户点头 —— 那正是 agentic 模式要避免的。别把它当"自动入口开关"。
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
    # ⚠️ `agentMode` 写成**机器可读**的形式 —— 这就是**唯一**的自动/手动判据，
    #    想核对"哪几个是自动入口"直接读它，不另立一张会与文件本身漂移的映射表。
    manual = item["mode"] == "manual"
    tail = ("（**手动选** —— 同方向已有一个自动可调用的 agent，两者职责重叠，"
            "同时参与自动调用会让同一句话走两条路、**行为不确定**）"
            if manual else "（**自动可调用**）")
    prov = (f"> 生成自 `{HOST_AGENT_REL}/{SRC_DIR.name}/{src.name}`"
            f"（由 `.codebuddy/agents/_build.py` 逐字移植）。**改规则请改源规格后重新生成。**\n"
            f"> `agentMode: {item['mode']}`{tail}\n\n")

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


def preset_rows() -> list[tuple[str, ...]]:
    """从宿主 `catalog.py` 里读出 ``PRESET_AGENTS`` 的每一项（id / 下拉显示名 / 说明 / 文件名）。

    ⚠️ 用 `ast` 解析而不是 `import`：那是宿主包里的模块（相对导入、还牵着别的宿主模块），
       单文件导入会失败；而这个检查不该以"宿主包能不能被导入"为前提。
    """
    tree = ast.parse(CATALOG.read_text(encoding="utf-8"))
    for node in tree.body:
        targets = [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        if not any(getattr(t, "id", None) == "PRESET_AGENTS" for t in targets):
            continue
        return [tuple(str(el.value) for el in elt.elts) for elt in node.value.elts]
    raise LookupError(f"{CATALOG} 里找不到 PRESET_AGENTS")


def preset_filenames() -> set[str]:
    """登记在宿主清单里的**文件名**集合。

    为什么要在这里查一遍：预置的**目录**与宿主清单的**登记**是两份东西，
    对不上时那个智能体会从面板下拉里**静默消失** —— 宿主侧自己的测试能抓，但它属于
    另一个包、另一套跑法；在"改源 + 生成"的同一条路上顺手查掉，人工就少一个漏点。
    """
    return {row[3] for row in preset_rows()}


def orphan_agents() -> list[str]:
    """本目录里**由本脚本命名**、但已不在 `SOURCES` 里的 `studio-*.md`。

    ⚠️ 抓的是"改名 / 删源规格之后遗留的孤儿"：它不在生成清单里，却还躺在 CodeBuddy
    的 agent 目录里被主 Agent 看见 —— 照着**已经不存在的规则**干活。只报不删：
    删文件不该由生成器偷偷做。
    """
    want = {it["name"] + ".md" for it in SOURCES}
    return sorted(p.name for p in HERE.glob("studio-*.md") if p.name not in want)


def main() -> int:
    ap = argparse.ArgumentParser(description="移植宿主包 presets 的规格 → CodeBuddy 子智能体")
    ap.add_argument("--预览", dest="preview", action="store_true",
                    help="只打印清单，不写文件")
    a = ap.parse_args()

    print(f"  源规格：{SRC_DIR}")
    print(f"  {len(SOURCES)} 份 → 生成 {len(SOURCES)} 个智能体到 {HERE}")
    print()
    total = 0
    for it in SOURCES:
        name, n, secs = build_one(it, a.preview)
        total += n
        flag = "（预览）" if a.preview else ""
        tag = "手动" if it["mode"] == "manual" else "自动"
        print(f"  ✅ {name:30s} {tag} 正文 {n:6d} 字符 ｜ {secs:3d} 个标题 {flag}")
    print()
    print(f"  合计正文 {total} 字符（≈ {total / 1024:.0f} KB）")
    auto = sum(1 for it in SOURCES if it["mode"] == "agentic")
    print(f"  自动可调用 {auto} 个 · 手动 {len(SOURCES) - auto} 个"
          f"（自动入口的判据只有各文件的 agentMode 一处）")

    # ── 宿主侧清单有没有登记这些规格（没登记 = 下拉里静默少一项）──
    print()
    print(f"── 宿主侧清单 PRESET_AGENTS 是否登记了这 {len(SOURCES)} 份 ──")
    rc = 0
    try:
        listed = preset_filenames()
    except Exception as exc:                                    # noqa: BLE001
        print(f"  ❌ 读不出 PRESET_AGENTS：{exc}")
        rc = 1
    else:
        want = {it["src"] for it in SOURCES}
        only_src, only_cat = sorted(want - listed), sorted(listed - want)
        if only_src or only_cat:
            print(f"  ❌ 不一致：清单里缺 {only_src}；清单里多 {only_cat}")
            print(f"     修法：改 {CATALOG} 的 PRESET_AGENTS"
                  "（id / 下拉显示名 / 说明 / 包内文件名的四项一组）")
            rc = 1
        else:
            print(f"  ✅ {len(listed)} 份都登记了（与源规格同名）")

    # ── 题材泄漏：口径是"与题材无关"，而它**不报错**就会静默漂回去 ──
    print()
    print("── 角色段 / description / 下拉说明里有没有具体题材 ──")
    leaks: list[str] = []
    for it in SOURCES:
        for word in topic_hits(it["desc"]):
            leaks.append(f"{it['name']} 的 description 里有「{word}」")
        body = (SRC_DIR / it["src"]).read_text(encoding="utf-8")
        for word in topic_hits(body):
            leaks.append(f"{it['name']} 的角色段（{it['src']}）里有「{word}」")
    try:
        rows = preset_rows()
    except Exception as exc:                                    # noqa: BLE001
        rows = []
        print(f"  ⚠️ 读不出 PRESET_AGENTS，下拉说明这一层没查：{exc}")
    for row in rows:
        for word in topic_hits(row[1] + row[2]):
            leaks.append(f"面板下拉「{row[1]}」里有「{word}」")
    if leaks:
        for line in leaks:
            print(f"  ❌ {line}")
        print("     口径：题材住在**具体项目的规则**里，不住在 agent 里（见本文件顶部）。")
        print("     改法：换成形态 / 能力的中性说法；具体数值保留为「默认档」，"
              "并在角色段声明一句「项目规则优先」")
        rc = 1
    else:
        print(f"  ✅ {len(SOURCES)} 份的角色段与 description、{len(rows)} 条下拉说明都干净")

    # ── 本目录有没有改名 / 删源后遗留的孤儿 ──
    print()
    print("── 本目录有没有遗留的孤儿 agent ──")
    orphans = orphan_agents()
    if orphans:
        print(f"  ❌ 不在生成清单里却还躺着：{orphans}")
        print("     它们是源规格改名 / 删除之前的产物，主 Agent 会照着**过时规则**干活；"
              "确认无用后删掉（本脚本不代删）")
        rc = 1
    else:
        print("  ✅ 没有孤儿")

    print()
    print("  校验（引擎侧）：cd ComfyUI/custom_nodes && python -m unittest "
          "comfy_studio.tests.test_agent_presets -t .")
    print("  校验（宿主侧）：cd Comfy-Desktop/lib && python -m unittest "
          "comfy_studio.tests.test_agents_tools")
    return rc


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
