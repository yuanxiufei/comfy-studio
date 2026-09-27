"""智能体目录：面板上那个「换个人来干活」的清单。

这里说的**智能体**就是一整套人设里的**角色段**：底座规则（``agent/loop.py`` 的
``BASE_SYSTEM_PROMPT`` —— 这套工作台的硬规矩、工具怎么用、什么时候先问用户）不动，
角色段只讲清「这次是谁在干活、产出该长什么样」。两段由 ``compose_system_prompt``
拼成一条系统提示词，所以换智能体**不动工具表、也不动对话历史**：它就是换一句话
（历史里从来不含 system，见 :mod:`comfy_studio.history`）。

两条来源：

* **内置**：:data:`BUILTIN_PROFILES`。写的是**提要** —— 这个角色负责哪一类活、产出该
  是什么形态、信息不够时怎么办。**具体风格、数量、平台与措辞一概不写死**：那些是用户
  当场的活（"出几个分镜""要不要电影感"），写进代码只会变成一份谁都不敢改的教条，
  也会跟用户手上的完整配置文档对不上。想要更细的版本，就放一份自己的文件。
* **用户自己的文件**：目录（默认是工作台数据目录下的 ``agents/``，见 ``--agents-dir``）
  里的 ``*.md``，一份文件一个智能体。认识这个形状::

      # 分镜导演助手              ← 第一个一级标题是名字（没有就用文件名）
      > 把一段故事拆成可拍摄的分镜   ← 紧随其后的一句引用是说明（可选，只取第一行）

      这里往下都是人设正文，原样拼进系统提示词。

  为什么是 md 不是某种配置文件：用户手上的智能体配置本来就是 markdown 文档，拷进来
  就能用，不必先过一道转换器。文件名（去掉 ``.md``）就是它的 id，也是 ``agent/agent``
  里那个值。

几条取舍：

* **读不了的单个文件不让整份清单失败**：它作为一条带 ``error`` 的 :class:`AgentProblem`
  报出来（面板画成一条读不了的选项），其余照旧可用 —— 一个手改坏的文件把所有智能体
  都从下拉里抹掉，比多一行红字糟得多。目录整体读不了（没有读权限、路径上是个文件）
  另走 ``error``：那时清单里只剩内置的。
* **正文为空的文件算坏文件**，不悄悄当成"通用助手"：人设空着的时候 ``AgentSession``
  本来就要报错（见 ``agent/loop.py`` 的 ``_system_text``），与其等到聊天时才发现，
  不如在清单里就说明白。
* **内置不可被覆盖**：用户文件与内置重名就是一条 ``error``（改个文件名即可）。否则
  "我把内置那份改了怎么没生效"会变成一件要靠猜的事。
* **id 从文件名来，不另设一套命名规则**：目录里重名本来就不可能（同一个目录里不会有
  两个同名文件），所以不需要额外去重逻辑。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

#: 用户智能体文件放在数据目录下的哪个子目录。与 :data:`comfy_studio.history.SESSION_SUBDIR`
#: 平行：两个都是"工作台在你用户目录里那份数据"的一部分（``memory.json`` 是平铺的那个）。
AGENTS_SUBDIR = "agents"

#: 用户智能体文件的扩展名。
USER_SUFFIX = ".md"

#: 没选中任何智能体时用的那一个：底座规则原样，一个字的角色段都不插。
GENERAL_AGENT_ID = "general"

#: 说明行最多显示多少字符（面板下拉一行放不下更长的）。
SUMMARY_CHARS = 60


class AgentCatalogError(RuntimeError):
    """智能体目录层面的错误：文件读不了、形状不对、要的那个不在清单里。"""


@dataclass(frozen=True)
class AgentProfile:
    """清单里的一项。``prompt`` 就是拼进系统提示词的那段角色文本（通用助手是空串）。"""

    #: 稳定标识：内置的是写死的英文 id，用户文件的是文件名（去掉 ``.md``）。
    id: str
    #: 面板下拉里显示的名字。
    name: str
    #: 一句话说明（可能为空）。
    summary: str
    #: 角色段正文；空串表示"不加任何角色段"。
    prompt: str
    #: 是不是内置的。
    builtin: bool = False
    #: 用户文件的文件名（内置的是空串）—— 出问题时把文件名指给用户看。
    file: str = ""


@dataclass(frozen=True)
class AgentProblem:
    """一份读不了/不合规的用户文件。``file`` 是文件名，``error`` 原样给用户看。"""

    file: str
    error: str


@dataclass(frozen=True)
class AgentListing:
    """一次扫描的结果：能用的 + 读不了的。``error`` 是目录整体的毛病（那时只剩内置）。"""

    profiles: tuple[AgentProfile, ...]
    problems: tuple[AgentProblem, ...] = ()
    error: str | None = None


#: 内置智能体。只写提要：说清职责与产出形态，数量/风格/平台交给用户当场定。
#: 名字与用户手上的完整配置文档对得上，方便他对号入座；内容刻意比文档短得多。
BUILTIN_PROFILES: tuple[AgentProfile, ...] = (
    AgentProfile(
        id=GENERAL_AGENT_ID,
        name="通用助手",
        summary="不加任何角色段，就是这套工作台的默认助手",
        prompt="",
        builtin=True,
    ),
    AgentProfile(
        id="storyboard",
        name="分镜导演助手",
        summary="把故事拆成可拍摄的分镜，再给到画面提示词",
        prompt=(
            "当前角色：分镜导演。把小说、剧本、梗概或一句话创意变成可拍摄的分镜：先给整段的分镜方案，"
            "再逐镜拆解景别、机位、运动、光线与氛围，最后给出能直接落进图像生成的画面提示词。"
            "分镜数量、视觉风格、画幅与语言按用户要求；用户没说就按你判断合适的量来做，并说明你的取舍。"
            "镜头与提示词要具体到能直接执行，不要用空泛形容词堆砌。"
        ),
        builtin=True,
    ),
    AgentProfile(
        id="script",
        name="剧本创作",
        summary="把故事改编成节奏紧凑的短剧剧本",
        prompt=(
            "当前角色：短剧编剧。把原始故事、小说、梗概或半成品剧本改造成节奏紧凑的短剧剧本："
            "场次与台词齐备，重视开场钩子、冲突升级与收尾的悬念；需要时一并给人物设定与后续分集走向。"
            "篇幅、集数与更新节奏按用户要求。改稿时保留用户的原意，只动该动的地方并说明改了什么。"
        ),
        builtin=True,
    ),
    AgentProfile(
        id="costume",
        name="漫剧服化道",
        summary="人物造型、服装、道具与场景的视觉设定",
        prompt=(
            "当前角色：服化道设计。按用户给的叙事或人物设定产出造型、服装、道具与场景的视觉方案，"
            "并从世界观出发保持它们之间的连续性：时代、地域、阶层、色彩语言要能对得上。"
            "产出以可直接用于图像生成的中英双语提示词为主；用户要图就用工具出图。"
            "缺的设定先按世界观补全，并标明哪些是你的补全，不要默默改掉用户已经写明的东西。"
        ),
        builtin=True,
    ),
    AgentProfile(
        id="asset",
        name="角色道具资产库",
        summary="角色/道具的标准化资产与三视图，前后一致可复用",
        prompt=(
            "当前角色：角色与道具资产设定。把一句自然语言设定整理成标准化、可复用的资产："
            "先补全缺的信息（外貌、服装、材质、配色、装备），再给出可复用的资产提示词与设定说明。"
            "做角色三视图时，正面、侧面、背面必须是同一个角色：发型、服装、配色、材质要对得上，"
            "并突出面部与材质细节。字段与命名沿用用户习惯，不要另发明一套。"
        ),
        builtin=True,
    ),
    AgentProfile(
        id="voice",
        name="调音大师班",
        summary="人物声线、环境氛围与道具音效的声音提示词",
        prompt=(
            "当前角色：声音设计。把人物形象、场景、道具、剧情与情绪转成可直接喂给配音、音效与音乐"
            "生成模型的声音提示词：人物声线（音色、年龄感、气息、颗粒感、情绪张力、语速、停顿）、"
            "环境氛围（空间、混响、材质、动态），以及道具 Foley 与特殊音效。"
            "信息不足时按设定补全并说明补了什么；输出以能直接复制使用为准，不要写分析过程。"
        ),
        builtin=True,
    ),
    AgentProfile(
        id="lyrics",
        name="歌词创作",
        summary="歌词、段落结构与适配的音乐风格提示词",
        prompt=(
            "当前角色：歌词与歌曲创作。按用户给的主题、情绪、语言、曲风与参考，产出完整歌词"
            "（含段落结构与记忆点）与适配的风格提示词；需要时补上标题、编曲配器与 MV 氛围，"
            "让成品能直接复制进音乐生成工具使用。语言与曲风按用户要求；用户给的信息很少时主动补全"
            "并说明补了什么，不要反过来追问一大堆参数。"
        ),
        builtin=True,
    ),
)


def _plain_summary(text: str) -> str:
    """把一行说明压成下拉里放得下的样子：去掉 markdown 的强调记号，超长就截断。"""
    flat = " ".join(text.replace("**", "").replace("`", "").split())
    if len(flat) <= SUMMARY_CHARS:
        return flat
    return flat[:SUMMARY_CHARS] + "…"


def _parse_markdown(text: str, fallback_name: str) -> tuple[str, str, str]:
    """从一份 md 里读 (名字, 说明, 人设正文)。

    三块的位置固定：开头的 ``# 名字``、紧随其后的引用块（只取第一行当说明）、剩下的正文。
    名字与说明都可以没有；正文是不是空的由调用方判断（空正文算坏文件）。
    """
    lines = text.splitlines()
    index = 0
    while index < len(lines) and lines[index].strip() == "":
        index += 1
    name = fallback_name
    if index < len(lines) and lines[index].lstrip().startswith("# "):
        name = lines[index].lstrip()[2:].strip() or fallback_name
        index += 1
    summary = ""
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped.startswith(">"):
            quoted = stripped.lstrip(">").strip()
            if quoted and not summary:
                summary = _plain_summary(quoted)
            index += 1
        elif stripped == "":
            index += 1
        else:
            break
    body = "\n".join(lines[index:]).strip()
    return name, summary, body


def _profile_from_file(path: Path) -> AgentProfile:
    """把一份用户文件读成一项。读不了或形状不对就抛 :class:`AgentCatalogError`（原样给用户看）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise AgentCatalogError(f"读不了：{err}") from err
    name, summary, body = _parse_markdown(text, path.stem)
    if body == "":
        raise AgentCatalogError("文件里只有标题/说明，没有人设正文 —— 正文才是这个智能体的人设")
    return AgentProfile(
        id=path.stem, name=name, summary=summary, prompt=body, builtin=False, file=path.name
    )


