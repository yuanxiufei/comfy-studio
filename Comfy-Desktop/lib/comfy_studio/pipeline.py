"""从小说到视频：把「一剧一目录」的生产阶段串成一条**能跑、能断点续跑**的流水线。

**为什么要有这一层**：``projects_spec.STAGE_SPECS`` 早写清了 S0a–S7a「谁做 · 落哪 · 怎么跑 ·
判据在哪」，``agent/catalog.py`` 早有七份成品人设，``novels.py`` 读得进原著，``projects.py``
建得出项目。可这四样**互相不认识** —— 面板上每一件都点得到，却没有一处能把"一部小说"
一路推到"一套可投产的视频提示词"。原先干这件事的是引擎侧运行时的 ``pipeline`` 模块
（``projects_spec.py`` 的 ``MIGRATIONS`` 注释里还留着它读的 ``pipeline.OUTLINE_JSON``），
它随 ``AI漫剧智能体工作流/07-智能体运行时/`` 整目录一起不在检出里了，本文件是它在本仓的落点。

**为什么落在宿主侧**：主编排要同时看得见四张表 —— 阶段表（``projects_spec``）、智能体目录
（``agent/catalog``）、原文（``novels``）、用户那份模型配置（``settings`` →
``LLMConfig.from_env``）。这四样**只有宿主进程全都有**：引擎进程既没有智能体目录，也不认
模型配置。见 :data:`STAGE_AGENT` 里"连接为什么放这儿"那条。

**这一段能做完什么、做不完什么（先说清）**：``STAGE_SPECS`` 每个阶段的 ``check_exts``
说的是**实质产物** —— S2 是 ``.png``、S5 是 ``.mp4``、S6 是 ``.mp3``。那些是**渲染**出来的，
要引擎侧运行时 + ComfyUI 工作流 + 模型权重才算得出来，本文件一行都产不出。所以每段分两半：

* **宿主侧能产的那半**：提示词与设定文本。这一半**真的写盘**，落在该阶段的 ``landings`` 里。
* **必须引擎侧渲染的那半**：``needs_render=True`` 的阶段在报告里带 ``render_pending``，
  并**明说缺什么** —— 绝不把"文本写出去了"报成"S2 完成了"。这正是 ``STAGE_OUTPUTS``
  只查 ``check_dirs`` / ``check_exts`` 的原因：它查实质产物，假不了。本文件沿用同一条口径，
  不另造一个宽松的"完成"判据。

**断点续跑**：``<项目>/00_PROJECT/05_流程/pipeline-state.json`` 记着哪一段跑过、产物是哪一份。
再跑一遍时产物还在的那几段直接跳过（``force=True`` 才重跑）。为什么状态要落盘而不只看
"产物在不在"：每段都是**要花钱、要等**的模型调用，而"产物在不在"分不清"上次跑完了"与
"上次写到一半"。**只跑过一半的段不算跑过**（见 :meth:`NovelToVideoPipeline._done_before`）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from .agent.catalog import AgentCatalog, AgentListing
from .agent.llm import LLMConfig, OpenAIChatClient
from .agent.types import ChatMessage, system_message, user_message
from .cancel import CancelToken
from .mcp import McpError, McpTool
from .novels import NovelLibrary, NovelsError, resolve_novel
from .projects import DEFAULT_EPISODES, ProjectLibrary
from .projects_spec import (
    PROJECT_DIRS,
    STAGE_BY_CODE,
    STAGE_ORDER,
    STEP_ORDER,
    WORKBENCH_STEPS,
    resolve_project,
    scan_project,
    stage_how,
    step_gaps,
    step_stages,
)
from .review import ReviewChannel, ReviewError

#: 状态账的版本号。形状变了就加它 —— 老账读不动时**明确报错**，不猜着读。
#:
#: 2：阶段表从八段长成十一段（补了原文解析 / 对白与旁白 / 短剧合成三段，代号 S0a / S4a / S7a）。
#: 加了段就**必须**加这个号：老账里没有这三段的记录，读成"还没跑"是错的 ——
#: 那三段里有两段（原文解析、对白）在链的**前面**，老账把它们读成"没跑"的话，
#: 一次 `--from` 重跑会从半路开始，而报告上写着"已补齐"，人不会去追。
STATE_VERSION = 2

#: 机器可读的分集大纲。**与 ``projects_spec.MIGRATIONS`` 的目标路径逐字一致**：那份表专门
#: 警告过，它留在老位置时建纲阶段读不到就会重写一份，静默覆盖人改过的大纲。本文件认同一个
#: 位置，并且**已有就绝不动它**（见 :meth:`NovelToVideoPipeline._write_outline`）。
OUTLINE_JSON = "00_PROJECT/01_剧本/00_总纲/_分集大纲.json"

#: 流水线自己的状态账。放 `05_流程` 是它的本分：那里本来就是"流程与进度"的落点。
STATE_REL = "00_PROJECT/05_流程/pipeline-state.json"

#: 一次交给模型的**原著**最多多少字符。原著动辄上百万字，整本塞进去既超上下文也没必要：
#: S0 是先定骨架，骨架看开头就够，细节留给 S4 分镜按集去取。
NOVEL_EXCERPT_CHARS = 12000

#: 一次交给模型的**上游产物**每份最多多少字符。七段连着跑，产物会越滚越大。
UPSTREAM_EXCERPT_CHARS = 8000

#: 模型输出里认的 JSON 块（`````json ... `````）。S0 的机器可读大纲从这里取。
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

#: 阶段的三种归宿。``skipped`` 是"上次跑过、产物还在"，与"这次没做"不是一回事。
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

#: 工作台里**一段**现在什么样（见 :meth:`NovelToVideoPipeline.stage_mark`）。
#: 这四个字是回给面板的（``comfyStudioChatContentScript.ts`` 的 ``stepChip`` 按它们出签），
#: 与上面那三个 ``STATUS_*`` **不是一回事**：那三个是"账上记着跑成什么样"，
#: 这四个是"这一格该显示什么"。``text`` 与 ``missing`` 在账里都没有对应值 ——
#: 那两种情形账本身是自洽的，是**盘**跟账对不上。
MARK_TODO = "todo"
MARK_TEXT = "text"
MARK_MISSING = "missing"
#: 一段成了：账与盘都这么说（与 ``STATUS_DONE`` 同一个字面量，别写成两个字面量）。
MARK_DONE = STATUS_DONE
#: 只有**一步**才有的两种：这一步一段都没跑、且落点也空（``empty``）；
#: 料不齐（``partial``，含"只有文本、实质产物还要引擎侧渲染"那种）。
MARK_EMPTY = "empty"
MARK_PARTIAL = "partial"

#: 单段的墙钟上限（秒）。超了就把这一段判失败，并说清是"没在时限内回话"。
#:
#: **为什么必须有**：请求是**非流式**的（见 ``agent/llm.py`` 的 ``max_tokens`` 注释），
#: 整段生成完才回来第一个字节；本机小模型一旦收不住（复读、长篇思考），外面看就是**永远卡住**
#: —— 实测一次 27B 本地模型跑 S0 超过 25 分钟仍未回话，而流水线不自带看门狗
#: （它不走 ``AgentSession``，见 :class:`LLMStageRunner`），前端也只有慢档超时兜底。
#: 有了这条上限，"卡住"就变成一条写着阶段与用时的显式失败。
#:
#: 默认给得宽（对齐 ``server.DEFAULT_TURN_TIMEOUT``）：正经的长稿本来就要时间。
STAGE_TIMEOUT_SECONDS = 1800.0

#: 改上限用的环境变量。填了不像正数的值**当场报错**，不悄悄忽略：配置写错了却照常跑起来，
#: 用户只会以为"这个开关没用"（口径同 ``agent/llm.py`` 的 ``_max_tokens_from_env``）。
STAGE_TIMEOUT_ENV = "COMFY_STUDIO_PIPELINE_STAGE_TIMEOUT"


def _stage_timeout_from_env(default: float = STAGE_TIMEOUT_SECONDS) -> float:
    raw = os.environ.get(STAGE_TIMEOUT_ENV, "").strip()
    if raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise PipelineError(f"{STAGE_TIMEOUT_ENV} 必须是正数（秒），给的是 {raw!r}") from None
    if value <= 0:
        raise PipelineError(f"{STAGE_TIMEOUT_ENV} 必须是正数（秒），给的是 {raw!r}")
    return value

#: 正在跑的项目（项目根路径）。同一项目两条流水线同时跑，会**各写各的进度账**，
#: 后写的把先写的盖掉 —— 而两边都真的在调模型（**钱是双份的**），最后一次报告
#: 还会把另一条的段算成"没跑"。所以第二条当场拒绝，不并发。
#:
#: 只管**同进程**（面板连点两次、两条 ``pipeline/run`` 撞上）。跨进程（面板 + 手工
#: 命令行各跑一条）没做文件锁：Windows 上进程被强杀会留下清不掉的锁，那比"多跑一次"
#: 更坏 —— 用户从此每次都被一个不存在的"正在跑"挡住，还得自己去删那个文件。
RUNNING_PROJECTS: set[str] = set()


# ─────────────────────────────────────────────────────────────
# 一、阶段 ↔ 智能体 ↔ 文本产物（**两张表的连接**，不是新的事实）
# ─────────────────────────────────────────────────────────────

#: 阶段 → 随包预置智能体 id（``agent/catalog.py`` 的 ``PRESET_AGENTS``）。
#:
#: **为什么这张表在这儿而不在 ``projects_spec.py``**：它是**两张表的连接**，不是新的事实。
#: ``projects_spec`` 说得出"这一段归谁做"（``owner``，人话），``catalog`` 说得出"有哪些智能体"
#: （id），但 ``projects_spec`` 被刻意做成"只 import 标准库、没有包内相对导入"（它要能被
#: ``--spec`` 按路径单独执行），于是它**看不见** ``catalog``。本模块是唯一同时看得见这两张表的
#: 模块，所以连接放这里；"不许分家"由 ``tests/test_pipeline.py`` 机械核对：覆盖
#: ``STAGE_ORDER`` 每一项，且每个非空 id 都真实存在于 ``PRESET_AGENTS``。
#:
#: S7 是空串，**不是漏填**：``PRESET_AGENTS`` 里没有合规审核智能体（七份分别是剧本、服化道、
#: 资产库、分镜、视频、调音、歌词）。空串 = 这一段不由模型生成，改走机械体检。编一个 id 出来
#: 才会把事情搞坏：它会静默地拿"剧本创作"的人设去审合规。
STAGE_AGENT: dict[str, str] = {
    "S0a": "script",
    "S0": "script",
    "S1": "costume",
    "S2": "costume",
    "S3": "asset",
    "S4": "storyboard",
    "S4a": "script",
    "S5": "video",
    "S6": "voice",
    "S7": "",
    "S7a": "video",
}

#: 阶段 → (文本产物相对路径, 是否还有一半得引擎侧渲染)。
#: 路径的父目录**必须**是 ``PROJECT_DIRS`` 里的一项（也就是该阶段的 ``landings``），
#: 由 ``tests/test_pipeline.py`` 机械核对 —— 落点写错的失效模式是产物掉在面板看不见的地方。
STAGE_ARTIFACT: dict[str, tuple[str, bool]] = {
    "S0a": ("00_PROJECT/00_原文解析/原文解析.md", False),
    "S0": ("00_PROJECT/01_剧本/00_总纲/分集大纲与三表.md", False),
    "S1": ("00_PROJECT/02_资产索引/资产总表.md", False),
    "S2": ("00_PROJECT/04_交付与出图/出图提示词_S2.md", True),
    "S3": ("06_EXPRESSIONS/表情与动作提示词.md", True),
    "S4": ("08_STORYBOARDS/分镜表.md", False),
    "S4a": ("00_PROJECT/06_对白/对白稿/对白与旁白表.md", False),
    "S5": ("09_SHOTS/视频提示词.md", True),
    "S6": ("11_AUDIO/声音提示词.md", True),
    "S7": ("10_CONSISTENCY/合规体检.md", False),
    "S7a": ("00_PROJECT/04_交付与出图/成片合成单.md", True),
}

#: 阶段 → 引擎侧那 12 张**生产工作流**里，这一段的实质产物该用哪几张出。
#: id 就是引擎 ``skills/render.py`` 的 ``RENDER_TARGETS`` 里的 id（宿主不 import 引擎，
#: 只能照抄在这儿）；有序，第一条是首选。
#:
#: **为什么要有这张表**：``needs_render`` 只说得出"图还没出"，说不出**用哪张图出**。
#: 用户看着卡片上那句"跑完还要回引擎侧出图"，手上只有一排 12 个目标要自己认 —— 认错不报错，
#: 只会出成另一张图（比如把场景卡当角色定妆板）。钉死"这一段 ↔ 这张图"，卡片上才能直接
#: 摆一个「去出图」。
#:
#: **键集必须与 ``needs_render=True`` 的那几段一字不差**，由 :func:`_build_tasks` 与
#: ``tests/test_pipeline.py`` 机械核对 —— 这张表两种错法都不响：少一条 = 按钮画不出来、
#: 用户又得自己猜；多一条 = 卡片摆出一个"出图"按钮，而这一步的完成判定压根不看图。
#:
#: 前缀 ``character-sheet`` 的那三张是**同一套角色配方**的三个档（质量 / 快档 / Z-Image）：
#: 这里绑的是配方，档位在图那一行的下拉里换，别把三个档都当成三个用途。
#:
#: 每一项是 ``(渲染目标 id, 落点目录)``。落点**必须是这一段 ``check_dirs`` 里的一个**，
#: 由 :func:`_check_render_bindings` 机械核对 —— 出图时面板把它拼在项目根后面，当
#: ``renders/run`` 的 ``output_dir`` 交给引擎（引擎那边落盘见 ``renders/catalog.py``）。
#:
#: **为什么落点也要钉在这里**：不钉的话，图只会留在引擎自己的 ``output/`` 里，而这一段的体检
#: 看的是项目目录 —— 卡片上"还缺图"就永远不消，人以为白跑了一趟。这跟 id 绑错一样是**不响**的
#: 那种错：出了图、也算出了东西，只是没出在该在的地方。
STAGE_RENDER: dict[str, tuple[tuple[str, str], ...]] = {
    # 角色的三视图落 02_CHARACTERS、场景的六角度落 05_ENVIRONMENTS（02–05 那四个目录里的 .png）。
    # 服装与道具走的是同一套角色配方、按内容分落 03_COSTUMES / 04_PROPS —— 见 STAGE_RENDER_NOTE。
    "S2": (("character-sheet", "02_CHARACTERS"), ("scene-card", "05_ENVIRONMENTS")),
    # 表情集与动作集：还是那套角色配方，出的是同一个角色的多张变体（动作集那一格的落点见附言）。
    "S3": (("character-sheet", "06_EXPRESSIONS"),),
    # 逐镜出片：先试片看提示词对不对，再上正片；多镜连贯那条用在"镜间要保持同一人物"时。
    # 三张都落 09_SHOTS —— 这一段的体检看的就是它。
    "S5": (
        ("video-draft", "09_SHOTS"),
        ("video-final", "09_SHOTS"),
        ("video-multishot", "09_SHOTS"),
    ),
    # 音频这一类，引擎侧目前**只有主题曲这一张图**（见下面的 STAGE_RENDER_NOTE）。
    "S6": (("music", "11_AUDIO"),),
    # 成片母版走放大；补帧是可选的那一步。两张都落交付那一格。
    "S7a": (
        ("video-upscale", "00_PROJECT/04_交付与出图"),
        ("video-interpolate", "00_PROJECT/04_交付与出图"),
    ),
}

#: 上面那几条要说清的一句（报告里原样带出去、画在按钮旁边）。没写的段就是不附言。
#:
#: 存在的理由：光看 id 会**把话说满**。S6 绑的是主题曲，而这一段要的是配音与环境声 ——
#: 引擎侧还没有那两张图，不说清的话，用户会以为按下去出来的是配音。这一句就是那层"到哪为止"。
#:
#: S2 / S3 后半句说的是**落点那一层**的"到哪为止"：面板一次只填得了一个输出目录，而这两段
#: 一个目录装不下（服装/道具、表情/动作各自成格）。不写清的话，服装图会静默地躺在角色那一格里。
STAGE_RENDER_NOTE: dict[str, str] = {
    "S2": (
        "角色/服装/道具走定妆板，场景走设定卡；分镜首帧不在这一段（S4 的活，它的完成判定不看图）。"
        "「去出图」落的是首选那一格（角色 → 02_CHARACTERS、场景 → 05_ENVIRONMENTS）："
        "服装与道具是同一套配方，出完按内容归到 03_COSTUMES / 04_PROPS"
    ),
    "S3": (
        "表情与动作走的是同一套角色配方：这一段量最大，要快档试提示词的话，"
        "在渲染那一行把图换成 character-sheet-lightning。"
        "落点填的是表情那一格（06_EXPRESSIONS），动作集出完归到 07_POSES"
    ),
    "S5": "先试片（768p）看提示词对不对，再上正片；首帧/尾帧在渲染那一行的参考图里给（本机图片路径）",
    "S6": "引擎侧现在只有主题曲这一张音频图；配音、环境声、Foley 都还没有对应的图 —— 这一段出的不是配音",
    "S7a": "放大出成片母版，补帧是可选的一步；两张的输入片子都要先用 stage_input_file 放进引擎 input/",
}

#: 阶段 → 交给模型的一句话（"这一段要产出什么"）。
#: 不写在 ``projects_spec`` 里：那里的 ``gate`` 只写判据**在哪**（见它自己的 ⚠️），
#: 而这里是**要模型产出什么**，是提示词的一部分，会随人设一起改。
STAGE_BRIEF: dict[str, str] = {
    "S0a": (
        "读原著，产出**原文解析**：① 章节切分（章节号 + 一句话说这一章发生了什么）"
        "② 场景切分（地点 / 时间 / 在场人物 / 这一场在故事里的作用）"
        "③ 出场人物清单（姓名、身份、与主角的关系、首次出场的位置）"
        "④ 关键情节与卡点（可以改编成钩子的地方）"
        "⑤ 改编取舍建议（哪几条线可以并、哪几条必须留）。"
        "只做解析：这一段的产物是给后面几段看的底账，不写剧本、不定集数、不出分镜。"
    ),
    "S0": (
        "读原著（或它的开头），产出三样：① 分集大纲（每集一句话钩子 + 集末卡点）"
        "② 人物三表（人物表 / 关系表 / 势力表）③ 角色小传。"
        "正文之后另起一个 ```json 代码块给出机器可读的分集骨架，"
        '顶层必须是对象，至少含 "集数" 与 "角色" 两个键；'
        "给不出就别给这个块，不要编一个形状不对的 JSON。"
    ),
    "S1": (
        "按 S0 的大纲与 S0a 的原文解析产出资产总表，分三块写："
        "① **角色与场景提取** —— 把原著与剧本里出现过的人物、地点、势力逐个捞出来去重，"
        "标出他在故事里的作用与首次出场的位置；"
        "② **视觉风格定义** —— 定下全剧的色彩、材质、光线、时代与镜头质感，"
        "它是后面出图与出视频的统一口径，先定它再列清单；"
        "③ 按这份口径列出世界观、角色、服装、道具、场景各自的清单与视觉要点。"
        "每条资产给一个稳定 ID，前缀分别是 WOR_ / CHR_ / CST_ / PRP_ / ENV_，序号三位。"
    ),
    "S2": (
        "把 S1 的资产逐条写成**图像生成提示词**（中英双语 + 负面提示词 + 角色的三视图要求 / "
        "场景的六角度要求）。只产提示词，不出图 —— 出图那一步在引擎侧。"
    ),
    "S3": (
        "在 S2 的角色基础上产出表情集与动作集的提示词：每个主要角色一组表情、一组动作，"
        "逐条标注用途与适配镜头。同样只产提示词。"
    ),
    "S4": (
        "把大纲逐集拆成可拍摄的分镜：镜号、景别、机位、构图、运镜、光影、时长、画面描述，"
        "以及每镜的人物 Identity Lock 与场景 Environment Lock。"
    ),
    "S4a": (
        "按 S4 的分镜表逐个镜头写对白与旁白，一镜一行：镜号、说话人（写「旁白」的另起一格）、"
        "台词、语气、这句大致占多长时间。旁白交代时间跳跃与人物内心，对白推进冲突 —— "
        "不要把分镜里的画面描述复述成旁白。台词量按镜头时长收着写，宁短勿长。"
        "正文之后另起一节写**配音单**：哪几句要进录音、按什么顺序、每句的表演提示。"
    ),
    "S5": (
        "把 S4 的分镜逐镜写成可投产的视频提示词（逐镜五段式 + 时长 + 运动强度），"
        "并给出镜间衔接（上一镜尾帧 → 下一镜首帧）与一致性校验清单。"
        "这是本流水线的终点交付物：拿到它就能去可灵 / Seedance / 即梦那类平台出片。"
    ),
    "S6": (
        "产出声音设计：人物声线、环境声、道具 Foley、剧情声音表现，"
        "逐条给出标准化的声音提示词，并标明它对应哪一集哪一镜。"
    ),
    "S7": "",
    "S7a": (
        "把 S5 的逐镜视频与 S6 的声音合成成片，产出**合成单**：每一镜用哪个镜头文件、"
        "对哪一条音轨、入出点（时间码）、转场方式、字幕，以及全片的总时长与分辨率。"
        "再单列一节**合成前必须核过的一致性项**：镜间尾帧接得住首帧、音画是否同步、"
        "音量有没有统一基准、字幕与对白是否逐字一致 —— 每条写清拿什么去核。"
        "只出合成单与校验清单；真正的合成要回引擎侧跑，这一段在宿主侧到此为止。"
    ),
}

#: 流水线自己的底座人设。**刻意不用 ``agent/loop.py`` 的 ``BASE_SYSTEM_PROMPT``**：
#: 那一条是**带工具的聊天助手**人设（"先用 plan__submit 把步骤清单交给他过一眼"、
#: "图片用返回的 url 原样给出"），而流水线每一段是**无人值守的一次性文本生成**，
#: 没有工具、也没人在旁边点头。照搬那条会让模型去等一个永远不来的确认。
PIPELINE_SYSTEM_PROMPT = (
    "你在一条「小说 → 视频」的生产流水线里干活，这一次只负责其中的一段。"
    "产出会直接写进项目文件，所以**只写正文**：不要寒暄，不要复述任务，不要问要不要继续，"
    "不要用工具（这一段没有工具可用）。"
    "用中文写；只有明确要求双语提示词时才附英文。"
    "材料不够就按现有内容做最合理的假设，并在正文最后用一行「> 假设：…」说明补了什么。"
    "这条流水线是无人值守跑的，停下来等确认等于把这一段丢掉。"
)


class PipelineError(RuntimeError):
    """流水线层面的错误：项目/原文不对、阶段代码不存在、状态账读不动、智能体缺了。"""


@dataclass(frozen=True)
class StageTask:
    """一段活：谁做 · 要产出什么 · 落在哪 · 还差哪一半得引擎侧渲染（用哪张图出）。"""

    code: str
    name: str
    owner: str
    #: 随包预置智能体 id；空串 = 这一段不用模型（体检型，见 :meth:`_check_report`）。
    agent_id: str
    #: 文本产物相对项目根的路径。恒非空 —— 每段都至少留下一份可读的文本。
    artifact: str
    #: True = 这一段的**实质产物**（图 / 视频 / 音频）还得引擎侧渲染才算数。
    needs_render: bool
    #: 交给模型的一句话：这一段要产出什么。
    brief: str
    #: 该阶段的实质产物体检口径（取自 ``STAGE_SPECS``），报告里原样带出去。
    check_dirs: tuple[str, ...]
    check_exts: tuple[str, ...]
    #: 这一段的实质产物该用引擎侧哪几张图出、各自落进哪个目录（``STAGE_RENDER``）。
    #: 空 = 这一段没有那一半。落点取自这一段的 ``check_dirs``（:func:`_check_render_bindings` 核对）。
    render_lands: tuple[tuple[str, str], ...] = ()
    #: 绑这几张图时要说清的一句（``STAGE_RENDER_NOTE``），报告里原样带出去。
    render_note: str = ""

    @property
    def render_targets(self) -> tuple[str, ...]:
        """只要目标 id（面板拿它画按钮）。落点见 :attr:`render_lands`。"""
        return tuple(target for target, _ in self.render_lands)

    @property
    def actor(self) -> str:
        """这一段由谁做（报告里那一列）。空 id 时如实说"不用模型"。"""
        return self.agent_id or "机械体检（不用模型）"

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "owner": self.owner,
            "agent": self.agent_id,
            "actor": self.actor,
            "artifact": self.artifact,
            "needs_render": self.needs_render,
            # 面板拿这几条画「去出图」那排按钮（空数组 = 这一步不用出图，见 STAGE_RENDER）；
            # ``render_lands`` 是"按下去存进哪一格"，面板拼上项目根当 output_dir 交给渲染 ——
            # 没有它，图只会留在引擎的 output/ 里，这一段的体检永远还是"缺图"。
            "render_targets": list(self.render_targets),
            "render_lands": dict(self.render_lands),
            "render_note": self.render_note,
            "brief": self.brief,
            "check_dirs": list(self.check_dirs),
            "check_exts": list(self.check_exts),
        }


@dataclass
class StageOutcome:
    """一段跑完的样子。``error`` 非空就是这一段没成 —— 不吞。"""

    code: str
    name: str
    status: str
    agent_id: str
    artifact: str
    needs_render: bool
    seconds: float
    note: str = ""
    error: str = ""
    #: 同 :attr:`StageTask.render_lands`：还缺的那些图**是哪几张、该落进哪一格**。
    #: ``render_pending`` 只说"还缺"，说不出"缺的叫什么" —— 卡片上那枚按钮靠这一条才画得出来。
    render_lands: tuple[tuple[str, str], ...] = ()
    render_note: str = ""

    @property
    def render_targets(self) -> tuple[str, ...]:
        """只要目标 id（面板拿它画按钮）。落点见 :attr:`render_lands`。"""
        return tuple(target for target, _ in self.render_lands)

    @property
    def render_pending(self) -> bool:
        """文本产物有了，但实质产物还缺（要引擎侧渲染）。报告里必须看得见这一条。"""
        return self.status in (STATUS_DONE, STATUS_SKIPPED) and self.needs_render

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "status": self.status,
            "agent": self.agent_id,
            "artifact": self.artifact,
            "needs_render": self.needs_render,
            "render_pending": self.render_pending,
            "render_targets": list(self.render_targets),
            "render_lands": dict(self.render_lands),
            "render_note": self.render_note,
            "seconds": round(self.seconds, 2),
            "note": self.note,
            "error": self.error,
        }


#: 跑一段的出口：``(任务, 系统提示词, 用户提示词) -> 正文``。
#: 之所以做成可注入的口子而不是就地调模型：单测要能在**没有模型、不联网**的情况下，
#: 把编排逻辑（顺序、断点续跑、落盘、失败即停）整条走一遍。生产用 :class:`LLMStageRunner`。
StageRunner = Callable[[StageTask, str, str], Awaitable[str]]


class LLMStageRunner:
    """生产用的出口：按一份 ``LLMConfig`` 发一轮请求，拿回正文。

    **不用 ``AgentSession`` 是有意的**：会话要求至少一个工具（见 ``agent/loop.py`` 的
    ``AgentSession.__init__`` 那句 ``一个工具都没有``），而流水线每一段的产出都是
    "读上下文 → 写文本"，工具不是它要的东西 —— 硬塞一个空工具表，只是为满足断言而造一个假工具。
    真要用工具的阶段（出图、渲染）本来就不在本文件的能力范围里（见模块开头）。

    ``tools=None`` 是照实说"这次没有工具"：``OpenAIChatClient.complete`` 收这个形状。
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config
        self.client = OpenAIChatClient(config) if config is not None else OpenAIChatClient(
            LLMConfig.from_env()
        )

    async def __call__(self, task: StageTask, system_prompt: str, user_prompt: str) -> str:
        messages: list[ChatMessage] = [
            system_message(system_prompt),
            user_message(user_prompt),
        ]
        reply = await self.client.complete(messages, None)
        return reply.content or ""

    async def close(self) -> None:
        await self.client.close()


