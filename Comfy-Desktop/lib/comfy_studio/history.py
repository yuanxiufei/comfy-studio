"""跨宿主重启的对话存档：把"说过的话"落盘，重开桌面还接得上。

与 :mod:`comfy_studio.memory` 的分工要说清，两者都落盘但记的不是一回事：

* ``memory`` 记**事实**（"我喜欢方形构图"、"这台是 24G 的 4090"）—— 一句一条，跨会话共用，
  每次开新会话都该带上；
* ``history`` 记**对话本身**（这一轮问了什么、模型调了哪些工具、回了什么）—— 一条时间线，
  按会话分开，只在该会话里续上。

没有它的时候，宿主进程一退（关抽屉、重启桌面、换个 canvas 页面重载）整段对话就没了：
``server.py`` 的会话只活在内存里，而面板画的东西也只活在那个 webview 里。于是"刚才那个
参数是多少来着"只能重说一遍。有了它：面板一开就 ``agent/history`` 拉回上次的对话，宿主
重建会话时把存档喂回 :class:`~comfy_studio.agent.AgentSession`，接着聊就行。

几条取舍：

* **系统提示词不进存档**。它每轮都要重算（见 ``agent/loop.py`` 的 ``_system_text``：
  记忆、在挂的通道都会变），存下来反而是错的 —— 下次起来会拿着一份过期的规则当人设。
* **只存完整的轮次**。一次 ``ask`` 结束后历史才是配对的（每个 tool_call 都有对应的 tool
  结果，取消的那一轮也会补齐），所以按轮次边界裁：宁可少留几轮，也不把一次工具调用裁成
  半截 —— 半截的历史喂回模型只会得到一个更难查的 400。
* **条数与单条长度都有上限**。存档会原样进下一次的提示词，无限长的工具结果（一张画布的
  快照动辄几十万字符）会把 token 预算撑爆。超出就截断，并在**文本里写明**截了多少 ——
  模型看得见"这里被截了"，需要时自己重跑一次工具，而不是拿到一段看着完整的假内容。
* **文件名用会话 id 的哈希**。session_id 是外面的调用方（桌面壳、别的 MCP 客户端）给的，
  直接拿来拼文件名等于把 ``../`` 交给对方（能写到目录外面去）。哈希之后只会是 16 位十六
  进制，路径穿越这件事从根上不存在；真正的 session_id 存在文件里，读的时候核对一下，
  对不上就是文件被挪过或撞了哈希，直接报错。
* **读不了就报错，不静默重建**（和记忆同一个理由）：悄悄从空开始会变成"我的对话莫名其妙
  没了"，比报错难查得多。错误信息里写着文件路径与"删掉它就能重新开始"。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .agent.types import ChatMessage, ToolCall

#: 存档放在数据目录下的哪个子目录（memory.json 是平铺的，对话按会话分文件）。
SESSION_SUBDIR = "sessions"

#: 存档格式版本。形状变了就 +1，旧文件会被显式拒绝而不是硬读。
HISTORY_VERSION = 1

#: 一个会话最多留多少条消息（只按整轮裁，见 :func:`_trim`）。
MAX_MESSAGES = 60

#: 单条消息最多存多少字符。工具结果可以很长（画布快照那种），存档却要每次都进提示词。
MAX_CONTENT_CHARS = 4000

#: 截断标记里带的说明，模型与用户都能看见"这里不是原文"。
TRUNCATED_MARK = "…（存档已截断 {dropped} 字符）"

#: 会话清单里给标题留多少字符（标题取第一句用户话，面板那行放不下更长的）。
TITLE_CHARS = 40


class HistoryError(RuntimeError):
    """对话存档层面的错误：session_id 不合法、文件读不了、格式不认识、消息形状不对。"""


@dataclass(frozen=True)
class SessionHistory:
    """一次读档的结果。"""

    #: 这份存档是哪个会话的（文件里自报的那个 —— 读的时候已经与问过的 id 核对过）。
    session_id: str
    #: 可以直接喂回会话的消息（不含 system —— 它每轮重算）。
    messages: tuple[ChatMessage, ...]
    #: 因为超过 :data:`MAX_MESSAGES` 而被丢掉的消息条数（手工改过或旧版本写的文件才会 > 0）。
    dropped: int
    #: 上次落盘时间（ISO 8601，UTC）；没存过就是空串。
    saved_at: str


@dataclass(frozen=True)
class SessionSummary:
    """一段对话的摘要 —— 面板那份"你有几段对话"的清单就照它画。

    它**不是**一次读档的结果（不带着整段对话），只够画一行：标题、条数、上次落盘时间。
    """

    #: 文件里自报的会话 id；文件读不出来时是空串（那就只认得出 ``file``）。
    session_id: str
    #: 存档文件名（读不出来时，这是唯一能指给用户看的东西）。
    file: str
    #: 存下来的消息条数（读不出来时是 0）。
    messages: int
    #: 上次落盘时间（ISO 8601，UTC）；读不出来时是空串。
    saved_at: str
    #: 标题：第一句用户话，压成一行、按 :data:`TITLE_CHARS` 截断；一句用户话都没有就是空串。
    title: str
    #: 这个文件读不了的原因（原样给用户看）；读得了就是 None。
    error: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _one_line(text: str) -> str:
    """压成一行并按 :data:`TITLE_CHARS` 截断 —— 标题要能在下拉里一行放得下。"""
    flat = " ".join(text.split())
    if len(flat) <= TITLE_CHARS:
        return flat
    return flat[:TITLE_CHARS] + "…"


def title_of(messages: Sequence[ChatMessage]) -> str:
    """标题取**第一句用户话**：那是用户自己给这段对话起的名，比时间戳好认。

    给会话清单用；活会话读内存里的那份、存档会话读盘上那份，两边同一套算法。
    """
    for message in messages:
        if message.role == "user" and message.content.strip():
            return _one_line(message.content)
    return ""


def _clean_session_id(value: Any) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise HistoryError("session_id 必须是非空字符串")
    return value.strip()


def _truncate_content(role: str, content: str) -> str:
    """按 :data:`MAX_CONTENT_CHARS` 截一条消息的正文，截了就写明截了多少。"""
    if len(content) <= MAX_CONTENT_CHARS:
        return content
    dropped = len(content) - MAX_CONTENT_CHARS
    mark = TRUNCATED_MARK.format(dropped=dropped)
    # 标记本身也算长度，别让它把结果顶过上限。
    return content[: max(0, MAX_CONTENT_CHARS - len(mark))] + mark


def _trim(messages: Sequence[ChatMessage], limit: int = MAX_MESSAGES) -> tuple[list[ChatMessage], int]:
    """从**轮次边界**裁到 ``limit`` 条以内，返回 (留下的, 丢掉的条数)。

    边界的定义很直白：留下的第一条必须是用户消息。这样后面要么是完整的
    assistant(可能带 tool_calls) + tool 组，要么什么都没有 —— 不会出现"结果还在、
    调用被裁掉了"那种半截历史。
    """
    kept = list(messages)
    if len(kept) <= limit:
        return kept, 0
    window = kept[-limit:]
    for index, message in enumerate(window):
        if message.role == "user":
            return window[index:], len(kept) - len(window) + index
    # 一条用户消息都没有（理论上不会）：宁可全不要，也不要半截的工具调用。
    return [], len(kept)


def _message_to_wire(message: ChatMessage) -> dict[str, Any]:
    """存成 OpenAI 那套形状 —— 它本来就是事实标准，存档不必再发明一种。"""
    wire: dict[str, Any] = {"role": message.role}
    if message.role == "tool":
        wire["content"] = _truncate_content(message.role, message.content)
        wire["tool_call_id"] = message.tool_call_id or ""
        if message.name:
            wire["name"] = message.name
        return wire
    wire["content"] = _truncate_content(message.role, message.content)
    if message.tool_calls:
        wire["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    return wire


def _tool_call_from_wire(raw: Any, where: str) -> ToolCall:
    if not isinstance(raw, dict):
        raise HistoryError(f"{where} 里的 tool_calls 必须是对象数组，给的是 {type(raw).__name__}")
    function = raw.get("function")
    if not isinstance(function, dict):
        raise HistoryError(f"{where} 里的 tool_call 没有 function 对象")
    name = function.get("name")
    if not isinstance(name, str) or name.strip() == "":
        raise HistoryError(f"{where} 里的 tool_call 没有函数名")
    arguments = function.get("arguments") or "{}"
    if isinstance(arguments, dict):
        parsed = arguments
    elif isinstance(arguments, str):
        try:
            parsed = json.loads(arguments) if arguments.strip() else {}
        except ValueError as err:
            raise HistoryError(f"{where} 里工具 {name} 的参数不是合法 JSON: {err}") from err
    else:
        raise HistoryError(f"{where} 里工具 {name} 的参数类型不支持: {type(arguments).__name__}")
    if not isinstance(parsed, dict):
        raise HistoryError(f"{where} 里工具 {name} 的参数不是 JSON 对象")
    call_id = raw.get("id")
    if not isinstance(call_id, str) or call_id == "":
        raise HistoryError(f"{where} 里工具 {name} 的调用没有 id")
    return ToolCall(id=call_id, name=name, arguments=parsed)


def _message_from_wire(raw: Any, index: int) -> ChatMessage:
    """从存档里读回一条消息。形状不对就报错并**指出是第几条** —— 手工改过文件时好定位。"""
    where = f"第 {index} 条消息"
    if not isinstance(raw, dict):
        raise HistoryError(f"{where} 不是对象：{type(raw).__name__}")
    role = raw.get("role")
    if role == "system":
        raise HistoryError(
            f"{where} 是 system —— 存档里不该有它（系统提示词每轮重算，存下来就成了过期人设）"
        )
    if role not in ("user", "assistant", "tool"):
        raise HistoryError(f"{where} 的 role 不认识：{role!r}")
    content = raw.get("content")
    if content is None:
        # 带 tool_calls 的 assistant 允许 content 为空（OpenAI 那边就是这么发的）。
        content = "" if raw.get("tool_calls") else None
    if not isinstance(content, str):
        raise HistoryError(f"{where} 的 content 必须是字符串，给的是 {type(raw.get('content')).__name__}")
    if role == "tool":
        call_id = raw.get("tool_call_id")
        if not isinstance(call_id, str) or call_id == "":
            raise HistoryError(f"{where} 是工具结果却没有 tool_call_id")
        name = raw.get("name")
        return ChatMessage(
            role="tool",
            content=content,
            tool_call_id=call_id,
            name=name if isinstance(name, str) and name else None,
        )
    calls: list[ToolCall] = []
    raw_calls = raw.get("tool_calls")
    if raw_calls is not None:
        if not isinstance(raw_calls, list):
            raise HistoryError(f"{where} 的 tool_calls 必须是数组")
        calls = [_tool_call_from_wire(item, where) for item in raw_calls]
    return ChatMessage(role=role, content=content, tool_calls=calls)


def _pairing_problem(messages: Sequence[ChatMessage]) -> str | None:
    """挑历史里"工具结果配不上调用"的刺：有问题返回一句描述（第几条、哪个工具），没问题返回 None。

    读存档与写存档两边共用这一份（写那边不肯把不成对的历史落盘 —— 落下去的文件下次会被
    整份拒绝，用户那段对话直接打不开，比这一轮没落盘糟得多）。

    "欠着结果"这件事要**跨组**盯着：一次一轮里可以连着调好几次工具（模型一轮里发两次
    tool_calls），所以碰上第二组调用时，得先看第一组是不是还没等到结果 —— 只用当前这一组
    的 id 覆盖，等于把"上一组的结果全缺"从眼皮底下放过去，而那正是喂回模型会被打回的
    那份历史。
    """
    pending: set[str] = set()
    owed: int | None = None
    for index, message in enumerate(messages):
        if message.role == "assistant" and message.tool_calls:
            if pending:
                return (
                    f"第 {index} 条又要调工具，可第 {owed} 条的那次调用还没等到结果"
                )
            ids = [call.id for call in message.tool_calls]
            if len(set(ids)) != len(ids):
                return f"第 {index} 条的 tool_calls 里有重复的调用 id"
            pending = set(ids)
            owed = index
            continue
        if message.role == "tool":
            if not pending or message.tool_call_id not in pending:
                return f"第 {index} 条工具结果（{message.name or '未知工具'}）配不上任何调用"
            pending.discard(message.tool_call_id or "")
            continue
        if pending:
            return f"第 {index} 条是 {message.role}，可第 {owed} 条的工具调用还没等到结果"
    # 收尾也要看一眼：挂着一组没结果的调用就结束，是**最像样的**那种半截历史
    # （后面没有别的消息来触发上面那个分支，不看就一路放过去）。
    if pending:
        return f"第 {owed} 条的调用一直没等到结果"
    return None


def _check_pairing(messages: Sequence[ChatMessage]) -> None:
    """读存档时挑刺：每个工具结果都得配得上前面的调用，否则这份历史喂回模型只会被服务端打回。

    这里宁可**拒绝**整份存档也不"修"它：少一条结果就少一条，模型看到的历史与真实发生的
    对不上，比报错更难查（报错至少指得出文件在哪）。
    """
    problem = _pairing_problem(messages)
    if problem:
        raise HistoryError(f"{problem}：存档被改坏了")


def entries(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """把历史消息转成面板能直接照着画的条目（与实时事件同一套字段）。

    顺序按真实发生的来：模型的"过程话"在它要的工具之前，工具结果跟在调用之后。带
    tool_calls 的 assistant 消息就是"过程"（画成 intermediate），没带的才是这一轮的回答
    （画成 final）—— 与 ``agent/event`` 那边的分法一致，面板因此两种来路都画得一样。
    """
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "user":
            out.append({"type": "user", "text": message.content})
        elif message.role == "assistant":
            if message.content.strip():
                out.append(
                    {
                        "type": "assistant",
                        "text": message.content,
                        "variant": "intermediate" if message.tool_calls else "final",
                    }
                )
            for call in message.tool_calls:
                out.append(
                    {
                        "type": "tool_call",
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                )
        elif message.role == "tool":
            out.append(
                {
                    "type": "tool_result",
                    "id": message.tool_call_id or "",
                    "name": message.name or "",
                    "text": message.content,
                }
            )
    return out


class SessionHistoryStore:
    """一份按会话分开的对话存档。目录由调用方给（``--memory-dir`` / :func:`memory_home` + ``sessions``）。"""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory).expanduser()

    def path(self, session_id: str) -> Path:
        """某个会话的存档文件路径。

        文件名是 session_id 的 sha1 前 16 位：session_id 来自外面，直接拼进路径等于把
        ``..`` 交给对方。真正的 id 存在文件里，读的时候核对。
        """
        key = hashlib.sha1(_clean_session_id(session_id).encode("utf-8")).hexdigest()[:16]
        return self.directory / f"{key}.json"

    # ---- 读 / 写 ---------------------------------------------------------

    def load(self, session_id: str) -> SessionHistory:
        """读回一个会话的历史。文件不存在 = 还没聊过，这不是错误。"""
        session_id = _clean_session_id(session_id)
        path = self.path(session_id)
        if not path.exists():
            return SessionHistory(session_id=session_id, messages=(), dropped=0, saved_at="")
        return self._read(path, expected=session_id)

    def list(self) -> list[SessionSummary]:
        """列出目录里所有聊过的对话（面板那份会话清单就照它画）。

        一个文件读不了**不让整份清单失败**：那一段如实带上 ``error``（此时只认得出文件名，
        session_id 是空的），别的照旧列出来 —— 一个坏存档把所有对话都从清单里抹掉，用户连
        "换一段接着聊"都做不到，比多一行红字糟得多。读不了的文件一律原样留着，不重建。

        排序按上次落盘时间倒序（最近的排前面），没写时间的排最后、按 id 兜底 —— 清单要稳定，
        同一份目录列两次不能给出两种顺序。
        """
        if not self.directory.is_dir():
            return []
        out: list[SessionSummary] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                loaded = self._read(path, expected=None)
            except HistoryError as err:
                out.append(
                    SessionSummary(
                        session_id="",
                        file=path.name,
                        messages=0,
                        saved_at="",
                        title="",
                        error=str(err),
                    )
                )
                continue
            out.append(
                SessionSummary(
                    session_id=loaded.session_id,
                    file=path.name,
                    messages=len(loaded.messages),
                    saved_at=loaded.saved_at,
                    title=title_of(loaded.messages),
                )
            )
        out.sort(key=lambda item: (item.saved_at, item.session_id), reverse=True)
        return out

    def _read(self, path: Path, expected: str | None) -> SessionHistory:
        """读一份存档文件。``expected`` 给 None 表示"不知道是谁的，以文件里自报的为准"（列目录用）。

        除了这一处核对，两条路要挑的刺完全一样 —— 所以只有这一份实现，别在两边各写一遍。
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            raise HistoryError(
                f"对话存档读不了（{path}）：{err}。"
                "请修好它，或者把它删掉——删掉就是从一段空对话重新开始"
            ) from err
        if not isinstance(raw, dict):
            raise HistoryError(f"对话存档不是 JSON 对象（{path}）：{type(raw).__name__}")
        version = raw.get("version")
        if version != HISTORY_VERSION:
            raise HistoryError(
                f"对话存档的版本不认（{path}）：文件里是 {version!r}，"
                f"这个版本只认 {HISTORY_VERSION}。旧版本的存档读不了，删掉它就能重新开始"
            )
        declared = raw.get("session_id")
        if expected is None:
            if not isinstance(declared, str) or declared.strip() == "":
                raise HistoryError(f"对话存档里没写 session_id（{path}）：不知道这是哪段对话")
        elif declared != expected:
            raise HistoryError(
                f"对话存档对不上会话（{path}）：文件里记的是 {declared!r}，"
                "问的是别的会话。多半是文件被挪过或改过，删掉它就能重新开始"
            )
        raw_messages = raw.get("messages")
        if not isinstance(raw_messages, list):
            raise HistoryError(f"对话存档里的 messages 必须是数组（{path}）")
        messages = [_message_from_wire(item, index) for index, item in enumerate(raw_messages)]
        _check_pairing(messages)
        kept, dropped = _trim(messages)
        saved_at = raw.get("saved_at")
        return SessionHistory(
            session_id=declared if isinstance(declared, str) else "",
            messages=tuple(kept),
            dropped=dropped,
            saved_at=saved_at if isinstance(saved_at, str) else "",
        )

    def save(self, session_id: str, messages: Sequence[ChatMessage]) -> int:
        """把一个会话的历史写下去（原子替换），返回真正存下的条数。

        system 一律丢掉（每轮重算），超长/超量按上面的规矩裁。写失败会抛
        :class:`HistoryError` —— 由调用方决定这算不算把这一轮判失败（宿主那边只记一行
        stderr，不会因为存档写不进去就把用户这一轮的答案吞掉）。
        """
        session_id = _clean_session_id(session_id)
        payload_messages = [message for message in messages if message.role != "system"]
        kept, _dropped = _trim(payload_messages)
        # 不成对的历史一律不落盘：写下去的话，下次读它会被上面的 _check_pairing 整份拒绝，
        # 用户那段对话（连更早那些好轮次）就全打不开了。这里拒掉只赔上这一轮不落盘 ——
        # 答案已经在用户手里，宿主那边只记一行 stderr（见 server.py 的 _save_history）。
        problem = _pairing_problem(kept)
        if problem:
            raise HistoryError(
                f"这一轮的历史不成对，没写进存档：{problem}。"
                "写下去会让整份存档下次读不了，所以宁可这一轮不落盘"
            )
        body = {
            "version": HISTORY_VERSION,
            "session_id": session_id,
            "saved_at": _now(),
            "messages": [_message_to_wire(message) for message in kept],
        }
        text = json.dumps(body, ensure_ascii=False, indent=2)
        path = self.path(session_id)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            # 先写同目录的临时文件再 replace：中途崩了也不会留下半截 JSON（与记忆同一套）。
            handle = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.directory,
                prefix=".history-",
                suffix=".tmp",
                delete=False,
            )
            try:
                with handle:
                    handle.write(text)
                os.replace(handle.name, path)
            except BaseException:
                Path(handle.name).unlink(missing_ok=True)
                raise
        except OSError as err:
            raise HistoryError(f"对话存档写不进去（{path}）：{err}") from err
        return len(kept)

    def clear(self, session_id: str) -> bool:
        """删掉一个会话的存档（``agent/reset`` 走这条）。返回是否真的删了文件。

        必须删：不然"清空这段对话"在下次重启后又会被存档原样复活 —— 用户看到的会是
        "清了个寂寞"。
        """
        path = self.path(session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError as err:
            raise HistoryError(f"对话存档删不掉（{path}）：{err}") from err
        return True


__all__ = [
    "HISTORY_VERSION",
    "MAX_CONTENT_CHARS",
    "MAX_MESSAGES",
    "SESSION_SUBDIR",
    "TITLE_CHARS",
    "HistoryError",
    "SessionHistory",
    "SessionHistoryStore",
    "SessionSummary",
    "entries",
    "title_of",
]
