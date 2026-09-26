"""跨会话的长期记忆：用户说过的偏好与稳定事实，落盘留着下次还认得。

**为什么需要它**：会话历史（:class:`~comfy_studio.agent.AgentSession`）只活在宿主进程的
内存里，宿主一退出就没了。于是「我喜欢方形构图」「我这台是 24G 的 4090」「别再用那个
采样器」这类话，每次开面板都得重说一遍；刚沉淀下来的 skill、上一个否掉计划的原因，
下一轮也不认。这里把它们收成一份**用户级的**记忆：

* ``memory__remember`` —— 记一条（一条只说一件事），返回它的 id；
* ``memory__recall`` —— 查：不传关键词就列最近记的，传了就只回匹配的；
* ``memory__forget`` —— 删掉记错或过时的（id 从 recall 拿）。

除了这三张工具，宿主还会把 :meth:`MemoryStore.digest` 拼进**系统提示词**（见
:func:`comfy_studio.agent.loop.compose_system_prompt`）——模型一开口就知道自己记得什么，
不必先查一遍；素材大了才靠 ``memory__recall`` 挑。因此这份记忆**每轮都会重算**：
这一轮刚记住的事，下一轮就在提示词里。

**为什么落在宿主的用户目录，而不是 ComfyUI 检出里**：记忆是「这个人的」，不是「这个
引擎安装的」。检出和它下面的 ``.venv`` 都是可以随时删掉重建的（``npm run setup`` 就是
重来一遍），记忆不该跟着一起没；同一台机器上换一个 ComfyUI 安装，用户的偏好也还是
那一份。默认位置按操作系统惯例取用户数据目录（Windows ``%APPDATA%``、macOS
``~/Library/Application Support``、Linux ``$XDG_DATA_HOME``），要换地方用
``--memory-dir`` 或环境变量 ``COMFY_STUDIO_MEMORY_DIR``。

**为什么是 JSON 而不是数据库**：条数上限 :data:`MAX_ENTRIES`、整个文件几十 KB，
读一次、改一次、整份原子替换就够，不需要引入任何新依赖（本仓的纪律：不引新第三方包）。

**读不了就报错，不静默重建**：文件坏了（不是 JSON、版本不认识、形状不对）时宁可让
调用方看到 ``MemoryStoreError``，也不悄悄从空开始——那会变成"助手莫名其妙把记性丢了"，
比报错更难查。真要从头开始，就由用户自己把文件删掉（错误信息里写着路径）。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .cancel import CancelToken
from .mcp import McpError, McpTool

#: 汇进工具表时用的 server 名。
MEMORY_SERVER = "memory"

#: 落盘文件名（放在记忆目录下）。
DEFAULT_MEMORY_FILENAME = "memory.json"

#: 文件格式版本。形状变了就 +1，旧文件会被显式拒绝而不是硬读。
STORE_VERSION = 1

#: 一条记忆最多多少字。记忆是"一句话的偏好"，不是文档——真长的东西该写进 skill 或文件。
MAX_TEXT_CHARS = 500

#: 一条记忆最多几个标签 / 每个标签多长。
MAX_TAGS = 5
MAX_TAG_CHARS = 32

#: 记忆条数上限。满了就明确拒绝，让模型/用户先删掉不再需要的，而不是无限膨胀。
MAX_ENTRIES = 200

#: ``recall`` 默认/最多回几条。
DEFAULT_RECALL_LIMIT = 20
MAX_RECALL_LIMIT = 200

#: 拼进系统提示词时，最多带几条、最多占多少字符。宁可列不下让模型去查，
#: 也不要把提示词撑爆——每轮都要带上它。
PROMPT_MAX_ENTRIES = 20
PROMPT_MAX_CHARS = 1200

#: 记忆目录名（拼在系统数据目录下面）。
APP_DIR_NAME = "comfy-studio"


class MemoryStoreError(RuntimeError):
    """记忆层面的错误：参数不对、文件读不了、条数满了、要删的 id 不存在。

    故意不叫 ``MemoryError`` —— 那是 Python 内建的（内存分配失败），
    同名会让 `except` 抓错东西。
    """


def memory_home() -> Path:
    """默认的记忆目录：按操作系统惯例取**用户级**数据目录。

    环境变量优先（``APPDATA`` / ``LOCALAPPDATA`` / ``XDG_DATA_HOME``），
    没有就退回各自的惯例路径；Windows 上 ``APPDATA`` 缺失时按 ``~/AppData/Roaming``
    的惯例拼——这是标准布局，不是本机专有路径。
    """
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
        return root / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_DIR_NAME


def _now() -> str:
    """ISO 8601（秒级，UTC）。落盘用，别依赖本地时区。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _key(text: str) -> str:
    """判重用的一把钥匙：空白折叠 + 大小写不敏感。

    只用来判断"是不是同一条"，落盘存的仍是用户/模型给的原话（去掉首尾空白）。
    """
    return " ".join(text.split()).casefold()


