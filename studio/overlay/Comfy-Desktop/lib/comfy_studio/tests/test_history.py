"""``comfy_studio.history`` 的单元测试（纯本地：临时目录当数据目录，不拉子进程、不连模型）。

三种"回到上次"的来路都验：存档自己（存/读/裁/挑刺）、面板拿到的可画条目、以及宿主那一层
（``agent/history`` 先看活会话再看存档、``agent/reset`` 连存档一起删、一轮跑完自动落盘、
新会话把存档喂回去接着聊）。

另外验会话位满了怎么办（存档让"淘汰"变成无损操作，于是可以自动腾位子；没存档兜底就老实拒绝）。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_history -v
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfy_studio.agent import AgentError, AgentSession, DEFAULT_SYSTEM_PROMPT, LLMConfig
from comfy_studio.agent.types import ChatMessage, ToolCall
from comfy_studio.history import (
    HISTORY_VERSION,
    MAX_CONTENT_CHARS,
    MAX_MESSAGES,
    SESSION_SUBDIR,
    HistoryError,
    SessionHistoryStore,
    entries as history_entries,
)
from comfy_studio.cancel import CancelToken
from comfy_studio.mcp import McpTool
from comfy_studio.rpc import INVALID_PARAMS, INTERNAL_ERROR, RpcError
from comfy_studio.server import DEFAULT_SESSION, MAX_SESSIONS, StudioHost
from comfy_studio.skills import SkillCatalog


def _tool(name: str = "comfy_list_skills") -> McpTool:
    return McpTool(server="fake", name=name, description="假工具", input_schema={"type": "object"})


class _FakeLLM:
    """只回一句话的假模型：这些用例不连网络，也不真的跑工具。"""

    def __init__(self, reply: str = "好的") -> None:
        self.config = LLMConfig(base_url="http://127.0.0.1:9/v1", model="fake-model")
        self.reply = reply
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages, _tools=None, *, cancel=None, on_retry=None) -> ChatMessage:
        self.seen.append(list(messages))
        return ChatMessage(role="assistant", content=self.reply)

    async def close(self) -> None:
        """没什么要关的。"""


class _StubHub:
    """只满足 ``StudioHost`` / ``create_session`` 的构造：工具表给一张真的，但永远不该被调到。"""

    def __init__(self, tools: list[McpTool] | None = None) -> None:
        self.tools = list(tools) if tools is not None else [_tool()]

    async def call_tool(self, name, arguments, *, cancel=None):
        raise AssertionError("这些用例不该真的调工具")


class _Ctx:
    """``agent_chat`` 只要一个能收 ``agent/event`` 的出口。"""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, method: str, params: dict) -> None:
        self.events.append((method, params))


def _make_host(store: SessionHistoryStore | None, *, max_sessions: int = MAX_SESSIONS) -> StudioHost:
    """只挂对话存档的最小宿主（MCP 一个都不拉，工具表由假 hub 顶上）。

    ``max_sessions`` 调小给"会话位满了怎么办"那组用例用：真上限是 8，为了验淘汰没必要真建 8 个。
    """
    hub = _StubHub()
    return StudioHost(hub, SkillCatalog(hub), history=store, max_sessions=max_sessions)  # type: ignore[arg-type]


def _pairs(count: int) -> list[ChatMessage]:
    """造 ``count`` 条一问一答（以 user 开头），用来撑轮次边界。"""
    out: list[ChatMessage] = []
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        out.append(ChatMessage(role=role, content=f"第 {index} 句"))
    return out


def _write_raw(
    store: SessionHistoryStore,
    session_id: str,
    messages: list[dict],
    *,
    version: object = HISTORY_VERSION,
    declared: str | None = None,
) -> Path:
    """绕过 save() 直接写一份存档，用来摆出"文件被改坏 / 旧版本 / 别的会话写的"局面。

    ``declared`` 是文件里自报的 session_id（默认真实那个）；给别的值就是在摆"文件被挪过"。
    """
    path = store.path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "version": version,
        "session_id": session_id if declared is None else declared,
        "saved_at": "",
        "messages": messages,
    }
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return path


class SessionHistoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-history-")
        self.dir = Path(self._tmp.name)
        self.store = SessionHistoryStore(self.dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- 存与读 ---------------------------------------------------------

    def test_an_empty_directory_is_an_empty_conversation(self) -> None:
        # 文件不存在 = 还没聊过，不是错误，也不该有任何副作用。
        loaded = self.store.load("s1")
        self.assertEqual(loaded.messages, ())
        self.assertEqual(loaded.dropped, 0)
        self.assertEqual(loaded.saved_at, "")
        self.assertFalse(self.store.path("s1").exists())

    def test_a_conversation_survives_a_fresh_store(self) -> None:
        # 换一个进程/宿主就是这个效果：同一目录再开一份，读得到。
        messages = [
            ChatMessage(role="user", content="帮我把这张图放大两倍"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_1", name="fake__do_it", arguments={"scale": 2})],
            ),
            ChatMessage(role="tool", content='{"ok": true}', tool_call_id="call_1", name="fake__do_it"),
            ChatMessage(role="assistant", content="已经好了"),
        ]
        self.assertEqual(self.store.save("s1", messages), 4)

        loaded = SessionHistoryStore(self.dir).load("s1")
        self.assertEqual([m.role for m in loaded.messages], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(loaded.messages[0].content, "帮我把这张图放大两倍")
        self.assertEqual(loaded.messages[1].tool_calls[0].arguments, {"scale": 2})
        self.assertEqual(loaded.messages[2].tool_call_id, "call_1")
        self.assertEqual(loaded.messages[2].name, "fake__do_it")
        self.assertEqual(loaded.messages[3].content, "已经好了")
        self.assertTrue(loaded.saved_at)
        self.assertEqual(loaded.dropped, 0)

    def test_sessions_do_not_see_each_other(self) -> None:
        self.store.save("a", [ChatMessage(role="user", content="会话 a 的话")])
        self.store.save("b", [ChatMessage(role="user", content="会话 b 的话")])
        self.assertEqual(self.store.load("a").messages[0].content, "会话 a 的话")
        self.assertEqual(self.store.load("b").messages[0].content, "会话 b 的话")

    def test_the_system_prompt_is_not_stored(self) -> None:
        # 人设每轮重算（记忆、在挂的通道都会变），存下来就是一份过期人设。
        self.store.save("s1", [ChatMessage(role="system", content="旧人设"), ChatMessage(role="user", content="问")])
        loaded = self.store.load("s1")
        self.assertEqual([m.role for m in loaded.messages], ["user"])
        raw = json.loads(self.store.path("s1").read_text(encoding="utf-8"))
        self.assertNotIn("system", json.dumps(raw, ensure_ascii=False))

    def test_the_file_is_readable_json_with_a_version(self) -> None:
        self.store.save("s1", [ChatMessage(role="user", content="问")])
        raw = json.loads(self.store.path("s1").read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], HISTORY_VERSION)
        self.assertEqual(raw["session_id"], "s1")
        self.assertEqual(raw["messages"][0], {"role": "user", "content": "问"})

    def test_saving_leaves_no_temp_file_behind(self) -> None:
        # 原子写：临时文件必须已经被替换掉，不能留在目录里。
        self.store.save("s1", [ChatMessage(role="user", content="问")])
        self.assertEqual([p.name for p in self.dir.iterdir()], [self.store.path("s1").name])

    def test_clearing_removes_the_file_and_says_whether_it_was_there(self) -> None:
        self.store.save("s1", [ChatMessage(role="user", content="问")])
        self.assertIs(self.store.clear("s1"), True)
        self.assertFalse(self.store.path("s1").exists())
        # 再删一次没有东西可删，如实回 False（不是错误）。
        self.assertIs(self.store.clear("s1"), False)

    # ---- 路径安全 -------------------------------------------------------

    def test_a_hostile_session_id_cannot_escape_the_directory(self) -> None:
        # session_id 是外面给的，直接拼进路径等于把 `..` 交给对方。
        path = self.store.path("../../evil")
        self.assertEqual(path.parent, self.dir)
        self.assertRegex(path.name, r"^[0-9a-f]{16}\.json$")

        self.store.save("../../evil", [ChatMessage(role="user", content="问")])
        self.assertEqual([p.name for p in self.dir.iterdir()], [path.name])
        self.assertFalse((self.dir.parent / "evil.json").exists())

    def test_session_id_must_be_a_non_empty_string(self) -> None:
        for bad in ("", "   ", None, 7, ["s1"]):
            with self.assertRaises(HistoryError):
                self.store.path(bad)  # type: ignore[arg-type]
            with self.assertRaises(HistoryError):
                self.store.load(bad)  # type: ignore[arg-type]
            with self.assertRaises(HistoryError):
                self.store.save(bad, [])  # type: ignore[arg-type]

    # ---- 裁剪 -----------------------------------------------------------

    def test_only_whole_turns_are_kept(self) -> None:
        # 70 条（35 轮）超过上限 60：留下的第一条必须是 user，不能出现"结果还在、调用被裁掉"。
        self.store.save("s1", _pairs(70))
        raw = json.loads(self.store.path("s1").read_text(encoding="utf-8"))
        self.assertEqual(len(raw["messages"]), MAX_MESSAGES)
        self.assertEqual(raw["messages"][0]["role"], "user")
        # 文件里的裁剪不发生第二次，所以读回来的 dropped 是 0。
        loaded = self.store.load("s1")
        self.assertEqual(len(loaded.messages), MAX_MESSAGES)
        self.assertEqual(loaded.dropped, 0)

    def test_the_turn_boundary_is_respected_even_when_it_costs_a_message(self) -> None:
        # 65 条：窗口正好切在 assistant 上，宁可少留一条也要从 user 起头（59 条）。
        self.store.save("s1", _pairs(65))
        raw = json.loads(self.store.path("s1").read_text(encoding="utf-8"))
        self.assertEqual(len(raw["messages"]), 59)
        self.assertEqual(raw["messages"][0]["role"], "user")

    def test_a_hand_trimmed_file_reports_how_many_were_dropped(self) -> None:
        # 手工改过或旧版本写的文件可能超量：读的时候裁一次，并把丢掉的条数报出来。
        _write_raw(self.store, "s1", [{"role": m.role, "content": m.content} for m in _pairs(65)])
        loaded = self.store.load("s1")
        self.assertEqual(len(loaded.messages), 59)
        self.assertEqual(loaded.dropped, 6)
        self.assertEqual(loaded.messages[0].role, "user")

    def test_long_content_is_truncated_with_a_visible_mark(self) -> None:
        # 一段超长工具结果（画布快照那种）会把提示词撑爆：截断，并在文本里写明截了多少。
        long_text = "x" * (MAX_CONTENT_CHARS * 3)
        self.store.save(
            "s1",
            [
                ChatMessage(
                    role="assistant", content="", tool_calls=[ToolCall(id="call_1", name="t", arguments={})]
                ),
                ChatMessage(role="tool", content=long_text, tool_call_id="call_1", name="t"),
            ],
        )
        loaded = self.store.load("s1")
        content = loaded.messages[1].content
        self.assertLessEqual(len(content), MAX_CONTENT_CHARS)
        self.assertIn("存档已截断", content)
        self.assertIn(str(len(long_text) - MAX_CONTENT_CHARS), content)
        self.assertNotEqual(content, long_text)

    def test_short_content_is_stored_verbatim(self) -> None:
        text = "短的一句话"
        self.store.save("s1", [ChatMessage(role="user", content=text)])
        self.assertEqual(self.store.load("s1").messages[0].content, text)

    # ---- 读不了就报错 ---------------------------------------------------

    def test_a_broken_file_is_reported_and_left_alone(self) -> None:
        path = self.store.path("s1")
        path.write_text("{ 这不是 json", encoding="utf-8")
        with self.assertRaises(HistoryError) as caught:
            SessionHistoryStore(self.dir).load("s1")
        self.assertIn(str(path), str(caught.exception))
        # 不静默重建：坏文件原样留着，用户自己决定修还是删。
        self.assertEqual(path.read_text(encoding="utf-8"), "{ 这不是 json")

    def test_an_unknown_version_is_refused(self) -> None:
        _write_raw(self.store, "s1", [], version=99)
        with self.assertRaises(HistoryError) as caught:
            self.store.load("s1")
        self.assertIn("99", str(caught.exception))

    def test_a_file_written_for_another_session_is_refused(self) -> None:
        _write_raw(self.store, "s1", [{"role": "user", "content": "别人的话"}], declared="s2")
        with self.assertRaises(HistoryError) as caught:
            self.store.load("s1")
        self.assertIn("对不上会话", str(caught.exception))

    def test_a_broken_write_is_reported_with_the_path(self) -> None:
        blocked = self.dir / "blocked"
        blocked.write_text("这不是目录", encoding="utf-8")
        store = SessionHistoryStore(blocked / SESSION_SUBDIR)
        with self.assertRaises(HistoryError) as caught:
            store.save("s1", [ChatMessage(role="user", content="问")])
        self.assertIn(str(blocked / SESSION_SUBDIR), str(caught.exception))

    # ---- 消息形状与配对 -------------------------------------------------

    def test_a_system_message_in_the_archive_is_refused(self) -> None:
        _write_raw(self.store, "s1", [{"role": "system", "content": "过期人设"}])
        with self.assertRaises(HistoryError) as caught:
            self.store.load("s1")
        self.assertIn("system", str(caught.exception))

    def test_misshapen_messages_are_refused(self) -> None:
        cases = [
            ("不是对象", ["一段文本"]),
            ("role 不认识", [{"role": "robot", "content": "喂"}]),
            ("content 不是字符串", [{"role": "user", "content": 7}]),
            ("tool 没有 tool_call_id", [{"role": "tool", "content": "结果"}]),
            ("tool_calls 不是数组", [{"role": "assistant", "content": "", "tool_calls": {}}]),
        ]
        for label, messages in cases:
            with self.subTest(label=label):
                _write_raw(self.store, "s1", messages)
                with self.assertRaises(HistoryError):
                    self.store.load("s1")

    def test_tool_call_shapes_are_checked(self) -> None:
        cases = [
            ("不是对象", ["一段文本"]),
            ("没有 function", {"id": "call_1"}),
            ("没有函数名", {"id": "call_1", "function": {"arguments": "{}"}}),
            ("参数不是合法 JSON", {"id": "call_1", "function": {"name": "t", "arguments": "{ 不是"}}),
            ("参数类型不支持", {"id": "call_1", "function": {"name": "t", "arguments": 7}}),
            ("没有 id", {"function": {"name": "t", "arguments": "{}"}}),
        ]
        for label, call in cases:
            with self.subTest(label=label):
                _write_raw(self.store, "s1", [{"role": "assistant", "content": "", "tool_calls": [call]}])
                with self.assertRaises(HistoryError):
                    self.store.load("s1")

    def test_a_tool_result_that_matches_no_call_is_refused(self) -> None:
        # 少一条结果、或者结果配错了调用，喂回模型只会被服务端打回：宁可整份拒绝。
        _write_raw(
            self.store,
            "s1",
            [{"role": "tool", "content": "结果", "tool_call_id": "call_1", "name": "t"}],
        )
        with self.assertRaises(HistoryError) as caught:
            self.store.load("s1")
        self.assertIn("配不上任何调用", str(caught.exception))

        _write_raw(
            self.store,
            "s1",
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_1", "function": {"name": "t", "arguments": "{}"}}],
                },
                {"role": "tool", "content": "结果", "tool_call_id": "call_9", "name": "t"},
            ],
        )
        with self.assertRaises(HistoryError):
            self.store.load("s1")

    def test_a_pending_call_interrupted_by_a_user_message_is_refused(self) -> None:
        _write_raw(
            self.store,
            "s1",
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "call_1", "function": {"name": "t", "arguments": "{}"}}],
                },
                {"role": "user", "content": "还在吗"},
            ],
        )
        with self.assertRaises(HistoryError) as caught:
            self.store.load("s1")
        self.assertIn("没等到结果", str(caught.exception))

    def test_a_paired_call_and_result_read_back(self) -> None:
        _write_raw(
            self.store,
            "s1",
            [
                {
                    "role": "assistant",
                    "content": "先查一下",
                    "tool_calls": [{"id": "call_1", "function": {"name": "t", "arguments": '{"n": 1}'}}],
                },
                {"role": "tool", "content": "结果", "tool_call_id": "call_1", "name": "t"},
            ],
        )
        loaded = self.store.load("s1")
        self.assertEqual([m.role for m in loaded.messages], ["assistant", "tool"])
        self.assertEqual(loaded.messages[0].tool_calls[0].arguments, {"n": 1})
        self.assertEqual(loaded.messages[1].name, "t")


class HistoryEntriesTests(unittest.TestCase):
    """面板照着画的那套条目：与实时事件的字段保持一致。"""

    def test_the_roles_map_to_what_the_panel_paints(self) -> None:
        messages = [
            ChatMessage(role="user", content="问一句"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_1", name="fake__do_it", arguments={"limit": 5})],
            ),
            ChatMessage(role="tool", content="[]", tool_call_id="call_1", name="fake__do_it"),
            ChatMessage(role="assistant", content="答一句"),
        ]
        self.assertEqual(
            history_entries(messages),
            [
                {"type": "user", "text": "问一句"},
                {"type": "tool_call", "id": "call_1", "name": "fake__do_it", "arguments": {"limit": 5}},
                {"type": "tool_result", "id": "call_1", "name": "fake__do_it", "text": "[]"},
                {"type": "assistant", "text": "答一句", "variant": "final"},
            ],
        )

    def test_an_assistant_that_talks_before_calling_a_tool_is_intermediate(self) -> None:
        messages = [
            ChatMessage(
                role="assistant",
                content="先查一下可用的 skill",
                tool_calls=[ToolCall(id="call_1", name="fake__list", arguments={})],
            )
        ]
        self.assertEqual(
            history_entries(messages),
            [
                {"type": "assistant", "text": "先查一下可用的 skill", "variant": "intermediate"},
                {"type": "tool_call", "id": "call_1", "name": "fake__list", "arguments": {}},
            ],
        )

    def test_an_empty_conversation_has_nothing_to_paint(self) -> None:
        self.assertEqual(history_entries([]), [])


class SessionRestoreTests(unittest.TestCase):
    """存档喂回会话这一步（``AgentSession`` 的 ``history`` 参数）。"""

    def _session(self, history=None) -> AgentSession:
        return AgentSession(_StubHub(), [_tool()], llm=_FakeLLM(), history=history)  # type: ignore[arg-type]

    def test_without_history_the_conversation_is_just_the_system_prompt(self) -> None:
        session = self._session()
        self.assertEqual([m.role for m in session.messages], ["system"])
        self.assertEqual(session.messages[0].content, DEFAULT_SYSTEM_PROMPT)

    def test_an_archived_conversation_lands_right_after_the_system_prompt(self) -> None:
        history = [ChatMessage(role="user", content="上次问的"), ChatMessage(role="assistant", content="上次答的")]
        session = self._session(history)
        self.assertEqual([m.role for m in session.messages], ["system", "user", "assistant"])
        self.assertEqual(session.messages[1].content, "上次问的")
        self.assertEqual(session.messages[2].content, "上次答的")

    def test_an_archived_system_message_is_refused(self) -> None:
        # 人设每轮重算，从历史里再来一条就成了"两条人设、其中一条过期"。
        with self.assertRaises(AgentError) as caught:
            self._session([ChatMessage(role="system", content="过期人设")])
        self.assertIn("system", str(caught.exception))

    def test_something_that_is_not_a_message_is_refused(self) -> None:
        with self.assertRaises(AgentError):
            self._session([{"role": "user", "content": "问"}])  # type: ignore[list-item]

    def test_reset_leaves_only_the_system_prompt(self) -> None:
        session = self._session([ChatMessage(role="user", content="上次问的")])
        session.reset()
        self.assertEqual([m.role for m in session.messages], ["system"])


class HostHistoryTests(unittest.IsolatedAsyncioTestCase):
    """宿主那层：``agent/history`` 先看活会话再看存档，``agent/reset`` 连存档一起删。

    建会话（``StudioHost._session``）是 async 的：会话位满了它得先淘汰一个（关掉要是 await）。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-history-")
        self.dir = Path(self._tmp.name)
        self.store = SessionHistoryStore(self.dir / SESSION_SUBDIR)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _live_session(self, history=None) -> AgentSession:
        return AgentSession(_StubHub(), [_tool()], llm=_FakeLLM(), history=history)  # type: ignore[arg-type]

    def test_nothing_ever_said_is_an_empty_conversation(self) -> None:
        result = _make_host(self.store).agent_history({}, None)  # type: ignore[arg-type]
        self.assertEqual(result["session_id"], DEFAULT_SESSION)
        self.assertEqual(result["source"], "store")
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["messages"], 0)
        self.assertEqual(result["dropped"], 0)
        self.assertEqual(result["saved_at"], "")

    def test_without_the_archive_the_answer_is_still_an_empty_conversation(self) -> None:
        # --no-history：形状一样，只是永远没有内容可给。
        result = _make_host(None).agent_history({"session_id": "s1"}, None)  # type: ignore[arg-type]
        self.assertEqual(result["session_id"], "s1")
        self.assertEqual(result["source"], "store")
        self.assertEqual(result["entries"], [])

    def test_the_archive_comes_back_as_drawable_entries(self) -> None:
        self.store.save(
            DEFAULT_SESSION,
            [
                ChatMessage(role="user", content="帮我把这张图放大两倍"),
                ChatMessage(role="assistant", content="已经好了"),
            ],
        )
        result = _make_host(self.store).agent_history({}, None)  # type: ignore[arg-type]
        self.assertEqual(result["source"], "store")
        self.assertEqual(
            result["entries"],
            [
                {"type": "user", "text": "帮我把这张图放大两倍"},
                {"type": "assistant", "text": "已经好了", "variant": "final"},
            ],
        )
        self.assertEqual(result["messages"], 2)
        self.assertTrue(result["saved_at"])

    def test_a_live_session_wins_over_the_archive(self) -> None:
        # 存档要一轮末尾才写，活会话手里的历史更全；有活会话就不该去读盘。
        self.store.save(DEFAULT_SESSION, [ChatMessage(role="user", content="存档里那句")])
        host = _make_host(self.store)
        host._sessions[DEFAULT_SESSION] = self._live_session([ChatMessage(role="user", content="活着的那句")])

        result = host.agent_history({}, None)  # type: ignore[arg-type]
        self.assertEqual(result["source"], "session")
        self.assertEqual(result["entries"], [{"type": "user", "text": "活着的那句"}])
        self.assertEqual(result["messages"], 1)
        self.assertEqual(result["dropped"], 0)
        self.assertEqual(result["saved_at"], "")

    def test_a_broken_archive_is_reported_not_swallowed(self) -> None:
        path = self.store.path(DEFAULT_SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("坏了", encoding="utf-8")
        with self.assertRaises(RpcError) as caught:
            _make_host(self.store).agent_history({}, None)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, INTERNAL_ERROR)
        self.assertIn(str(path), caught.exception.message)

    def test_session_id_has_to_be_a_string(self) -> None:
        with self.assertRaises(RpcError) as caught:
            _make_host(self.store).agent_history({"session_id": 7}, None)  # type: ignore[arg-type]
        self.assertIn("session_id", caught.exception.message)

    def test_reset_also_clears_the_archive(self) -> None:
        # 只清内存的话，下次重启会被存档原样复活 —— 用户看到的是"清了个寂寞"。
        self.store.save(DEFAULT_SESSION, [ChatMessage(role="user", content="问")])
        host = _make_host(self.store)
        first = host.agent_reset({}, None)  # type: ignore[arg-type]
        self.assertEqual(first, {"session_id": DEFAULT_SESSION, "reset": False, "history_cleared": True})
        self.assertFalse(self.store.path(DEFAULT_SESSION).exists())
        second = host.agent_reset({}, None)  # type: ignore[arg-type]
        self.assertIs(second["history_cleared"], False)

    def test_reset_empties_the_live_session_and_only_its_own_archive(self) -> None:
        self.store.save(DEFAULT_SESSION, [ChatMessage(role="user", content="default 的")])
        self.store.save("other", [ChatMessage(role="user", content="other 的")])
        host = _make_host(self.store)
        session = self._live_session([ChatMessage(role="user", content="default 的")])
        host._sessions[DEFAULT_SESSION] = session

        result = host.agent_reset({}, None)  # type: ignore[arg-type]
        self.assertIs(result["reset"], True)
        self.assertIs(result["history_cleared"], True)
        self.assertEqual([m.role for m in session.messages], ["system"])
        # 别的会话的存档动都不动。
        self.assertTrue(self.store.path("other").exists())

    async def test_a_new_session_continues_the_archived_conversation(self) -> None:
        # 宿主重启之后接着聊，走的就是这一步：建会话时把存档喂回去。
        self.store.save(DEFAULT_SESSION, [ChatMessage(role="user", content="上次问的")])
        host = _make_host(self.store)
        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "fake-model"}):
            session = await host._session(DEFAULT_SESSION)
            again = await host._session(DEFAULT_SESSION)
        self.assertIs(session, again, "同一个会话不该被重建两遍")
        self.assertEqual([m.role for m in session.messages], ["system", "user"])
        self.assertEqual(session.messages[1].content, "上次问的")
        await host.close()

    async def test_a_broken_archive_blocks_a_new_session(self) -> None:
        path = self.store.path(DEFAULT_SESSION)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("坏了", encoding="utf-8")
        host = _make_host(self.store)
        with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "fake-model"}):
            with self.assertRaises(RpcError) as caught:
                await host._session(DEFAULT_SESSION)
        self.assertEqual(caught.exception.code, INTERNAL_ERROR)

    def test_a_failed_write_only_warns(self) -> None:
        # 答案已经算出来交给用户了，不该因为存档写不进去就把这一轮判成失败。
        blocked = self.dir / "blocked"
        blocked.write_text("这不是目录", encoding="utf-8")
        host = _make_host(SessionHistoryStore(blocked / SESSION_SUBDIR))
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            host._save_history(DEFAULT_SESSION, self._live_session())
        self.assertIn("对话存档没写成", err.getvalue())
        self.assertIn(DEFAULT_SESSION, err.getvalue())

    def test_without_the_archive_there_is_nothing_to_write(self) -> None:
        host = _make_host(None)
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            host._save_history(DEFAULT_SESSION, self._live_session())
        self.assertEqual(err.getvalue(), "")