def _require_landing(rel: str, *, what: str) -> str:
    """文本产物的父目录必须是 ``PROJECT_DIRS`` 里的一项。

    落点写错的失效模式是**产物掉在面板看不见的地方**：写盘成功、报告一切正常，
    只是没人找得到它。所以这里当场抛错，而不是默默建一个新目录。
    """
    parent = os.path.dirname(rel).replace("\\", "/")
    if parent not in PROJECT_DIRS:
        raise PipelineError(
            f"{what} 的落点 {rel!r} 不在项目目录清单里（父目录 {parent!r}）；"
            "PROJECT_DIRS 见 projects_spec.py。落点不在清单里等于产物没人找得到。"
        )
    return rel


#: 渲染目标的 id 长什么样（``STAGE_RENDER`` 里那些）。见引擎 ``skills/render.py``。
_RENDER_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _check_render_bindings() -> None:
    """核对 ``STAGE_RENDER`` 与 ``needs_render`` 是不是**同一批阶段**、落点在不在体检口径里。

    这几张表分家都不响，而且错法各自坏在不同地方：

    * 少绑一条 —— 卡片画不出「去出图」，用户又得自己在 12 张里认，认错只会出成另一张图；
    * 多绑一条 —— 卡片摆出一个"出图"按钮，而这一步的完成判定压根不看图：按下去跑出来的东西
      没人验，也没人知道该不该验；
    * 落点不在 ``check_dirs`` 里 —— 图出得成、也确实落了盘，**只是落在体检不看的地方**：
      卡片上"还缺图"永远不消，人以为白跑一趟（同 :func:`_require_landing` 那条道理）。

    另外顺手把 id 的形状与"附言挂在空处"这两种也挡掉。
    """
    pending = {code for code, (_, needs) in STAGE_ARTIFACT.items() if needs}
    bound = {code for code, lands in STAGE_RENDER.items() if lands}
    if bound != pending:
        raise PipelineError(
            "STAGE_RENDER 与 STAGE_ARTIFACT 的 needs_render 对不上："
            f"要出图却没绑图的是 {'、'.join(sorted(pending - bound)) or '（没有）'}；"
            f"绑了图却不用出图的是 {'、'.join(sorted(bound - pending)) or '（没有）'}。"
        )
    for code, lands in STAGE_RENDER.items():
        spec = STAGE_BY_CODE.get(code)
        if spec is None:
            # 这一条本该由 _build_tasks 末尾的 extra 那句拦下（话说得更全），但这里先读到它 ——
            # 与其抛 KeyError，不如给同一句人话。
            raise PipelineError(
                f"STAGE_RENDER 里的 {code} 不是 S0a–S7a 里的阶段（见 projects_spec.STAGE_ORDER）"
            )
        for target, land in lands:
            if not _RENDER_ID_RE.match(target):
                raise PipelineError(
                    f"阶段 {code} 绑的渲染目标 {target!r} 不像个 id（小写字母 / 数字 / 连字符，"
                    "如 character-sheet）；id 见引擎 skills/render.py 的 RENDER_TARGETS。"
                )
            if land not in spec.check_dirs:
                raise PipelineError(
                    f"阶段 {code} 给 {target} 绑的落点 {land!r} 不在这一段的体检目录里"
                    f"（{'、'.join(spec.check_dirs)}）；出图会落在体检不看的地方，"
                    "卡片上「还缺图」就永远不消。"
                )
    strays = set(STAGE_RENDER_NOTE) - set(STAGE_RENDER)
    if strays:
        raise PipelineError(
            f"STAGE_RENDER_NOTE 里这几段没绑图，那句话会挂在空处：{'、'.join(sorted(strays))}"
        )