def _clean_text(raw: Any) -> str:
    if not isinstance(raw, str) or raw.strip() == "":
        raise MemoryStoreError("text 必须是非空字符串")
    text = raw.strip()
    if len(text) > MAX_TEXT_CHARS:
        raise MemoryStoreError(
            f"一条记忆最多 {MAX_TEXT_CHARS} 字，现在有 {len(text)} 字："
            "只记一句能当结论用的话，长内容该写成 skill 或者存成文件"
        )
    return text


def _clean_tags(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise MemoryStoreError("tags 必须是字符串数组")
    tags: list[str] = []
    for item in raw:
        if not isinstance(item, str) or item.strip() == "":
            raise MemoryStoreError("tags 里每一项都必须是非空字符串")
        tag = item.strip()
        if len(tag) > MAX_TAG_CHARS:
            raise MemoryStoreError(f"单个标签最多 {MAX_TAG_CHARS} 字，给的是 {len(tag)} 字: {tag}")
        if tag not in tags:  # 去重但保留顺序，别让模型重复写同一个标签
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise MemoryStoreError(f"一条记忆最多 {MAX_TAGS} 个标签，现在有 {len(tags)} 个")
    return tuple(tags)


def _as_limit(raw: Any) -> int:
    if raw is None:
        return DEFAULT_RECALL_LIMIT
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise MemoryStoreError(f"limit 必须是整数，实际是 {type(raw).__name__}")
    if raw < 1 or raw > MAX_RECALL_LIMIT:
        raise MemoryStoreError(f"limit 要在 1~{MAX_RECALL_LIMIT} 之间，给的是 {raw}")
    return raw


def _as_id(raw: Any) -> str:
    if not isinstance(raw, str) or raw.strip() == "":
        raise MemoryStoreError("id 必须是非空字符串（用 memory_recall 拿）")
    return raw.strip()


@dataclass(frozen=True)
class MemoryEntry:
    """一条记忆：一句话 + 可选标签 + 记下来的时间。"""

    id: str
    text: str
    tags: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "tags": list(self.tags), "created_at": self.created_at}

    @classmethod
    def from_json(cls, raw: Any, where: Any) -> MemoryEntry:
        if not isinstance(raw, dict):
            raise MemoryStoreError(f"记忆文件里有一条不是对象（{where}）")
        entry_id = raw.get("id")
        text = raw.get("text")
        if not isinstance(entry_id, str) or entry_id == "":
            raise MemoryStoreError(f"记忆文件里有条目缺 id（{where}）")
        if not isinstance(text, str) or text.strip() == "":
            raise MemoryStoreError(f"记忆文件里 {entry_id} 的 text 不是非空字符串（{where}）")
        raw_tags = raw.get("tags") or []
        if not isinstance(raw_tags, list) or any(not isinstance(t, str) for t in raw_tags):
            raise MemoryStoreError(f"记忆文件里 {entry_id} 的 tags 不是字符串数组（{where}）")
        created = raw.get("created_at")
        if not isinstance(created, str) or created == "":
            # 时间缺了不影响使用（只是排序/展示），但如实补一个空值而不是编一个时间。
            created = ""
        return cls(id=entry_id, text=text, tags=tuple(raw_tags), created_at=created)