class TurnPersistTests(unittest.IsolatedAsyncioTestCase):
    """一轮跑完就落盘 —— 面板重新打开时才有东西可画。"""

    async def test_a_finished_turn_lands_in_the_archive(self) -> None:
        with tempfile.TemporaryDirectory(prefix="comfy-studio-history-") as tmp:
            store = SessionHistoryStore(Path(tmp) / SESSION_SUBDIR)
            host = _make_host(store)
            with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "fake-model"}):
                session = await host._session(DEFAULT_SESSION)
            session.llm = _FakeLLM("已经好了")  # 换掉真 HTTP 客户端：这一轮不连网

            ctx = _Ctx()
            result = await host.agent_chat({"text": "帮我把这张图放大两倍"}, ctx)  # type: ignore[arg-type]
            self.assertEqual(result["text"], "已经好了")

            loaded = store.load(DEFAULT_SESSION)
            self.assertEqual([m.role for m in loaded.messages], ["user", "assistant"])
            self.assertEqual(loaded.messages[0].content, "帮我把这张图放大两倍")
            self.assertEqual(loaded.messages[1].content, "已经好了")
            # system 不进存档：人设每轮重算。
            self.assertNotIn("system", [m.role for m in loaded.messages])
            self.assertTrue(ctx.events)

    async def test_the_next_host_picks_the_conversation_back_up(self) -> None:
        # 宿主重启：同一个数据目录再起一个宿主，会话从存档接着聊。
        with tempfile.TemporaryDirectory(prefix="comfy-studio-history-") as tmp:
            store = SessionHistoryStore(Path(tmp) / SESSION_SUBDIR)
            store.save(
                DEFAULT_SESSION,
                [ChatMessage(role="user", content="上次问的"), ChatMessage(role="assistant", content="上次答的")],
            )
            host = _make_host(store)
            with mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "fake-model"}):
                session = await host._session(DEFAULT_SESSION)
            session.llm = _FakeLLM("接着答")
            llm = session.llm

            result = await host.agent_chat({"text": "接着上次"}, _Ctx())  # type: ignore[arg-type]
            self.assertEqual(result["text"], "接着答")
            # 上次那段 + 这一轮，都在这次请求的 messages 里。
            sent = llm.seen[0]
            self.assertEqual([m.role for m in sent], ["system", "user", "assistant", "user"])
            self.assertEqual(sent[1].content, "上次问的")
            self.assertEqual(sent[3].content, "接着上次")
            self.assertEqual(
                [m.role for m in store.load(DEFAULT_SESSION).messages], ["user", "assistant", "user", "assistant"]
            )