def _build_tasks() -> tuple[StageTask, ...]:
    """把这几张静态表拧成任务清单。**顺序 = ``STAGE_ORDER``**，不另排一遍。"""
    _check_render_bindings()
    tasks: list[StageTask] = []
    for code in STAGE_ORDER:
        spec = STAGE_BY_CODE[code]
        if code not in STAGE_AGENT:
            raise PipelineError(f"阶段 {code} 没有配智能体（见 STAGE_AGENT）")
        if code not in STAGE_ARTIFACT:
            raise PipelineError(f"阶段 {code} 没有配文本产物落点（见 STAGE_ARTIFACT）")
        artifact, needs_render = STAGE_ARTIFACT[code]
        tasks.append(
            StageTask(
                code=code,
                name=spec.name,
                owner=spec.owner,
                agent_id=STAGE_AGENT[code],
                artifact=_require_landing(artifact, what=f"阶段 {code}"),
                needs_render=needs_render,
                brief=STAGE_BRIEF.get(code, ""),
                check_dirs=tuple(spec.check_dirs),
                check_exts=tuple(spec.check_exts),
                render_lands=STAGE_RENDER.get(code, ()),
                render_note=STAGE_RENDER_NOTE.get(code, ""),
            )
        )
    extra = (
        set(STAGE_AGENT)
        | set(STAGE_ARTIFACT)
        | set(STAGE_BRIEF)
        | set(STAGE_RENDER)
        | set(STAGE_RENDER_NOTE)
    ) - set(STAGE_ORDER)
    if extra:
        raise PipelineError(
            f"这几张表里有不属于 S0a–S7a 的键：{'、'.join(sorted(extra))}；"
            "阶段表以 projects_spec.STAGE_ORDER 为准。"
        )
    return tuple(tasks)