#: 拼进系统提示词的「怎么用记忆」那几条。放在这里而不是 agent 的默认人设里：
#: 只有挂了记忆工具（``--memory``）时这段才成立。
MEMORY_PROMPT_RULES = (
    "关于长期记忆：你有一套跨会话的长期记忆（memory__remember / memory__recall / memory__forget），"
    "它存在用户这台机器上，下次打开面板你还认得。\n"
    "什么时候记：用户说“记住…”“以后都…”时；或者他讲了一件以后还用得上的事"
    "（惯用的模型与 skill、常跑的尺寸与步数、不喜欢的风格、这台机器什么显卡）——用 memory__remember 记下，"
    "一条只说一件事，别记流水账，也别记这一次的临时要求。\n"
    "什么时候查：要贴他的习惯又拿不准时，先 memory__recall 查一下再决定，别凭印象猜；"
    "列出来的那份只是最近的一些，查全了要用它。\n"
    "记错或过时了用 memory__forget 删掉（id 从 recall 结果里拿）。记完在回答里点一句，让他有机会纠正。"
)


class MemoryStore:
    """一份落盘的记忆。目录由调用方给（``--memory-dir`` / 环境变量 / :func:`memory_home`）。"""

    def __init__(
        self,
        directory: str | os.PathLike[str],
        filename: str = DEFAULT_MEMORY_FILENAME,
    ) -> None:
        self.directory = Path(directory).expanduser()
        self.path = self.directory / filename
        self._entries: list[MemoryEntry] = []
        self._loaded = False

    # ---- 读盘 / 落盘 -----------------------------------------------------

    def load(self) -> tuple[MemoryEntry, ...]:
        """读一次盘（幂等）。文件不存在 = 还没记过，这不是错误。"""
        if self._loaded:
            return tuple(self._entries)
        if not self.path.exists():
            self._entries = []
            self._loaded = True
            return ()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            raise MemoryStoreError(
                f"记忆文件读不了（{self.path}）：{err}。"
                "请修好它，或者把它删掉再启动——现在这样读，助手会把旧的记性丢掉"
            ) from err
        if not isinstance(raw, dict):
            raise MemoryStoreError(f"记忆文件顶层应该是对象（{self.path}）")
        version = raw.get("version")
        if version != STORE_VERSION:
            raise MemoryStoreError(
                f"记忆文件版本不认识（{self.path}：version={version!r}，本版只认 {STORE_VERSION}）"
            )
        entries = raw.get("entries")
        if not isinstance(entries, list):
            raise MemoryStoreError(f"记忆文件里缺 entries 数组（{self.path}）")
        self._entries = [MemoryEntry.from_json(item, self.path) for item in entries]
        self._loaded = True
        return tuple(self._entries)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"version": STORE_VERSION, "entries": [e.to_json() for e in self._entries]}
        # 先写同目录的临时文件再原子替换：写到一半断了也不会留下半截 JSON。
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def entries(self) -> tuple[MemoryEntry, ...]:
        """全部记忆，按记下来的先后（新的在后）。"""
        self._ensure_loaded()
        return tuple(self._entries)

    @property
    def count(self) -> int:
        return len(self.entries)

    def _next_id(self) -> str:
        """下一个 id：``m-<n>``。只有形如 ``m-<数字>`` 的才参与计数。"""
        top = 0
        for entry in self._entries:
            if entry.id.startswith("m-") and entry.id[2:].isdigit():
                top = max(top, int(entry.id[2:]))
        return f"m-{top + 1}"

    # ---- 三个动作 --------------------------------------------------------

    def remember(self, text: str, tags: Sequence[str] | None = None) -> dict[str, Any]:
        """记一条。内容与已有的某条完全相同（忽略空白与大小写）时不重复记。"""
        clean = _clean_text(text)
        tag_list = _clean_tags(tags)
        self._ensure_loaded()
        key = _key(clean)
        for entry in self._entries:
            if _key(entry.text) == key:
                return {"entry": entry, "duplicate": True}
        if len(self._entries) >= MAX_ENTRIES:
            raise MemoryStoreError(
                f"记忆已经满了（{MAX_ENTRIES} 条）：先用 memory__recall 看看哪些不再需要，"
                "用 memory__forget 删掉，再记新的"
            )
        entry = MemoryEntry(id=self._next_id(), text=clean, tags=tag_list, created_at=_now())
        self._entries.append(entry)
        self._save()
        return {"entry": entry, "duplicate": False}

    def recall(self, query: str | None = None, limit: int | None = None) -> dict[str, Any]:
        """查记忆，新的在前。``query`` 给了就只回文本或标签里含它的那些（忽略大小写）。

        只读：命中不写盘、不改任何计数，省得"查一下"这种动作也产生副作用。
        """
        if query is not None and not isinstance(query, str):
            raise MemoryStoreError("query 必须是字符串")
        cap = _as_limit(limit)
        self._ensure_loaded()
        needle = query.strip().lower() if query and query.strip() else None
        matched: list[MemoryEntry] = []
        for entry in reversed(self._entries):
            if needle is not None:
                haystack = " ".join((entry.text, *entry.tags)).lower()
                if needle not in haystack:
                    continue
            matched.append(entry)
        return {
            "count": len(self._entries),
            "matched": len(matched),
            "returned": min(len(matched), cap),
            "query": needle,
            "entries": [e.to_json() for e in matched[:cap]],
            "file": str(self.path),
        }

    def forget(self, memory_id: str) -> dict[str, Any]:
        """删掉一条；id 不存在就报错（并列出最近几条的 id，好让模型自己纠正）。"""
        target = _as_id(memory_id)
        self._ensure_loaded()
        for index, entry in enumerate(self._entries):
            if entry.id == target:
                self._entries.pop(index)
                self._save()
                return {"entry": entry.to_json(), "count": len(self._entries)}
        recent = ", ".join(e.id for e in self._entries[-5:])
        tail = f"；最近的是 {recent}" if recent else ""
        raise MemoryStoreError(f"没有 id 为 {target} 的记忆（共 {len(self._entries)} 条{tail}）")

    # ---- 系统提示词 ------------------------------------------------------

    def digest(self) -> str:
        """拼进系统提示词的那一段：怎么用记忆 + 已经记住的事。

        每轮 ask 都会重算（见 :meth:`~comfy_studio.agent.AgentSession.ask`），
        所以刚记下的那条下一轮就在里面。列不下时如实说明还有多少条，让模型去 recall。
        """
        lines = [MEMORY_PROMPT_RULES]
        entries = list(reversed(self.entries))  # 新的在前
        if not entries:
            lines.append("目前还没记住任何事。")
            return "\n".join(lines)

        listed: list[str] = []
        used = 0
        for entry in entries[:PROMPT_MAX_ENTRIES]:
            line = f"- [{entry.id}] {entry.text}"
            if entry.tags:
                line += f"（标签: {', '.join(entry.tags)}）"
            if listed and used + len(line) > PROMPT_MAX_CHARS:
                break
            listed.append(line)
            used += len(line)
        lines.append(f"以下是已经记住的事（共 {len(entries)} 条，这里列最新的 {len(listed)} 条）：")
        lines.extend(listed)
        left = len(entries) - len(listed)
        if left > 0:
            lines.append(f"（另有 {left} 条没有列出来，需要时用 memory__recall 查。）")
        return "\n".join(lines)