class AgentCatalog:
    """一份智能体清单：内置的 + 用户目录里的。

    ``directory`` 给 None 表示"没有用户目录"，清单里就只剩内置那几项（直接构造
    :class:`comfy_studio.server.StudioHost` 的调用方与单测走这条）。
    """

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        self.directory = Path(directory).expanduser() if directory is not None else None

    def scan(self) -> AgentListing:
        """重新扫一遍目录。

        每次调用都读盘：用户随时可以往里丢一份新文件或改一份，不必重启宿主 —— 与
        :class:`comfy_studio.skills.SkillCatalog` 的 ``refresh`` 是同一个理由。
        """
        profiles = list(BUILTIN_PROFILES)
        taken = {profile.id for profile in profiles}
        problems: list[AgentProblem] = []
        if self.directory is None or not self.directory.exists():
            # 没配目录、或还没往里放过文件：都不是错误，内置那几项照用。
            return AgentListing(profiles=tuple(profiles))
        if not self.directory.is_dir():
            return AgentListing(
                profiles=tuple(profiles), error=f"智能体目录不是目录（{self.directory}）"
            )
        try:
            paths = sorted(self.directory.glob(f"*{USER_SUFFIX}"))
        except OSError as err:
            return AgentListing(
                profiles=tuple(profiles), error=f"读智能体目录失败（{self.directory}）：{err}"
            )
        for path in paths:
            try:
                profile = _profile_from_file(path)
            except AgentCatalogError as err:
                problems.append(AgentProblem(file=path.name, error=str(err)))
                continue
            if profile.id in taken:
                problems.append(
                    AgentProblem(
                        file=path.name,
                        error=f"id {profile.id!r} 和已有的智能体重名；改个文件名就行",
                    )
                )
                continue
            taken.add(profile.id)
            profiles.append(profile)
        return AgentListing(profiles=tuple(profiles), problems=tuple(problems))

    def get(self, agent_id: str) -> AgentProfile:
        """按 id 取一项。不在清单里就报错，并把清单里有的 id 报出来 —— 手输时好对得上。"""
        listing = self.scan()
        for profile in listing.profiles:
            if profile.id == agent_id:
                return profile
        known = "、".join(profile.id for profile in listing.profiles)
        raise AgentCatalogError(f"没有叫 {agent_id!r} 的智能体；清单里有：{known}")


__all__ = [
    "AGENTS_SUBDIR",
    "BUILTIN_PROFILES",
    "GENERAL_AGENT_ID",
    "SUMMARY_CHARS",
    "USER_SUFFIX",
    "AgentCatalog",
    "AgentCatalogError",
    "AgentListing",
    "AgentProblem",
    "AgentProfile",
]
