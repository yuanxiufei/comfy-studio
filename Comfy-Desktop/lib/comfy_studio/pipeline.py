"""从小说到视频：把「一剧一目录」的生产阶段串成一条**能跑、能断点续跑**的流水线。

**为什么要有这一层**：``projects_spec.STAGE_SPECS`` 早写清了 S0–S7「谁做 · 落哪 · 怎么跑 ·
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
from .projects import DEFAULT_EPISODES
from .projects_spec import (
    PROJECT_DIRS,
    STAGE_BY_CODE,
    STAGE_ORDER,
    resolve_project,
    scan_project,
)
from .review import ReviewChannel, ReviewError

#: 状态账的版本号。形状变了就加它 —— 老账读不动时**明确报错**，不猜着读。
STATE_VERSION = 1

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
    "S0": "script",
    "S1": "costume",
    "S2": "costume",
    "S3": "asset",
    "S4": "storyboard",
    "S5": "video",
    "S6": "voice",
    "S7": "",
}

#: 阶段 → (文本产物相对路径, 是否还有一半得引擎侧渲染)。
#: 路径的父目录**必须**是 ``PROJECT_DIRS`` 里的一项（也就是该阶段的 ``landings``），
#: 由 ``tests/test_pipeline.py`` 机械核对 —— 落点写错的失效模式是产物掉在面板看不见的地方。
STAGE_ARTIFACT: dict[str, tuple[str, bool]] = {
    "S0": ("00_PROJECT/01_剧本/00_总纲/分集大纲与三表.md", False),
    "S1": ("00_PROJECT/02_资产索引/资产总表.md", False),
    "S2": ("00_PROJECT/04_交付与出图/出图提示词_S2.md", True),
    "S3": ("06_EXPRESSIONS/表情与动作提示词.md", True),
    "S4": ("08_STORYBOARDS/分镜表.md", False),
    "S5": ("09_SHOTS/视频提示词.md", True),
    "S6": ("11_AUDIO/声音提示词.md", True),
    "S7": ("10_CONSISTENCY/合规体检.md", False),
}

#: 阶段 → 交给模型的一句话（"这一段要产出什么"）。
#: 不写在 ``projects_spec`` 里：那里的 ``gate`` 只写判据**在哪**（见它自己的 ⚠️），
#: 而这里是**要模型产出什么**，是提示词的一部分，会随人设一起改。
STAGE_BRIEF: dict[str, str] = {
    "S0": (
        "读原著（或它的开头），产出三样：① 分集大纲（每集一句话钩子 + 集末卡点）"
        "② 人物三表（人物表 / 关系表 / 势力表）③ 角色小传。"
        "正文之后另起一个 ```json 代码块给出机器可读的分集骨架，"
        '顶层必须是对象，至少含 "集数" 与 "角色" 两个键；'
        "给不出就别给这个块，不要编一个形状不对的 JSON。"
    ),
    "S1": (
        "按 S0 的大纲产出资产总表：世界观、角色、服装、道具、场景各自的清单与视觉要点。"
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
    """一段活：谁做 · 要产出什么 · 落在哪 · 还差哪一半得引擎侧渲染。"""

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


def _build_tasks() -> tuple[StageTask, ...]:
    """把三张静态表拧成任务清单。**顺序 = ``STAGE_ORDER``**，不另排一遍。"""
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
            )
        )
    extra = (set(STAGE_AGENT) | set(STAGE_ARTIFACT) | set(STAGE_BRIEF)) - set(STAGE_ORDER)
    if extra:
        raise PipelineError(
            f"这几张表里有不属于 S0–S7 的键：{'、'.join(sorted(extra))}；"
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

    def _done_before(self, state: dict[str, Any], task: StageTask) -> bool:
        """这一段上次跑完过、而且产物还在吗。

        **两个条件都要**：账上写了 done、盘上却没有产物（被删、被移走、写到一半断电），
        那就得重跑 —— 只看账会把一个空的阶段报成完成，而且此后再也不会补上。
        """
        record = state["stages"].get(task.code)
        if not isinstance(record, dict) or record.get("status") != STATUS_DONE:
            return False
        return (self.project / task.artifact).is_file()

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
    lines += ["", f"状态账：{report['state']}"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 二、命令行：不经过桌面壳也能跑
# ─────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m comfy_studio.pipeline",
        description="从小说到视频：按 S0–S7 逐段产出。只产提示词与设定文本；"
                    "图 / 视频 / 音频要引擎侧渲染。",
    )
    parser.add_argument("--project", required=True, help="项目目录，或 projects/ 下的项目名")
    parser.add_argument("--novel", default=None, help="原著文本文件（.txt/.md，UTF-8）")
    parser.add_argument("--episodes", type=int, default=1, help="目标集数（默认 1）")
    parser.add_argument("--from", dest="from_code", default=None, help="从哪一段起（S0–S7）")
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
            raise PipelineError(f"{key} 必须是阶段代码（S0–S7）")
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
#: **为什么计划可以随便看、跑之前却要人点头**：S0–S7 是一串会写盘、按段调模型、动辄十几分钟的
#: 动作。面板上那是用户自己按的键；对话里模型不能替人按（与 ``projects.py`` 那句"不许替人建
#: 项目"同一条线）。所以 ``run`` **自己**弹一次确认，且只有用户明确选了 :data:`RUN_AGREE`
#: 才开跑 —— 不靠提示词里写一句"记得先问用户"。
PIPELINE_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="plan",
        description=(
            "看这部小说「从小说到视频」要走的 S0–S7：每段谁做（哪个智能体）、文本产出落在哪个目录、"
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
            "真去跑这部小说的生产流水线：按 S0–S7 顺序推进，每段的文本产物写进项目目录，"
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
                    "description": "可选：从哪一段开始（S0–S7），不给就从没跑过的第一段开始",
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
    "NovelToVideoPipeline",
    "StageOutcome",
    "StageRunner",
    "StageTask",
    "UPSTREAM_EXCERPT_CHARS",
    "format_report",
    "main",
    "plan_payload",
    "state_payload",
]