#: 阶段任务清单。模块导入时算一次 —— 三张表是静态的，拧坏了要当场知道，不是等跑到那儿。
STAGE_TASKS: tuple[StageTask, ...] = _build_tasks()
STAGE_TASK_BY_CODE = {task.code: task for task in STAGE_TASKS}


def _slice_tasks(
    tasks: tuple[StageTask, ...], from_code: str | None, to_code: str | None
) -> tuple[StageTask, ...]:
    """按 ``--从 / --到`` 切一段。阶段代码打错时**报错并列出有效的**，不当作"全跑"。"""
    for code in (from_code, to_code):
        if code is not None and code not in STAGE_TASK_BY_CODE:
            raise PipelineError(
                f"没有这个阶段：{code!r}；有效的有：{'、'.join(STAGE_ORDER)}"
            )
    start = STAGE_ORDER.index(from_code) if from_code else 0
    stop = STAGE_ORDER.index(to_code) + 1 if to_code else len(tasks)
    if start >= stop:
        raise PipelineError(
            f"起止反了：--从 {from_code}（第 {start + 1} 段）在 --到 {to_code}"
            f"（第 {stop} 段）之后，这一段是空的。"
        )
    return tasks[start:stop]


class NovelToVideoPipeline:
    """一部小说 → 一套可投产产物的那一条流水线。

    ``runner`` 不给就用 :class:`LLMStageRunner`（读环境变量 / ``settings.json`` 那份配置）。
    """

    def __init__(
        self,
        project: str | os.PathLike[str],
        novel: str | os.PathLike[str] | None = None,
        *,
        catalog: AgentCatalog | None = None,
        runner: StageRunner | None = None,
        config: LLMConfig | None = None,
        episodes: int = 1,
        stage_timeout: float | None = None,
        on_event: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        try:
            self.project = Path(resolve_project(str(project)))
        except Exception as err:  # ProjectError：项目不在 / 项目根没探测到
            raise PipelineError(f"项目用不了：{err}") from err
        # 原文也走"必须明说在哪"的口径：给了就读，读不了当场报错。静默跳过的失效模式是
        # 模型按"没有原著"编出一部剧来，而报告上一切正常。
        self.novel = Path(novel).expanduser() if novel is not None else None
        if self.novel is not None and not self.novel.is_file():
            raise PipelineError(f"原著不存在或不是文件：{self.novel}")
        self.catalog = catalog if catalog is not None else AgentCatalog()
        self.runner = runner
        self.config = config
        self.episodes = int(episodes)
        if self.episodes < 1:
            raise PipelineError(f"集数必须 ≥ 1，收到 {episodes!r}")
        self.on_event = on_event
        # 单段上限：显式给就用它，否则读环境变量，再否则用默认值（见 STAGE_TIMEOUT_SECONDS）。
        self.stage_timeout = (
            float(stage_timeout) if stage_timeout is not None else _stage_timeout_from_env()
        )
        if self.stage_timeout <= 0:
            raise PipelineError(f"单段上限必须是正数（秒），收到 {stage_timeout!r}")
        self.state_path = self.project / STATE_REL

    # ---- 计划 -----------------------------------------------------------

    def plan(self) -> tuple[StageTask, ...]:
        """逐段算出要什么。**不碰模型、不落盘** —— 面板点开就能看。

        顺带核对"要用的智能体真的在清单里"：少一份人设（包被裁掉、文件被改坏）时**当场报错**，
        并把目录扫描报出来的问题一起带上。不报的失效模式是那一段拿**空人设**去跑 ——
        产出看着像样，其实没有任何角色约束。
        """
        listing = self.catalog.scan()
        wanted = {task.agent_id for task in STAGE_TASKS if task.agent_id}
        known = {profile.id for profile in listing.profiles}
        missing = sorted(wanted - known)
        if missing:
            raise PipelineError(
                f"这几种智能体不在清单里：{'、'.join(missing)}。"
                f"{self._catalog_problems(listing)}"
                "它们随包预置在 agent/presets/ 下；文件被删或被改坏时也会这样。"
            )
        return STAGE_TASKS

    @staticmethod
    def _catalog_problems(listing: AgentListing) -> str:
        lines = [f"{p.file}：{p.error}" for p in listing.problems]
        if listing.error:
            lines.append(f"（目录整体：{listing.error}）")
        return "；".join(lines) + "。" if lines else ""

    # ---- 状态账 ---------------------------------------------------------

    def state(self) -> dict[str, Any]:
        """读状态账。**没有就是没有**（新项目），不是错误；有但读不动才是错误。"""
        if not self.state_path.is_file():
            return {"version": STATE_VERSION, "project": str(self.project), "stages": {}}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
            raise PipelineError(f"状态账读不动（{self.state_path}）：{err}") from err
        if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
            raise PipelineError(
                f"状态账的版本不认（{self.state_path} 里是 {raw.get('version')!r}，"
                f"本程序认 {STATE_VERSION}）。要么换回旧程序，要么删掉它重跑一遍 —— "
                "猜着读会把「哪一段跑过」读错，之后重跑与不跑都是错的。"
            )
        if not isinstance(raw.get("stages"), dict):
            raise PipelineError(f"状态账里没有 stages（{self.state_path}）")
        return raw

    def _save_state(self, state: dict[str, Any]) -> None:
        state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        state["project"] = str(self.project)
        state["novel"] = str(self.novel) if self.novel is not None else None
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(state, ensure_ascii=False, indent=2)
        self.state_path.write_text(text + "\n", encoding="utf-8")

    # ---- 一段成没成（断点续跑与工作台共用下面这两个原子）------------------

    def _artifact_ready(self, task: StageTask) -> bool:
        """这一段该落的**文本产物**在不在盘上。**只看盘**，账的说法交给 :meth:`_recorded_done`。"""
        return (self.project / task.artifact).is_file()

    @staticmethod
    def _recorded_done(ledger: dict[str, Any], task: StageTask) -> bool:
        """账上写着这一段跑完过没有。**只看账**，盘上有没有交给 :meth:`_artifact_ready`。"""
        record = ledger.get(task.code)
        return isinstance(record, dict) and record.get("status") == STATUS_DONE

    def stage_mark(self, ledger: dict[str, Any], task: StageTask) -> str:
        """这一段现在什么样：``todo`` / ``text`` / ``done`` / ``missing``。

        ``text`` 是"文本那半有了、实质产物还要引擎侧渲染"，``missing`` 是"账说跑过、盘上没有"。
        这两种都必须跟 ``todo`` 分开说：合成一个"完成度百分比"就没人看得出**该去渲染、还是该去重跑**。

        与 :meth:`_done_before` 的关系：两者共用上面那两个原子，但**结论故意不同** ——
        ``_done_before`` 是"这一回跳过它吗"（要求账上写着 done，因为每段都要花钱、要等），
        这里是"面板上这一格显示什么"（产物在就算成了，哪怕账上没有记录）。
        别把两处合成一处：合了以后要么"手写的产物被判成没做"，
        要么"跑到一半的段被判成跑过了"，两个方向各错一边。
        """
        text_ok = self._artifact_ready(task)
        if text_ok and not task.needs_render:
            return MARK_DONE
        if text_ok:
            return MARK_TEXT
        return MARK_MISSING if self._recorded_done(ledger, task) else MARK_TODO

    def _done_before(self, state: dict[str, Any], task: StageTask) -> bool:
        """这一段上次跑完过、而且产物还在吗。

        **两个条件都要**：账上写了 done、盘上却没有产物（被删、被移走、写到一半断电），
        那就得重跑 —— 只看账会把一个空的阶段报成完成，而且此后再也不会补上。
        """
        return self._recorded_done(state.get("stages", {}), task) and self._artifact_ready(task)

    # ---- 上下文 ---------------------------------------------------------

    def _novel_excerpt(self) -> str:
        """原著摘录。读不动**当场报错** —— 静默给空串等于让模型凭空编一部剧。"""
        if self.novel is None:
            return "（这一步没挂原著：按下面已有的产物往下做）"
        try:
            text = self.novel.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as err:
            raise PipelineError(
                f"原著读不动（{self.novel}）：{err}。"
                "中文网文常见 GB18030；请先转成 UTF-8，或走面板的「管理小说」导入"
                "（它认得 GB18030，见 novels.decode_text）。"
            ) from err
        if len(text) <= NOVEL_EXCERPT_CHARS:
            return text
        return text[:NOVEL_EXCERPT_CHARS] + f"\n…（原文共 {len(text)} 字，此处只给开头）"

    def _upstream_blocks(self, task: StageTask) -> list[str]:
        """这一段之前已经落盘的那些产物，按阶段顺序排。"""
        blocks: list[str] = []
        for earlier in STAGE_TASKS:
            if earlier.code == task.code:
                break
            path = self.project / earlier.artifact
            if not path.is_file():
                continue
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if len(body) > UPSTREAM_EXCERPT_CHARS:
                body = body[:UPSTREAM_EXCERPT_CHARS] + "\n…（此处只给开头）"
            blocks.append(f"── {earlier.code} {earlier.name}：{earlier.artifact} ──\n{body}")
        return blocks

    def _prompts(
        self, task: StageTask, profile_prompt: str, novel_excerpt: str
    ) -> tuple[str, str]:
        """拼这一段的两段提示词：底座 + 该阶段的人设；再把上下文摆给模型。

        原著摘录由调用方先读好传进来（:meth:`_novel_excerpt`）。**不在这里读**是有意的：
        读不动要在**开跑之前**报出来，而不是跑到 S0 才发现 —— 那时前面的钱已经花了，
        而且失败会被记成「S0 没成」，把一个输入问题伪装成阶段问题。
        """
        system_prompt = f"{PIPELINE_SYSTEM_PROMPT}\n\n{profile_prompt}".strip()
        parts = [
            f"# 这一段：{task.code} {task.name}",
            f"归口：{task.owner}",
            f"要产出：{task.brief or '（本段没有写要做什么，见阶段表）'}",
            f"落点：{task.artifact}",
            f"目标集数：{self.episodes}",
        ]
        if task.needs_render:
            parts.append(
                "注意：这一步只产出提示词。真正的图/视频/音频由引擎侧渲染，"
                "所以你交出的必须是**能被别人照着执行**的提示词，不是一句「我会去做」的承诺。"
            )
        parts.append("\n## 原著\n" + novel_excerpt)
        blocks = self._upstream_blocks(task)
        if blocks:
            parts.append("\n## 上游产物\n" + "\n\n".join(blocks))
        parts.append(
            f"\n现在只写 {task.artifact} 的正文，从标题开始，不要写任何解释性的前后缀。"
        )
        return system_prompt, "\n".join(parts)

    def _check_report(self, task: StageTask, state: dict[str, Any]) -> str:
        """S7（合规）那一段不用模型：把体检实况写成人话。

        **这不是"合规审核"**：真正的合规判据由引擎侧的 gate 命令执行（``STAGE_SPECS`` 的
        ``gate`` 写着它在哪），宿主侧能负责的只有"落点齐不齐、哪一段有产物"。所以报告
        开头就把这一条写明 —— 一个叫"合规体检"的文件最容易被人当成"审过了"。
        """
        info = scan_project(str(self.project))
        lines = [
            "# 合规体检（宿主侧机械体检，不是合规审核）",
            "",
            "> 本文件由流水线的 S7 自动写出。**它不判断内容是否合规** —— 真正的判据由引擎侧",
            "> 的 gate 命令执行（位置写在 projects_spec.STAGE_SPECS 的 gate 字段里）。",
            "> 这里只回答一件事：每个阶段的产物到底在不在。",
            "",
            f"- 项目：{self.project}",
            f"- 文件总数（绕开 __pycache__）：{info.get('files')}",
            f"- 最近改动：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(info.get('mtime') or 0))}",
            "",
            "## 各阶段产物",
            "",
            "| 阶段 | 名字 | 文本产物 | 文本在不在 | 实质产物（图/视频/音频） |",
            "| --- | --- | --- | --- | --- |",
        ]
        for candidate in STAGE_TASKS:
            has_text = (self.project / candidate.artifact).is_file()
            record = state["stages"].get(candidate.code) or {}
            if candidate.needs_render:
                if candidate.check_exts:
                    target = "、".join(candidate.check_dirs) + "（" + "、".join(candidate.check_exts) + "）"
                else:
                    target = "、".join(candidate.check_dirs)
                render = f"待引擎侧渲染 → {target}"
            else:
                render = "—"
            text_cell = "有" if has_text else "**缺**"
            lines.append(
                f"| {candidate.code} | {candidate.name} | `{candidate.artifact}` | {text_cell} "
                f"| {render} |"
            )
        missing_dirs = info.get("missing") or []
        legacy = info.get("legacy") or []
        lines += ["", "## 落点与老结构", ""]
        if missing_dirs:
            lines.append(f"- **缺落点**（{len(missing_dirs)} 个）：" + "、".join(f"`{m}`" for m in missing_dirs))
        else:
            lines.append("- 落点齐全。")
        if legacy:
            lines.append(
                "- **还躺在 v1 位置的全剧级设定**（`project migrate` 会搬）："
                + "、".join(f"`{m}`" for m in legacy)
            )
        else:
            lines.append("- 没有 v1 老结构残留。")
        lines += [
            "",
            "## 结论",
            "",
            "宿主侧能做的都做完了；上面标着「待引擎侧渲染」的那几格**本流水线产不出**，"
            "它们要引擎侧运行时 + ComfyUI 工作流 + 模型权重。别把本文件当成发布许可。",
        ]
        return "\n".join(lines) + "\n"

    def _write_outline(self, text: str) -> str:
        """S0 的机器可读大纲：**已有就绝不动它**，模型没给合格 JSON 就明说没落盘。

        ``projects_spec.MIGRATIONS`` 的注释写着这条路径为什么敏感：它在老位置时建纲阶段
        读不到就会重写一份，静默覆盖人改过的大纲。所以这里的口径是：只补空缺，不覆盖；
        补不上就如实记一笔，让下游知道该读 md 而不是 JSON。
        """
        target = self.project / OUTLINE_JSON
        if target.is_file():
            return "已有机器可读大纲，**没动它**（不拿模型新生成的覆盖人改过的那份）"
        block = JSON_BLOCK_RE.search(text)
        if block is None:
            return "模型没给 ```json 块，机器可读大纲没落盘（下游直接读上面那份 md）"
        try:
            data = json.loads(block.group(1))
        except json.JSONDecodeError as err:
            return f"模型给的 json 块解不开（{err}），**没落盘**"
        if not isinstance(data, dict):
            return "模型给的 json 顶层不是对象，**没落盘**"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return f"机器可读大纲已落盘（{OUTLINE_JSON}）"

    # ---- 跑 -------------------------------------------------------------

    async def _emit(self, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        result = self.on_event(payload)
        if asyncio.iscoroutine(result):
            await result

    async def run(
        self,
        *,
        from_code: str | None = None,
        to_code: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """按顺序跑一段。**失败即停**（后面的段依赖前面的），并把原因原样带回。

        同一项目**同时只许一条**（见 :data:`RUNNING_PROJECTS`）：第二条直接拒绝，
        不是排队 —— 排队会在用户以为"点快了没反应"的时候悄悄再烧一遍模型调用。
        """
        key = str(self.project)
        if key in RUNNING_PROJECTS:
            raise PipelineError(
                f"这个项目已经有一条流水线在跑了（{key}）。两条同时跑会各写各的进度账，"
                "后写的把先写的盖掉，而模型调用是双份的；等它跑完再开。"
            )
        RUNNING_PROJECTS.add(key)
        try:
            return await self._run_stages(from_code=from_code, to_code=to_code, force=force)
        finally:
            RUNNING_PROJECTS.discard(key)

    async def _run_stages(
        self,
        *,
        from_code: str | None = None,
        to_code: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """真跑的正文。**加门在上面的** :meth:`run` —— 内部复用时不该把自己挡住。"""
        tasks = _slice_tasks(self.plan(), from_code, to_code)
        state = self.state()
        if state.get("project") not in (None, str(self.project)):
            raise PipelineError(
                f"状态账是另一个项目的（{state.get('project')}，当前 {self.project}）—— "
                "共用一份账会把两部的进度搅在一起。"
            )
        state.setdefault("stages", {})

        runner = self.runner
        owns_runner = False
        if runner is None:
            runner = LLMStageRunner(self.config)
            owns_runner = True
        # 原著先读一遍（读不动当场抛出，见 _prompts 的说明），七段共用这一份摘录。
        novel_excerpt = self._novel_excerpt()

        await self._emit(
            {
                "type": "pipeline",
                "phase": "start",
                "project": str(self.project),
                "stages": [task.code for task in tasks],
            }
        )
        outcomes: list[StageOutcome] = []
        try:
            for task in tasks:
                outcome = await self._run_one(task, state, runner, force, novel_excerpt)
                outcomes.append(outcome)
                if outcome.status == STATUS_FAILED:
                    break
        finally:
            if owns_runner:
                await runner.close()  # type: ignore[attr-defined]

        report = {
            "project": str(self.project),
            "novel": str(self.novel) if self.novel is not None else None,
            "state": STATE_REL,
            "ok": all(o.status != STATUS_FAILED for o in outcomes) and len(outcomes) == len(tasks),
            "ran": [o.code for o in outcomes],
            "not_ran": [task.code for task in tasks[len(outcomes):]],
            "render_required": [o.code for o in outcomes if o.render_pending],
            "stages": [o.to_json() for o in outcomes],
        }
        await self._emit({"type": "pipeline", "phase": "finished", **report})
        return report

    async def _run_one(
        self,
        task: StageTask,
        state: dict[str, Any],
        runner: StageRunner,
        force: bool,
        novel_excerpt: str,
    ) -> StageOutcome:
        started = time.monotonic()
        if not force and self._done_before(state, task):
            outcome = StageOutcome(
                code=task.code,
                name=task.name,
                status=STATUS_SKIPPED,
                agent_id=task.agent_id,
                artifact=task.artifact,
                needs_render=task.needs_render,
                seconds=time.monotonic() - started,
                note="上次跑过且产物还在（--force 可重跑）",
                render_lands=task.render_lands,
                render_note=task.render_note,
            )
            await self._emit({"type": "pipeline", "phase": "stage", **outcome.to_json()})
            return outcome

        await self._emit(
            {
                "type": "pipeline",
                "phase": "stage_start",
                "code": task.code,
                "name": task.name,
                "actor": task.actor,
            }
        )
        try:
            if task.agent_id:
                profile = self.catalog.get(task.agent_id)
                system_prompt, user_prompt = self._prompts(task, profile.prompt, novel_excerpt)
                try:
                    # 上限见 STAGE_TIMEOUT_SECONDS：非流式请求没有响应头之外的生命迹象，
                    # 超时不只是"放弃等待"，还会把这次 HTTP 请求取消掉（模型侧才松得开手）。
                    text = await asyncio.wait_for(
                        runner(task, system_prompt, user_prompt), timeout=self.stage_timeout
                    )
                except asyncio.TimeoutError:
                    raise PipelineError(
                        f"{task.code} {task.name} 超过单段上限 {self.stage_timeout:g} 秒还没回话"
                        "（请求是非流式的，这段时间里看不到任何中间输出）。"
                        f"要么把上限调大（构造参数 stage_timeout 或环境变量 {STAGE_TIMEOUT_ENV}），"
                        "要么给模型配上输出上限（COMFY_STUDIO_LLM_MAX_TOKENS）——"
                        "本地小模型收不住时会一直编下去。"
                    ) from None
                if not text.strip():
                    raise PipelineError("模型返回了空内容")
            else:
                text = self._check_report(task, state)
            target = self.project / task.artifact
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            note = ""
            if task.code == "S0":
                note = self._write_outline(text)
            if task.needs_render:
                pending = f"实质产物待引擎侧渲染（{'、'.join(task.check_dirs)}）"
                note = f"{note}；{pending}" if note else pending
            outcome = StageOutcome(
                code=task.code,
                name=task.name,
                status=STATUS_DONE,
                agent_id=task.agent_id,
                artifact=task.artifact,
                needs_render=task.needs_render,
                seconds=time.monotonic() - started,
                note=note,
                render_lands=task.render_lands,
                render_note=task.render_note,
            )
            state["stages"][task.code] = {
                "status": STATUS_DONE,
                "artifact": task.artifact,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "note": note,
            }
        except Exception as err:  # 记下来并停：后面的段依赖这一段，继续跑只会连环错
            outcome = StageOutcome(
                code=task.code,
                name=task.name,
                status=STATUS_FAILED,
                agent_id=task.agent_id,
                artifact=task.artifact,
                needs_render=task.needs_render,
                seconds=time.monotonic() - started,
                error=f"{type(err).__name__}: {err}",
                render_lands=task.render_lands,
                render_note=task.render_note,
            )
            state["stages"][task.code] = {
                "status": STATUS_FAILED,
                "artifact": task.artifact,
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "error": outcome.error,
            }
        self._save_state(state)
        await self._emit({"type": "pipeline", "phase": "stage", **outcome.to_json()})
        return outcome


def format_report(report: dict[str, Any]) -> str:
    """把报告写成人话（CLI 用）。**渲染缺口必须在最后再念一遍** —— 那是本流水线的边界。"""
    lines = [
        f"项目：{report['project']}",
        f"原著：{report['novel'] or '（没挂）'}",
        "",
        "  阶段   状态      谁做              产物",
        "  -----  --------  ----------------  ------------------------------------",
    ]
    marks = {STATUS_DONE: "✓", STATUS_SKIPPED: "·", STATUS_FAILED: "✖"}
    for stage in report["stages"]:
        actor = STAGE_TASK_BY_CODE[stage["code"]].actor
        lines.append(
            f"  {stage['code']}    {marks.get(stage['status'], '?')} {stage['status']:<7} "
            f"{actor:<16}  {stage['artifact']}"
        )
        for key in ("note", "error"):
            if stage.get(key):
                lines.append(f"         {key}：{stage[key]}")
    if report["not_ran"]:
        lines += ["", f"没跑（前面的段没成）：{'、'.join(report['not_ran'])}"]
    if report["render_required"]:
        lines += [
            "",
            "⚠️ 这几段的**实质产物**还没出，本流水线产不出它们："
            + "、".join(report["render_required"]),
            "   它们要引擎侧运行时 + ComfyUI 工作流 + 模型权重。文本提示词已经落盘，"
            "可照它去引擎侧（或可灵 / Seedance / 即梦那类平台）出片。",
        ]
        # 面板上这几段各带一枚「去出图」；命令行这边没有按钮，就把该装哪张图、出完该落在哪儿
        # 念出来 —— 认错图不会报错，只会出成另一张（同 STAGE_RENDER 的注释）。
        for stage in report["stages"]:
            lands = stage.get("render_lands") if stage.get("render_pending") else None
            if not lands:
                continue
            note = f"（{stage['render_note']}）" if stage.get("render_note") else ""
            uses = "、".join(f"{target} → {land}" for target, land in lands.items())
            lines.append(f"   {stage['code']} 用：{uses}{note}")
    lines += ["", f"状态账：{report['state']}"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 二、命令行：不经过桌面壳也能跑
# ─────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m comfy_studio.pipeline",
        description="从小说到视频：按 S0a–S7a 逐段产出。只产提示词与设定文本；"
                    "图 / 视频 / 音频要引擎侧渲染。",
    )
    parser.add_argument("--project", required=True, help="项目目录，或 projects/ 下的项目名")
    parser.add_argument("--novel", default=None, help="原著文本文件（.txt/.md，UTF-8）")
    parser.add_argument("--episodes", type=int, default=1, help="目标集数（默认 1）")
    parser.add_argument("--from", dest="from_code", default=None, help="从哪一段起（S0a–S7a）")
    parser.add_argument("--to", dest="to_code", default=None, help="到哪一段止（含）")
    parser.add_argument("--force", action="store_true", help="跑过的段也重跑")
    parser.add_argument("--plan", action="store_true", help="只印计划，不碰模型、不落盘")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。出错就**打到 stderr 并回非零**，不吞。"""
    args = _build_parser().parse_args(argv)
    try:
        pipeline = NovelToVideoPipeline(
            args.project, args.novel, episodes=args.episodes
        )
        tasks = _slice_tasks(pipeline.plan(), args.from_code, args.to_code)
    except PipelineError as err:
        print(f"错误：{err}", file=sys.stderr)
        return 2

    if args.plan:
        print(f"项目：{pipeline.project}")
        print(f"原著：{pipeline.novel or '（没挂）'}")
        print("")
        for task in tasks:
            flag = "（还要引擎侧渲染）" if task.needs_render else ""
            print(f"{task.code}  {task.name}  ← {task.actor}{flag}")
            print(f"     产出：{task.artifact}")
        return 0

    try:
        report = asyncio.run(
            pipeline.run(from_code=args.from_code, to_code=args.to_code, force=args.force)
        )
    except PipelineError as err:
        print(f"错误：{err}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover - 人是能按 Ctrl-C 的
        print("已中断（产物与状态账保留，下次接着跑）", file=sys.stderr)
        return 130
    print(format_report(report))
    return 0 if report["ok"] else 1


# ---- 对话里的那两张工具 ---------------------------------------------

#: 汇进工具表时的 server 名：工具在模型那里叫 ``pipeline__plan`` / ``pipeline__run``。
PIPELINE_SERVER = "pipeline"

#: 跑之前那次确认给的两个选项。**同意这一条逐字比**：答别的（用户自己敲一句"随便"、面板没接住、
#: 通道超时）都算没同意。这一步要按段调模型、动辄十几分钟，含糊默许是这里最贵的那种静默错误。
RUN_AGREE = "继续跑"
RUN_DECLINE = "先别跑"


@dataclass(frozen=True)
class _Spec:
    """一张流水线工具：工具名 + 说明与参数表（与 ``projects.py`` / ``review.py`` 里同形）。"""

    name: str
    description: str
    input_schema: dict[str, Any]


def plan_payload(pipeline: NovelToVideoPipeline) -> dict[str, Any]:
    """一部剧的计划 + 进度。**面板（``pipeline/plan``）与对话工具回的是同一份形状** ——
    形状分家就会冒出"面板上写着还差 S4、模型说已经跑完了"这种事，而它没有报错、也没人复现。

    **只读**：``plan`` 与 ``state`` 都不碰模型、不落盘。
    """
    tasks = pipeline.plan()
    state = pipeline.state()
    return {
        "project": str(pipeline.project),
        "novel": str(pipeline.novel) if pipeline.novel is not None else None,
        "stages": [task.to_json() for task in tasks],
        "state": state.get("stages", {}),
        "render_required": [task.code for task in tasks if task.needs_render],
    }


def state_payload(pipeline: NovelToVideoPipeline) -> dict[str, Any]:
    """进度账：哪一段跑过、产物是哪一份。同样**只读**，同样两个入口共用。"""
    state = pipeline.state()
    return {
        "project": str(pipeline.project),
        "version": state.get("version"),
        "updated": state.get("updated"),
        "stages": state.get("stages", {}),
    }


#: 工作台每一步的落点里，回话里带几个文件名。带全了没用（`08_STORYBOARDS/` 上千个文件），
#: 带零个又没法"点开最上面那一份"—— 面板要的是"这几份现在长什么样"。
STEP_FILES_SHOWN = 8


def _landing_index(tree: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``tree`` 里每个落点的读数，按相对路径索引，并捎上它那一格的标题。

    一格里的落点是分成全剧级/分集级两组摆的，这里**摊平**：工作台按步骤取落点，
    分组是"资料库"那一页的摆法，这里再分一次组只是把同一件事说两遍。
    """
    out: dict[str, dict[str, Any]] = {}
    for shelf in tree.get("shelves", ()):
        for item in shelf.get("dirs", ()):
            row = dict(item)
            row["shelf"] = shelf.get("title", "")
            out[str(item.get("rel"))] = row
    return out


def steps_payload(
    pipeline: NovelToVideoPipeline, library: ProjectLibrary
) -> dict[str, Any]:
    """八步工作台的一整份读数：**每一步现在什么状态、那一步的落点里有什么**。

    为什么把两个来源合在这一处，而不是让面板各取一次再自己拼：「第几步有料了」这件事
    只有同时看得见**阶段状态**（状态账 + 产物文件）与**落点文件**（项目目录）才答得出来，
    而这两样分别在流水线与项目库里。让面板去拼，等于在界面层再写一份"什么算做完"的规则，
    那份规则迟早与 :meth:`NovelToVideoPipeline._done_before` 分家 —— 而分家时谁都不报错。

    每一步的 ``state`` 是四选一，**不合并成"完成度百分比"**：

    * ``done`` —— 这一步的阶段都成了（没有阶段的一步：落点里有产物就算成）；
    * ``partial`` —— 有料但不齐（含"只有文本、实质产物还要引擎侧渲染"那种）；
    * ``empty`` —— 阶段都没跑、落点也是空的；
    * 加一个阶段级的 ``missing``：账上记着跑过、产物却不在（被删了或被挪了）。

    ``current`` 是**第一个还没做完的步骤** —— 面板拿它当"你现在该看哪一步"，
    不自己数一遍（数一遍就会与这里的判据分家）。

    ⚠️ **只读**：不碰模型、不落盘，与 :func:`plan_payload` 同一个保证。
    """
    tasks = {task.code: task for task in pipeline.plan()}
    ledger = pipeline.state().get("stages", {})
    try:
        tree = library.tree(pipeline.project.name)
    except Exception as err:  # ProjectsError：项目不在库根下 / 项目根没探测到
        raise PipelineError(f"读不了项目落点：{err}") from err
    index = _landing_index(tree)
    names = {profile.id: profile.name for profile in pipeline.catalog.scan().profiles}

    steps: list[dict[str, Any]] = []
    for spec in WORKBENCH_STEPS:
        stages: list[dict[str, Any]] = []
        for code in step_stages(spec.key):
            task = tasks.get(code)
            if task is None:
                # WORKBENCH_STEPS 与阶段表对不上。step_gaps() 已钉住这条，这里是它
                # 万一漏了时的第二道：裸 KeyError 只会印出一个 'S4'，看不出是**哪两张表**分家了。
                raise PipelineError(
                    f"阶段 {code} 挂在步骤 {spec.key} 上，却不在计划里；"
                    "WORKBENCH_STEPS 与 STAGE_SPECS/STAGE_TASKS 需要对齐。"
                )
            stages.append(
                {
                    **task.to_json(),
                    # 四种归宿由流水线判（账 + 产物，见 stage_mark）；面板只负责照念。
                    "state": pipeline.stage_mark(ledger, task),
                    "agent_name": names.get(task.agent_id, ""),
                    "how": stage_how(code),
                }
            )
        landings: list[dict[str, Any]] = []
        for rel in spec.landings:
            item = index.get(rel) or {}
            files = list(item.get("files") or ())
            # 预置空表**不算进度**：刚建完项目那几格（06_对白/、07_素材归档/、05_流程/）
            # 里躺着的是建项目写下的空模板。把它们算进来的失效模式很难看 ——
            # 用户一步没跑，工作台已经显示"这几步有料了"。
            seeds = sum(1 for row in files if row.get("seed"))
            landings.append(
                {
                    "rel": rel,
                    "title": rel.rsplit("/", 1)[-1],
                    "shelf": item.get("shelf", ""),
                    "scope": item.get("scope", ""),
                    "exists": bool(item.get("exists")),
                    # 预置表排在后面：面板先摆真产物，空模板垫底并标出来。
                    "files": (
                        [row for row in files if not row.get("seed")]
                        + [row for row in files if row.get("seed")]
                    )[:STEP_FILES_SHOWN],
                    "count": max(0, int(item.get("count") or 0) - seeds),
                    "seed_count": seeds,
                    "truncated": bool(item.get("truncated")),
                }
            )
        count = sum(item["count"] for item in landings)
        marks = {item["state"] for item in stages}
        if not stages:
            # 没有机器阶段的一步（视觉风格）：产物在就算做完 —— 它没有别的判据。
            step_state = MARK_DONE if count > 0 else MARK_EMPTY
        elif marks == {MARK_DONE}:
            step_state = MARK_DONE
        elif marks == {MARK_TODO} and count == 0:
            step_state = MARK_EMPTY
        else:
            # 有料但不齐：``text``（待引擎侧渲染）、``missing``（产物不见了）、
            # 一部分阶段成了另一部分没跑 —— 三种都落这一格，面板按各自的签分着说。
            step_state = MARK_PARTIAL
        steps.append(
            {
                "key": spec.key,
                "name": spec.name,
                "goal": spec.goal,
                "note": spec.note,
                "needs": list(spec.needs),
                "stages": stages,
                "landings": landings,
                "count": count,
                "seed_count": sum(item["seed_count"] for item in landings),
                "state": step_state,
            }
        )

    finished = {step["key"] for step in steps if step["state"] == MARK_DONE}
    for step in steps:
        # ``needs`` 与 ``blocked_by`` 的差别就是"上游"与"上游里还欠哪几个"：
        # 面板只显示欠的那几个，否则每一步都挂着四五个上游名，看着像全都堵着。
        step["blocked_by"] = [key for key in step["needs"] if key not in finished]
        step["ready"] = not step["blocked_by"]
    return {
        "project": str(pipeline.project),
        "name": pipeline.project.name,
        "novel": str(pipeline.novel) if pipeline.novel is not None else None,
        "linked_novel": tree.get("novel", ""),
        "gaps": list(step_gaps()),
        "order": list(STEP_ORDER),
        "current": next((step["key"] for step in steps if step["state"] != MARK_DONE), ""),
        "steps": steps,
        "render_required": [task.code for task in tasks.values() if task.needs_render],
    }


def _tool_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """把工具参数挡成一套统一的 kwargs（两张工具回同样的键，少一层分叉）。

    只挡**形状**（必填、类型）；"S9 算不算阶段"交给流水线自己判 —— 它那边已经有一份
    "有效的有：S0、S1…"，在这儿再抄一份就是两份规则，早晚分家。
    """
    project = arguments.get("name")
    if not isinstance(project, str) or not project.strip():
        raise PipelineError("name 必须有（项目名或项目目录的路径）")
    novel = arguments.get("novel")
    if novel is not None and not isinstance(novel, str):
        raise PipelineError("novel 必须是字符串（原文库里的名字）")
    episodes = arguments.get("episodes", DEFAULT_EPISODES)
    if isinstance(episodes, bool) or not isinstance(episodes, int) or episodes < 1:
        raise PipelineError(f"集数必须是正整数，收到 {episodes!r}")
    picked: list[str | None] = []
    for key in ("from", "to"):
        value = arguments.get(key)
        if value is not None and not isinstance(value, str):
            raise PipelineError(f"{key} 必须是阶段代码（S0a–S7a）")
        picked.append(value)
    force = arguments.get("force", False)
    if not isinstance(force, bool):
        raise PipelineError("force 必须是布尔值")
    return {
        "project": project.strip(),
        "novel": novel,
        "episodes": episodes,
        "from_code": picked[0],
        "to_code": picked[1],
        "force": force,
    }


def _ok_result(payload: Any) -> dict[str, Any]:
    """把结果做成 MCP 的返回形状（与 ``projects.py`` 里那两张只读工具一致）。"""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}],
        "isError": False,
    }


def _error_result(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


#: 两张工具，分工是"看"与"跑"。
#:
#: **为什么计划可以随便看、跑之前却要人点头**：S0a–S7a 是一串会写盘、按段调模型、动辄十几分钟的
#: 动作。面板上那是用户自己按的键；对话里模型不能替人按（与 ``projects.py`` 那句"不许替人建
#: 项目"同一条线）。所以 ``run`` **自己**弹一次确认，且只有用户明确选了 :data:`RUN_AGREE`
#: 才开跑 —— 不靠提示词里写一句"记得先问用户"。
PIPELINE_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="plan",
        description=(
            "看这部小说「从小说到视频」要走的 S0a–S7a：每段谁做（哪个智能体）、文本产出落在哪个目录、"
            "哪几段跑完文本还要引擎侧渲染（图 / 视频 / 音频本流水线产不出）、以及现在跑到哪一步了。"
            "**不调模型、不写文件**，看一眼不花钱。"
            "用户问“要几步”“现在到哪了”“还差什么”“接着往下做要做什么”时用它；"
            "要真去跑那是 run，别拿这张当执行。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "项目名（projects__list 给的那个），或项目目录的路径",
                },
                "novel": {
                    "type": "string",
                    "description": "可选：原著在原文库里的名字；给了才看得出这次挂的是哪本书",
                },
            },
            "required": ["name"],
        },
    ),
    _Spec(
        name="run",
        description=(
            "真去跑这部小说的生产流水线：按 S0a–S7a 顺序推进，每段的文本产物写进项目目录，"
            "跑到“要渲染”的那几段就停下并如实说还缺渲染，不假装成片已经出来了。"
            "**这一步会按段调用模型、往项目目录里写文件、可能十几分钟**；"
            "它自己会先弹一次确认（把要跑几段、哪几段要渲染、会跳过哪些列给用户），"
            "用户没点头就不跑 —— 你不用再自己问一遍，但也**不要在用户只是打听进度时**调它。"
            "只想看计划或进度用 plan。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "项目名（projects__list 给的那个）"},
                "novel": {
                    "type": "string",
                    "description": "可选：原著在原文库里的名字（novels 那边那个名字）；不挂原著就不给",
                },
                "episodes": {
                    "type": "integer",
                    "description": f"可选：按几集拆分，不给就按默认的 {DEFAULT_EPISODES} 集",
                },
                "from": {
                    "type": "string",
                    "description": "可选：从哪一段开始（S0a–S7a），不给就从没跑过的第一段开始",
                },
                "to": {"type": "string", "description": "可选：跑到哪一段为止（含这一段）"},
                "force": {
                    "type": "boolean",
                    "description": "可选：跑过、产物还在的段也重跑；默认跳过它们（少花钱）",
                },
            },
            "required": ["name"],
        },
    ),
)