class SessionCapTests(unittest.IsolatedAsyncioTestCase):
    """会话位满了怎么办：能无损淘汰就自动淘汰，淘汰不了就如实拒绝 —— 别偷偷把对话丢了。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-history-")
        self.dir = Path(self._tmp.name)
        self.store = SessionHistoryStore(self.dir / SESSION_SUBDIR)
        # 建会话要有一份能用的模型配置；这里不连网，只求 create_session 别在构造时就报错。
        env = mock.patch.dict(os.environ, {"COMFY_STUDIO_LLM_MODEL": "fake-model"})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_the_least_recently_used_session_makes_room(self) -> None:
        host = _make_host(self.store, max_sessions=2)
        await host._session("s1")
        await host._session("s2")
        await host._session("s1")  # 碰一下 s1：最久没用的就换成了 s2
        await host._session("s3")
        self.assertEqual(list(host._sessions), ["s1", "s3"])
        await host.close()

    async def test_an_evicted_session_comes_back_from_the_archive(self) -> None:
        # 敢自动淘汰的前提就在这儿：淘汰等于把会话从内存里请出去，对话本身还在盘上。
        self.store.save("s2", [ChatMessage(role="user", content="s2 上次问的")])
        host = _make_host(self.store, max_sessions=1)
        await host._session("s1")
        await host._session("s2")  # 顶掉 s1，同时把 s2 的存档喂回来
        self.assertEqual(list(host._sessions), ["s2"])
        self.assertEqual([m.role for m in host._sessions["s2"].messages], ["system", "user"])
        self.assertEqual(host._sessions["s2"].messages[1].content, "s2 上次问的")
        await host.close()

    async def test_a_session_in_the_middle_of_a_turn_is_not_evicted(self) -> None:
        # 那一轮还在往它的 messages 里写，关掉它等于把活劈了。
        host = _make_host(self.store, max_sessions=1)
        await host._session("s1")
        host._turns["s1"] = CancelToken()
        with self.assertRaises(RpcError) as caught:
            await host._session("s2")
        self.assertEqual(caught.exception.code, INVALID_PARAMS)
        self.assertIn("都有一轮在跑", caught.exception.message)
        self.assertIn("s1", caught.exception.message)
        self.assertEqual(list(host._sessions), ["s1"])

    async def test_without_the_archive_a_new_session_is_refused(self) -> None:
        # --no-history：没有存档兜底，淘汰就是真把对话丢了 —— 宁可拒绝，也不偷偷丢。
        host = _make_host(None, max_sessions=1)
        await host._session("s1")
        with self.assertRaises(RpcError) as caught:
            await host._session("s2")
        self.assertEqual(caught.exception.code, INVALID_PARAMS)
        self.assertIn("--no-history", caught.exception.message)
        self.assertIn("复用已有的 session_id", caught.exception.message)
        # 别给一个做不到的建议：agent/reset 只清对话、不腾会话位（宿主没有"关会话"的调用）。
        self.assertNotIn("先 agent/reset 掉不用的", caught.exception.message)
        self.assertEqual(list(host._sessions), ["s1"])

    async def test_a_session_created_while_making_room_is_reused(self) -> None:
        # 腾位子要 await（关掉被淘汰的会话），这中间可能已经有人把同一个会话建好了：
        # 那就用那个，别再建第二个 —— 后建的会把前一个顶掉，谁都不再关得上它。
        host = _make_host(self.store, max_sessions=1)
        await host._session("s1")
        impostor = AgentSession(_StubHub(), [_tool()], llm=_FakeLLM())  # type: ignore[arg-type]

        async def fake_make_room() -> None:
            host._sessions.pop("s1")
            host._sessions["s2"] = impostor

        with mock.patch.object(host, "_make_room", new=fake_make_room):
            session = await host._session("s2")
        self.assertIs(session, impostor)
        self.assertEqual(list(host._sessions), ["s2"])

    def test_reset_is_refused_while_a_turn_is_running(self) -> None:
        # 否则这一轮收尾会把刚删掉的存档原样写回来：白删一次，用户还以为清干净了。
        self.store.save(DEFAULT_SESSION, [ChatMessage(role="user", content="问")])
        host = _make_host(self.store)
        host._sessions[DEFAULT_SESSION] = AgentSession(  # type: ignore[arg-type]
            _StubHub(), [_tool()], llm=_FakeLLM()
        )
        host._turns[DEFAULT_SESSION] = CancelToken()
        with self.assertRaises(RpcError) as caught:
            host.agent_reset({}, None)  # type: ignore[arg-type]
        self.assertEqual(caught.exception.code, INVALID_PARAMS)
        self.assertIn("agent/cancel", caught.exception.message)
        self.assertTrue(self.store.path(DEFAULT_SESSION).exists(), "被拒的重置不该动存档")


if __name__ == "__main__":
    unittest.main()
