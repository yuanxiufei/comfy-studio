"""智能体目录：面板上那个「换个人来干活」的清单。

这里说的**智能体**就是一整套人设里的**角色段**：底座规则（``agent/loop.py`` 的
``BASE_SYSTEM_PROMPT`` —— 这套工作台的硬规矩、工具怎么用、什么时候先问用户）不动，
角色段只讲清「这次是谁在干活、产出该长什么样」。两段由 ``compose_system_prompt``
拼成一条系统提示词，所以换智能体**不动工具表、也不动对话历史**：它就是换一句话
（历史里从来不含 system，见 :mod:`comfy_studio.history`）。

三条来源：

* **内置**：:data:`BUILTIN_PROFILES`。**只剩「通用助手」一项** —— 它不带任何角色段，就是
  这套工作台的出厂行为。角色的正文都搬进了下面两条的**文件**里：人设不写在代码里，代码里
  也就不会多出一份要跟文档同步的副本（"出几个分镜""要不要电影感"这类事一概不由代码说了算）。
* **随包预置**：:data:`PRESET_AGENTS` 那几份完整规格（落在 :data:`PRESET_DIR` 的 ``*.md``）。
  成品人设，正文**整份**读进来当角色段 —— 它们本来的用途就是整份塞进 System Prompt（见各份
  开头的「用途」），不是提要。选中哪个才带哪个。
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
* **代码内置的不可被覆盖**：用户文件与内置（也就是「通用助手」）重名是一条 ``error``
  （改个文件名即可）。否则"我把内置那份改了怎么没生效"会变成一件要靠猜的事。
* **随包预置可以被覆盖**：用户文件与预置 **id 相同**时就地顶掉它（不报错，位置也不动）。
  预置是"默认底稿"，用户手上那份才是他要的 —— 想改哪一项，就写个同 id 的文件丢进
  ``--agents-dir``，面板里那一项当场换成他的。
* **预置读不了只报那一条**：``file`` 写成 ``presets/<文件名>``，好让人分得清"包里的东西
  坏了"与"我自己写的文件有问题"。预置全读不出来时，清单里还剩通用助手与用户自己的文件。
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

#: 随包预置的成品人设放在哪：与本文件同级的 ``presets/``。
#: 从 :data:`__file__` 推、不认工作目录 —— 桌面壳起宿主时 cwd 是它自己的安装目录，跟包在
#: 哪没关系（``run-studio.mjs`` 起进程时也不改 cwd）。
PRESET_DIR = Path(__file__).resolve().parent / "presets"


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
    #: 是不是随包带来的（代码内置 + 随包预置）；False = 用户目录里的文件。
    builtin: bool = False
    #: 这个名字从哪来：用户文件的文件名，或预置的 ``presets/<文件名>``；代码内置的是空串。
    #: 出问题时把文件名指给用户看（面板也据此画出"读不了"的那几行）。
    file: str = ""


@dataclass(frozen=True)
class AgentProblem:
    """一份读不了/不合规的用户文件。``file`` 是文件名，``error`` 原样给用户看。"""

    file: str
    error: str


@dataclass(frozen=True)
class AgentListing:
    """一次扫描的结果：能用的 + 读不了的。``error`` 是用户目录整体的毛病
    （那时清单里只剩内置与预置）。"""

    profiles: tuple[AgentProfile, ...]
    problems: tuple[AgentProblem, ...] = ()
    error: str | None = None


#: 代码里内置的智能体。**只剩「通用助手」**：不带任何角色段，就是这套工作台的出厂行为。
#:
#: 从前这里还放着几个角色的"提要"（一段话的职责与产出形态）。那些角色现在由
#: :data:`PRESET_AGENTS` 带着**完整规格**随包预置 —— 同一件事不在两处各存一份，也就没有
#: "代码那份跟文档对不上"这回事。通用助手留在代码里，是因为它**不是**某个人设：它就是
#: "不加角色段"这个默认值本身。
BUILTIN_PROFILES: tuple[AgentProfile, ...] = (
    AgentProfile(
        id=GENERAL_AGENT_ID,
        name="通用助手",
        summary="不加任何角色段，就是这套工作台的默认助手",
        prompt="",
        builtin=True,
    ),
)


#: 随包预置的成品智能体：``(id, 下拉显示名, 一句说明, 包内文件名)``。
#:
#: 与 :data:`BUILTIN_PROFILES` 的分工是"正文从哪来"：内置把整段人设写在代码里，预置把
#: **整份规格文档**放在 :data:`PRESET_DIR` 里、一字不改地读进来当角色段。那些文档是给人看、
#: 也能整份搬到别的平台的完整人设（身份、工作流、输出规范、示例），在代码里再誊一遍既会
#: 走样，也会变成第二份要同步的副本。
#:
#: 这里的名字与说明**不**从文档里读：这几份的一级标题带着「完整迁移配置」这类**用途**
#: 标记（那是文件名与标题的约定），直接拿来当下拉项又长又乱；标题下面那段引用块也时有时无
#: （``AI剧本创作`` 与 ``AI资产库角色道具`` 两份紧跟标题的就是二级标题）。
#: 面板上显示成什么、与文档里写了什么，是两件事 —— 要改的也只是前者。
#:
#: id 沿用从前那几个内置项的 id：谁之前选过其中一个，现在选中的还是同一项，只是角色段从
#: "一段提要"换成了完整规格。正文体量见 ``presets/README.md``（每份 2.6–4.9 万字符；
#: 选中哪个才带哪个，但那一轮每一轮都带）。
PRESET_AGENTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "storyboard", "分镜导演助手", "把故事拆成可拍摄的分镜，再给到画面提示词",
        "分镜导演助手_完整迁移配置.md",
    ),
    (
        "script", "剧本创作", "把故事改编成节奏紧凑的连载剧集剧本",
        "AI剧本创作_完整迁移配置.md",
    ),
    (
        "video", "视频生成", "把分镜写成可投产的视频提示词与生成脚本，多镜衔接不崩坏",
        "AI视频生成_完整迁移配置.md",
    ),
    (
        "costume", "服化道设计", "人物造型、服装、道具与场景的视觉设定",
        "AI服化道智能体_完整迁移配置.md",
    ),
    (
        "asset", "角色道具资产库", "角色/道具的标准化资产与三视图，前后一致可复用",
        "AI资产库角色道具_完整迁移配置.md",
    ),
    (
        "voice", "调音大师班", "人物声线、环境氛围与道具音效的声音提示词",
        "调音大师班_完整迁移配置.md",
    ),
    (
        "lyrics", "歌词创作", "歌词、段落结构与适配的音乐风格提示词",
        "Suno歌词大师_完整迁移配置.md",
    ),
)


def _read_presets(directory: Path) -> tuple[list[AgentProfile], list[AgentProblem]]:
    """把随包预置读成清单项。读不了的那份单列成一条 problem，其余照旧可用。

    预置是**随包内容**：包被裁掉、搬坏，或者 :data:`PRESET_AGENTS` 里的文件名写错时，它就
    读不出来。处置口径与用户文件读不了时一致 —— 只报那一条，不让整份清单跟着塌（通用助手
    与用户自己的文件都还在）。``file`` 写成 ``presets/<文件名>``，好让人一眼看出毛病出在
    包里、不在自己的目录里。
    """
    profiles: list[AgentProfile] = []
    problems: list[AgentProblem] = []
    for agent_id, name, summary, filename in PRESET_AGENTS:
        shown = f"{directory.name}/{filename}"
        try:
            prompt = (directory / filename).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as err:
            problems.append(AgentProblem(file=shown, error=f"读不了：{err}"))
            continue
        if prompt == "":
            problems.append(
                AgentProblem(file=shown, error="文件是空的 —— 这个智能体的人设正文没了")
            )
            continue
        profiles.append(
            AgentProfile(
                id=agent_id, name=name, summary=summary, prompt=prompt, builtin=True, file=shown
            )
        )
    return profiles, problems


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
    """一份智能体清单：内置的 + 随包预置的 + 用户目录里的。

    ``directory`` 给 None 表示"没有用户目录"，清单里就只剩内置与预置（直接构造
    :class:`comfy_studio.server.StudioHost` 的调用方与单测走这条）。``presets`` 给 None
    表示"一份预置都不装"：测"没有预置时是什么样"走这条。
    """

    def __init__(
        self,
        directory: str | os.PathLike[str] | None = None,
        presets: str | os.PathLike[str] | None = PRESET_DIR,
    ) -> None:
        self.directory = Path(directory).expanduser() if directory is not None else None
        #: 随包预置目录；None = 不装预置（见 :data:`PRESET_AGENTS`）。
        self.presets = Path(presets).expanduser() if presets is not None else None

    def scan(self) -> AgentListing:
        """重新扫一遍。

        每次调用都读盘：用户随时可以往里丢一份新文件或改一份，不必重启宿主 —— 与
        :class:`comfy_studio.skills.SkillCatalog` 的 ``refresh`` 是同一个理由。预置那份
        也照读：它是随包内容、本不会变，但"用户手改了包内那份"与"文件被搬走"都该当场看见。
        """
        profiles: list[AgentProfile] = list(BUILTIN_PROFILES)
        blocked = {profile.id for profile in profiles}  # 代码内置：谁都不许顶
        problems: list[AgentProblem] = []
        # id → 它在清单里的位置，供"顶掉"用（用户文件顶预置；预置顶不了内置）。
        placed: dict[str, int] = {}
        if self.presets is not None:
            preset_profiles, preset_problems = _read_presets(self.presets)
            problems.extend(preset_problems)
            for profile in preset_profiles:
                placed[profile.id] = len(profiles)
                profiles.append(profile)
        if self.directory is None or not self.directory.exists():
            # 没配目录、或还没往里放过文件：都不是错误，内置与预置照用 —— 但预置自己读不了
            # 的那几条得如实带出来（以前这几个早退分支不带 problems，那时 problems 必然为空，
            # 有了预置就不一定了）。
            return AgentListing(profiles=tuple(profiles), problems=tuple(problems))
        if not self.directory.is_dir():
            return AgentListing(
                profiles=tuple(profiles),
                problems=tuple(problems),
                error=f"智能体目录不是目录（{self.directory}）",
            )
        try:
            paths = sorted(self.directory.glob(f"*{USER_SUFFIX}"))
        except OSError as err:
            return AgentListing(
                profiles=tuple(profiles),
                problems=tuple(problems),
                error=f"读智能体目录失败（{self.directory}）：{err}",
            )
        for path in paths:
            try:
                profile = _profile_from_file(path)
            except AgentCatalogError as err:
                problems.append(AgentProblem(file=path.name, error=str(err)))
                continue
            if profile.id in blocked:
                # 代码内置的（也就是「通用助手」）不能被顶掉：重名是一条错误（改个文件名
                # 就行），不是静默覆盖。"我把内置那份改了怎么没生效"不该靠猜。
                problems.append(
                    AgentProblem(
                        file=path.name,
                        error=f"id {profile.id!r} 和内置的智能体重名；改个文件名就行",
                    )
                )
                continue
            if profile.id in placed:
                # 随包预置可以被顶掉：预置是"默认底稿"，用户手上那份才是他要的。就地替换，
                # 位置不动 —— 换一份自己的文件不该让下拉里的次序跳一下。
                profiles[placed[profile.id]] = profile
                continue
            placed[profile.id] = len(profiles)
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
    "PRESET_AGENTS",
    "PRESET_DIR",
    "SUMMARY_CHARS",
    "USER_SUFFIX",
    "AgentCatalog",
    "AgentCatalogError",
    "AgentListing",
    "AgentProblem",
    "AgentProfile",
]