@dataclass(frozen=True)
class PipelineServerConfig:
    """与 ``McpServerConfig`` 同形的极小配置：这张工具表只需要一个名字。"""

    name: str = PIPELINE_SERVER


class PipelineClient:
    """鸭子型 MCP client：形状与 :class:`~comfy_studio.mcp.client.McpStdioClient` 一致，
    好直接汇进 :class:`~comfy_studio.mcp.McpHub` 的工具表（项目 / 本地文件那几个也是这么挂的）。

    ``review`` 是"跑之前得有人点头"那条通道（:class:`~comfy_studio.review.ReviewChannel`）：
    **没接上就不跑** —— 这个场合没人能点头，而这一步要花的钱与时间都不是能默许的。
    ``config_provider`` 取"当前生效的那套模型配置"，宿主把它接成 ``StudioHost._session_config``，
    于是对话里跑的与面板上点的是同一份配置；不接就走 ``LLMConfig.from_env()``（命令行那条路）。
    ``runner`` 是给测试的注入口（与 :class:`NovelToVideoPipeline` 那个参数一个意思）：测试要能在
    **不联网、不花钱**的前提下把这条路走完。
    """

    def __init__(
        self,
        *,
        novels: NovelLibrary | None = None,
        review: ReviewChannel | None = None,
        config_provider: Callable[[], LLMConfig] | None = None,
        runner: StageRunner | None = None,
        config: PipelineServerConfig | None = None,
    ) -> None:
        self.novels = novels
        self.review = review
        self.config_provider = config_provider
        self.runner = runner
        self.config = config if config is not None else PipelineServerConfig()

    @property
    def alive(self) -> bool:
        """没有子进程：这张表一直都在。"""
        return True

    def stderr_tail(self) -> str:
        """没有子进程，也就没有它的 stderr。"""
        return ""

    async def start(self) -> None:
        """没有子进程要拉。"""

    async def close(self) -> None:
        """没有连接要关；模型客户端是每次调用现建的（见 :meth:`_pipeline`）。"""

    async def list_tools(self) -> list[McpTool]:
        return [
            McpTool(
                server=self.config.name,
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
            for spec in PIPELINE_TOOLS
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        """跑一张。失败一律回 ``isError`` 文本交给模型；工具名不对是协议层的事，照旧抛。

        取消只在"等人点头"那一步生效：真开跑之后各段的模型请求不是流式的，中途掐断会留下
        半份产物与一条对不上的状态账 —— 那比让它跑完更糟。所以开跑之后本工具不再看 ``cancel``
        （要停就由面板关掉这次对话）。
        """
        spec = next((item for item in PIPELINE_TOOLS if item.name == name), None)
        if spec is None:
            known = ", ".join(item.name for item in PIPELINE_TOOLS)
            raise McpError(f"流水线工具表里没有 {name}；可用: {known}")
        try:
            args = _tool_args(dict(arguments or {}))
            result = (
                plan_payload(self._pipeline(args, config=None))
                if spec.name == "plan"
                else await self._run(args, cancel)
            )
        except (PipelineError, NovelsError, ReviewError) as err:
            return _error_result(str(err))
        return _ok_result(result)

    async def _run(self, args: dict[str, Any], cancel: CancelToken | None) -> dict[str, Any]:
        pipeline = self._pipeline(args, config=self._config())
        await self._confirm(pipeline, args, cancel)
        return await pipeline.run(
            from_code=args["from_code"], to_code=args["to_code"], force=args["force"]
        )

    def _pipeline(self, args: dict[str, Any], *, config: LLMConfig | None) -> NovelToVideoPipeline:
        """按工具参数造一台流水线。**不跑** —— 跑不跑由调用方决定。"""
        path: str | None = None
        if args["novel"] is not None:
            if self.novels is None:
                raise PipelineError(
                    "这个场合没挂原文目录，没法按名字取原文；要么别传 novel，要么先配好原著库"
                )
            path = resolve_novel(self.novels, args["novel"])
        return NovelToVideoPipeline(
            args["project"],
            path,
            runner=self.runner,
            config=config,
            episodes=args["episodes"],
        )

    def _config(self) -> LLMConfig | None:
        """当前生效的那套模型配置；宿主没接取配置的路就走环境变量那份。"""
        return None if self.config_provider is None else self.config_provider()

    async def _confirm(
        self, pipeline: NovelToVideoPipeline, args: dict[str, Any], cancel: CancelToken | None
    ) -> None:
        """跑之前把人拉进来点头；没点头就抛，**一个字节都不写**。"""
        if self.review is None:
            raise PipelineError(
                "这次对话里没人能确认（没接审核通道），流水线不跑。"
                "可以去面板上按「跑这一段」；或者在能弹确认的对话里再让我跑。"
            )
        planned = _slice_tasks(pipeline.plan(), args["from_code"], args["to_code"])
        renders = [task.code for task in planned if task.needs_render]
        records = pipeline.state().get("stages", {})
        ran = [
            task.code
            for task in planned
            if isinstance(records.get(task.code), dict)
            and records[task.code].get("status") == STATUS_DONE
        ]
        summary = (
            f"「{pipeline.project.name}」的流水线：{planned[0].code} → {planned[-1].code}，"
            f"共 {len(planned)} 段，每段一次模型调用"
            + (
                f"，其中 {'、'.join(renders)} 跑完文本还要引擎侧渲染（本流水线产不出图 / 视频 / 音频）"
                if renders
                else ""
            )
            + (f"；账上已经跑过 {'、'.join(ran)}，产物还在的会跳过" if ran else "")
            + "。要现在开跑吗？"
        )
        answer = await self.review.ask(summary, [RUN_AGREE, RUN_DECLINE], cancel=cancel)
        if answer != RUN_AGREE:
            raise PipelineError(
                f"用户没同意跑（他答的是 {answer!r}），这次一个字节都没写。"
                f"等他明确说「{RUN_AGREE}」再跑。"
            )


if __name__ == "__main__":  # pragma: no cover - CLI 入口
    raise SystemExit(main())


__all__ = [
    "JSON_BLOCK_RE",
    "LLMStageRunner",
    "NOVEL_EXCERPT_CHARS",
    "OUTLINE_JSON",
    "PIPELINE_SERVER",
    "PIPELINE_SYSTEM_PROMPT",
    "PIPELINE_TOOLS",
    "PipelineClient",
    "PipelineError",
    "PipelineServerConfig",
    "RUN_AGREE",
    "RUN_DECLINE",
    "STAGE_AGENT",
    "STAGE_ARTIFACT",
    "STAGE_BRIEF",
    "STAGE_TASKS",
    "STAGE_TASK_BY_CODE",
    "STATE_REL",
    "STATE_VERSION",
    "STATUS_DONE",
    "STATUS_FAILED",
    "STATUS_SKIPPED",
    "STEP_FILES_SHOWN",
    "NovelToVideoPipeline",
    "StageOutcome",
    "StageRunner",
    "StageTask",
    "UPSTREAM_EXCERPT_CHARS",
    "format_report",
    "main",
    "plan_payload",
    "state_payload",
    "steps_payload",
]