@dataclass(frozen=True)
class _Spec:
    """一张记忆工具：MCP 工具名 + 说明与参数表。"""

    name: str
    description: str
    input_schema: dict[str, Any]


#: 三张工具。描述里写清"什么时候该用/不该用"，因为这张表是模型判断的唯一依据。
MEMORY_TOOLS: tuple[_Spec, ...] = (
    _Spec(
        name="remember",
        description=(
            "把用户的偏好、或以后还用得上的事实记下来，跨会话留着（存在他这台机器上，下次打开还认得）。"
            "该记的：他说“记住…”“以后都…”的；惯用的模型 / skill / 尺寸 / 步数；明确说不喜欢的做法；"
            "这台机器的硬件情况。不该记的：这一次任务里的临时要求、跑出来的一串结果、"
            "任何敏感信息（密钥、口令、隐私内容）。一条只说一件事，别把几件事塞进一条。"
            "内容与已有的某条完全相同（忽略空白与大小写）时不会记两条，返回 duplicate=true 与那条的 id。"
            "返回的 id 留好：以后要改口、要删，用 memory__forget 指定它。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": f"要记的那句话，一句一件（最多 {MAX_TEXT_CHARS} 字）",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"可选：便于以后检索的标签，最多 {MAX_TAGS} 个",
                },
            },
            "required": ["text"],
        },
    ),
    _Spec(
        name="recall",
        description=(
            "查长期记忆。不传 query 就列最近记下的（那份大概已经随系统提示词给过你了）；"
            "传 query 则只看文本或标签里含这个词的。拿不准用户以前的习惯时先查再决定，别凭印象猜。"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "可选：关键词（例如 尺寸 / 显存 / 采样器）"},
                "limit": {
                    "type": "integer",
                    "description": f"最多回几条，默认 {DEFAULT_RECALL_LIMIT}（上限 {MAX_RECALL_LIMIT}）",
                },
            },
        },
    ),
    _Spec(
        name="forget",
        description=(
            "删掉一条记错、过时或用户明确要求别记了的记忆。id 从 memory__recall 的结果里拿；"
            "id 不存在会报错并列出最近几条的 id。删是不可逆的，删之前先确认自己拿对了那条。"
        ),
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "要删的记忆 id（形如 m-3）"}},
            "required": ["id"],
        },
    ),
)


def _validate(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """参数在本地先挡一道：形状不对就别去动文件。"""
    if name == "remember":
        kwargs: dict[str, Any] = {"text": args.get("text")}
        tags = args.get("tags")
        if tags is not None:
            kwargs["tags"] = tags
        return kwargs
    if name == "recall":
        query = args.get("query")
        if query is not None and not isinstance(query, str):
            raise MemoryStoreError("query 必须是字符串")
        return {"query": query, "limit": args.get("limit")}
    if name == "forget":
        return {"memory_id": args.get("id")}
    raise McpError(f"记忆工具表里没有 {name}")


@dataclass(frozen=True)
class MemoryServerConfig:
    """与 :class:`~comfy_studio.mcp.McpServerConfig` 同形的极小配置：这里只需要名字。"""

    name: str = MEMORY_SERVER


class MemoryClient:
    """鸭子型 MCP client：形状与 :class:`~comfy_studio.mcp.client.McpStdioClient` 一致，
    好直接汇进 :class:`~comfy_studio.mcp.McpHub` 的工具表（与画布 / 本地文件同一个做法）。
    """

    def __init__(self, store: MemoryStore, config: MemoryServerConfig | None = None) -> None:
        self.store = store
        self.config = config if config is not None else MemoryServerConfig()

    @property
    def alive(self) -> bool:
        return True

    def stderr_tail(self) -> str:
        return ""

    async def start(self) -> None:
        """没有子进程要拉：这张工具表一直都在。"""

    async def close(self) -> None:
        """没有连接要关；记忆是文件，随时可以再读。"""

    async def list_tools(self) -> list[McpTool]:
        return [
            McpTool(
                server=self.config.name,
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
            for spec in MEMORY_TOOLS
        ]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        """跑一个记忆动作。

        ``cancel`` 收下但不用：这几个动作都是**一次本地读写**（几十 KB 的 JSON），
        没有可中断的长等待。

        失败（参数不对、文件坏了、条数满了、id 不存在）一律回 ``isError`` 文本交给模型，
        与本地文件那几张一致——模型常常能自己改对（换个 id、先删几条）再试一次。
        """
        spec = next((s for s in MEMORY_TOOLS if s.name == name), None)
        if spec is None:
            known = ", ".join(s.name for s in MEMORY_TOOLS)
            raise McpError(f"记忆工具表里没有 {name}；可用: {known}")
        try:
            kwargs = _validate(name, dict(arguments or {}))
            if name == "remember":
                outcome = self.store.remember(**kwargs)
                entry: MemoryEntry = outcome["entry"]
                result: dict[str, Any] = {
                    "id": entry.id,
                    "text": entry.text,
                    "tags": list(entry.tags),
                    "duplicate": outcome["duplicate"],
                    "count": self.store.count,
                    "file": str(self.store.path),
                }
            elif name == "recall":
                result = self.store.recall(**kwargs)
            else:
                result = self.store.forget(**kwargs)
        except MemoryStoreError as err:
            return {"content": [{"type": "text", "text": str(err)}], "isError": True}
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "isError": False,
        }


__all__ = [
    "APP_DIR_NAME",
    "DEFAULT_MEMORY_FILENAME",
    "DEFAULT_RECALL_LIMIT",
    "MAX_ENTRIES",
    "MAX_RECALL_LIMIT",
    "MAX_TAGS",
    "MAX_TAG_CHARS",
    "MAX_TEXT_CHARS",
    "MEMORY_PROMPT_RULES",
    "MEMORY_SERVER",
    "MEMORY_TOOLS",
    "PROMPT_MAX_CHARS",
    "PROMPT_MAX_ENTRIES",
    "STORE_VERSION",
    "MemoryClient",
    "MemoryEntry",
    "MemoryStoreError",
    "MemoryServerConfig",
    "MemoryStore",
    "memory_home",
]
