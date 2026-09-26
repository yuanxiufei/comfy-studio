"""``comfy_studio.memory`` 的单元测试（纯本地：临时目录当记忆目录，不拉子进程、不连模型）。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_memory_tools -v
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfy_studio.agent import (
    DEFAULT_SYSTEM_PROMPT,
    AgentError,
    AgentSession,
    compose_system_prompt,
)
from comfy_studio.agent.llm import LLMConfig
from comfy_studio.agent.types import ChatMessage
from comfy_studio.mcp import McpError, McpHub
from comfy_studio.memory import (
    MAX_ENTRIES,
    MAX_TEXT_CHARS,
    MEMORY_PROMPT_RULES,
    MEMORY_TOOLS,
    PROMPT_MAX_ENTRIES,
    MemoryClient,
    MemoryStore,
    MemoryStoreError,
    memory_home,
)
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog


def _call(client: MemoryClient, tool: str, **args):
    return asyncio.run(client.call_tool(tool, args))


def _payload(result: dict) -> dict:
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def _error_text(result: dict) -> str:
    assert result["isError"] is True, result
    return result["content"][0]["text"]


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-memory-")
        self.dir = Path(self._tmp.name)
        self.store = MemoryStore(self.dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- 记与存 ---------------------------------------------------------

    def test_an_empty_directory_is_just_an_empty_memory(self) -> None:
        # 文件不存在 = 还没记过，不是错误，也不需要提示词里出现"出事"的说法。
        self.assertEqual(self.store.count, 0)
        self.assertFalse(self.store.path.exists())
        self.assertIn("目前还没记住任何事", self.store.digest())

    def test_a_remembered_thing_survives_a_fresh_store(self) -> None:
        # 换一个进程/宿主就是这个效果：同一目录再开一份，读得到。
        self.store.remember("用户喜欢方形构图（1:1）", tags=["构图"])
        again = MemoryStore(self.dir)
        self.assertEqual([e.text for e in again.entries], ["用户喜欢方形构图（1:1）"])
        self.assertEqual(again.entries[0].tags, ("构图",))
        self.assertEqual(again.entries[0].id, "m-1")
        self.assertTrue(again.entries[0].created_at)

    def test_ids_count_up_and_are_given_back(self) -> None:
        first = self.store.remember("第一件")["entry"]
        second = self.store.remember("第二件")["entry"]
        self.assertEqual((first.id, second.id), ("m-1", "m-2"))

    def test_a_repeat_is_not_recorded_twice(self) -> None:
        original = self.store.remember("用户喜欢方形构图")
        again = self.store.remember("  用户喜欢方形构图  ")  # 首尾空白不算不同
        self.assertIs(again["duplicate"], True)
        self.assertEqual(again["entry"].id, original["entry"].id)
        self.assertEqual(self.store.count, 1)

    def test_case_only_difference_is_still_the_same_memory(self) -> None:
        self.store.remember("常用 SDXL base 1.0")
        again = self.store.remember("常用 sdxl BASE 1.0")
        self.assertIs(again["duplicate"], True)
        self.assertEqual(self.store.count, 1)

    def test_the_store_refuses_to_grow_without_bound(self) -> None:
        with mock.patch("comfy_studio.memory.MAX_ENTRIES", 2):
            self.store.remember("一")
            self.store.remember("二")
            with self.assertRaises(MemoryStoreError) as caught:
                self.store.remember("三")
        self.assertIn("memory__forget", str(caught.exception))
        self.assertEqual(self.store.count, 2)

    def test_saving_leaves_no_temp_file_behind(self) -> None:
        # 原子写：临时文件必须已经被替换掉，不能留在目录里。
        self.store.remember("一件事")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["memory.json"])

    def test_the_file_is_readable_json_with_a_version(self) -> None:
        self.store.remember("一件事")
        raw = json.loads((self.dir / "memory.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["version"], 1)
        self.assertEqual(raw["entries"][0]["text"], "一件事")

    # ---- 参数与文件都得挑刺 ---------------------------------------------

    def test_text_has_to_be_a_non_empty_string(self) -> None:
        for bad in ("", "   ", None, 7, ["一句话"]):
            with self.assertRaises(MemoryStoreError):
                self.store.remember(bad)  # type: ignore[arg-type]

    def test_text_length_is_capped(self) -> None:
        with self.assertRaises(MemoryStoreError) as caught:
            self.store.remember("字" * (MAX_TEXT_CHARS + 1))
        self.assertIn(str(MAX_TEXT_CHARS), str(caught.exception))
        self.store.remember("字" * MAX_TEXT_CHARS)  # 正好到顶是允许的

    def test_tags_are_checked_and_deduped(self) -> None:
        entry = self.store.remember("一件事", tags=["构图", "构图", " 尺寸 "])["entry"]
        self.assertEqual(entry.tags, ("构图", "尺寸"))
        # 先去重再数上限：模型把同一个标签写六遍，存下来只有一个，不该算越界。
        repeated = self.store.remember("另一件事", tags=["构图"] * 6)["entry"]
        self.assertEqual(repeated.tags, ("构图",))
        for bad in (["a", "b", "c", "d", "e", "f"], ["x" * 33], ["ok", 3], "构图"):
            with self.assertRaises(MemoryStoreError):
                self.store.remember("第三件事", tags=bad)  # type: ignore[arg-type]

    def test_a_broken_file_is_reported_and_left_alone(self) -> None:
        path = self.dir / "memory.json"
        path.write_text("{ 这不是 json", encoding="utf-8")
        with self.assertRaises(MemoryStoreError) as caught:
            MemoryStore(self.dir).load()
        self.assertIn(str(path), str(caught.exception))
        # 不静默重建：坏文件原样留着，用户自己决定修还是删。
        self.assertEqual(path.read_text(encoding="utf-8"), "{ 这不是 json")

    def test_an_unknown_version_is_refused(self) -> None:
        (self.dir / "memory.json").write_text(
            json.dumps({"version": 99, "entries": []}), encoding="utf-8"
        )
        with self.assertRaises(MemoryStoreError) as caught:
            MemoryStore(self.dir).load()
        self.assertIn("99", str(caught.exception))

    def test_a_misshapen_entry_is_refused(self) -> None:
        (self.dir / "memory.json").write_text(
            json.dumps({"version": 1, "entries": [{"text": "缺 id"}]}), encoding="utf-8"
        )
        with self.assertRaises(MemoryStoreError):
            MemoryStore(self.dir).load()

    # ---- 查 -----------------------------------------------------------------

    def test_recall_lists_the_newest_first(self) -> None:
        self.store.remember("早的")
        self.store.remember("晚的")
        payload = self.store.recall()
        self.assertEqual(payload["count"], 2)
        self.assertEqual([e["text"] for e in payload["entries"]], ["晚的", "早的"])

    def test_recall_filters_by_text_or_tag_ignoring_case(self) -> None:
        self.store.remember("用户常跑 1024x1024", tags=["尺寸"])
        self.store.remember("用户不喜欢模糊的图", tags=["风格"])
        self.assertEqual([e["text"] for e in self.store.recall("尺寸")["entries"]], ["用户常跑 1024x1024"])
        self.assertEqual([e["text"] for e in self.store.recall("不喜欢")["entries"]], ["用户不喜欢模糊的图"])
        self.assertEqual(self.store.recall("SDXL_BASE")["matched"], 0)
        self.assertEqual(self.store.recall("没有的东西")["matched"], 0)

    def test_recall_does_not_touch_the_file(self) -> None:
        # 只是查一下，不该产生任何副作用（也就不该写盘）。
        self.store.remember("一件事")
        before = (self.dir / "memory.json").read_text(encoding="utf-8")
        self.store.recall()
        self.store.recall("一件")
        self.assertEqual((self.dir / "memory.json").read_text(encoding="utf-8"), before)

    def test_recall_limit_is_checked(self) -> None:
        self.store.remember("一件事")
        self.assertEqual(len(self.store.recall(limit=1)["entries"]), 1)
        for bad in (0, -1, 201, "5", 2.5, True):
            with self.assertRaises(MemoryStoreError):
                self.store.recall(limit=bad)  # type: ignore[arg-type]
        with self.assertRaises(MemoryStoreError):
            self.store.recall(query=7)  # type: ignore[arg-type]

    def test_forgetting_a_missing_id_says_what_is_there(self) -> None:
        self.store.remember("唯一一件")
        with self.assertRaises(MemoryStoreError) as caught:
            self.store.forget("m-9")
        self.assertIn("m-1", str(caught.exception))
        with self.assertRaises(MemoryStoreError):
            self.store.forget("")

    def test_forget_removes_and_persists(self) -> None:
        entry = self.store.remember("记错了的")["entry"]
        gone = self.store.forget(entry.id)
        self.assertEqual(gone["entry"]["text"], "记错了的")
        self.assertEqual(self.store.count, 0)
        self.assertEqual(MemoryStore(self.dir).count, 0)
        # 删掉之后再记同一句：应该是一条新的，而不是又被判成重复。
        self.assertEqual(self.store.remember("记错了的")["duplicate"], False)

    # ---- 提示词那一段 ---------------------------------------------------

    def test_the_digest_teaches_how_to_use_the_tools(self) -> None:
        digest = self.store.digest()
        for tool in ("memory__remember", "memory__recall", "memory__forget"):
            self.assertIn(tool, digest)
        self.assertTrue(digest.startswith(MEMORY_PROMPT_RULES))

    def test_the_digest_carries_the_remembered_things_with_their_ids(self) -> None:
        entry = self.store.remember("用户喜欢方形构图", tags=["构图"])["entry"]
        digest = self.store.digest()
        self.assertIn(f"[{entry.id}] 用户喜欢方形构图", digest)
        self.assertIn("标签: 构图", digest)
        self.assertIn("共 1 条", digest)

    def test_a_long_memory_says_how_many_were_left_out(self) -> None:
        with mock.patch("comfy_studio.memory.PROMPT_MAX_ENTRIES", 2):
            for index in range(4):
                self.store.remember(f"第 {index} 件事")
            digest = self.store.digest()
        self.assertIn("这里列最新的 2 条", digest)
        self.assertIn("另有 2 条没有列出来", digest)
        # 列出来的是最新的两条（新的在前）。
        self.assertIn("第 3 件事", digest)
        self.assertNotIn("第 0 件事", digest)

    def test_the_default_memory_home_is_a_user_level_directory(self) -> None:
        # 不许落在 ComfyUI 检出里（那会跟着检出一起被删）：路径要带 comfy-studio 这个名字，
        # 而且不该是当前工作目录下面的一层。
        home = memory_home()
        self.assertEqual(home.name, "comfy-studio")
        self.assertNotEqual(home, Path.cwd())


class MemoryClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-memory-")
        self.dir = Path(self._tmp.name)
        self.store = MemoryStore(self.dir)
        self.client = MemoryClient(self.store)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tools_are_named_and_described(self) -> None:
        tools = asyncio.run(self.client.list_tools())
        self.assertEqual([t.name for t in tools], [spec.name for spec in MEMORY_TOOLS])
        self.assertEqual([t.name for t in tools], ["remember", "recall", "forget"])
        for tool in tools:
            self.assertEqual(tool.server, "memory")
            self.assertTrue(tool.description.strip())
            self.assertIn("properties", tool.input_schema)

    def test_hub_exposes_them_qualified(self) -> None:
        hub = McpHub([], extra_clients=[self.client])
        asyncio.run(hub.start())
        self.assertEqual(
            [t.qualified_name for t in hub.tools],
            ["memory__remember", "memory__recall", "memory__forget"],
        )

    def test_unknown_tool_is_a_protocol_error(self) -> None:
        with self.assertRaises(McpError):
            _call(self.client, "wipe_everything")

    def test_remember_returns_the_id_and_the_count(self) -> None:
        payload = _payload(_call(self.client, "remember", text="用户喜欢方形构图", tags=["构图"]))
        self.assertEqual(payload["id"], "m-1")
        self.assertEqual(payload["text"], "用户喜欢方形构图")
        self.assertEqual(payload["tags"], ["构图"])
        self.assertIs(payload["duplicate"], False)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["file"], str(self.dir / "memory.json"))

    def test_recall_returns_entries_newest_first(self) -> None:
        _call(self.client, "remember", text="早的")
        _call(self.client, "remember", text="晚的")
        payload = _payload(_call(self.client, "recall"))
        self.assertEqual(payload["count"], 2)
        self.assertEqual([e["text"] for e in payload["entries"]], ["晚的", "早的"])
        self.assertEqual(payload["query"], None)

    def test_forget_by_id(self) -> None:
        entry = _payload(_call(self.client, "remember", text="记错了的"))
        payload = _payload(_call(self.client, "forget", id=entry["id"]))
        self.assertEqual(payload["count"], 0)

    def test_bad_arguments_come_back_as_isError_not_as_an_exception(self) -> None:
        # 参数不对是**模型能自己改对**的事：回文本让它重试，别把这一轮打断。
        self.assertIn("非空字符串", _error_text(_call(self.client, "remember", text="  ")))
        self.assertIn("tags", _error_text(_call(self.client, "remember", text="x", tags="构图")))
        self.assertIn("字符串", _error_text(_call(self.client, "recall", query=7)))
        self.assertIn("没有 id", _error_text(_call(self.client, "forget", id="m-9")))
        self.assertIn("id", _error_text(_call(self.client, "forget")))

    def test_a_broken_store_shows_up_as_an_error_text(self) -> None:
        (self.dir / "memory.json").write_text("坏了", encoding="utf-8")
        broken = MemoryClient(MemoryStore(self.dir))
        self.assertIn(str(self.dir / "memory.json"), _error_text(_call(broken, "recall")))


def _make_host(memory: MemoryClient | None) -> StudioHost:
    """只挂记忆的最小宿主（MCP 一个都不拉）。"""
    extra = [memory] if memory is not None else []
    hub = McpHub([], extra_clients=extra)
    return StudioHost(hub, SkillCatalog(hub), memory=memory)


class HostMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-memory-")
        self.dir = Path(self._tmp.name)
        self.store = MemoryStore(self.dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_info_reports_where_the_memory_lives(self) -> None:
        info = _make_host(MemoryClient(self.store)).info({}, None)
        self.assertIs(info["memory"], True)
        self.assertEqual(info["memory_file"], str(self.dir / "memory.json"))
        self.assertEqual(info["memory_entries"], 0)
        self.assertIsNone(info["memory_error"])

    def test_info_says_so_when_memory_is_off(self) -> None:
        info = _make_host(None).info({}, None)
        self.assertIs(info["memory"], False)
        self.assertIsNone(info["memory_file"])
        self.assertIsNone(info["memory_entries"])

    def test_a_broken_file_does_not_block_the_handshake(self) -> None:
        # 记忆坏了不该让人连不上宿主：握手照旧，错误如实报在 memory_error 里。
        (self.dir / "memory.json").write_text("坏了", encoding="utf-8")
        info = _make_host(MemoryClient(MemoryStore(self.dir))).info({}, None)
        self.assertIs(info["memory"], True)
        self.assertIsNone(info["memory_entries"])
        self.assertIn("memory.json", info["memory_error"])

    def test_without_memory_the_prompt_is_the_plain_default(self) -> None:
        host = _make_host(None)
        self.assertEqual(host._prompt_source(), DEFAULT_SYSTEM_PROMPT)

    def test_with_memory_the_prompt_is_recomputed_every_time(self) -> None:
        host = _make_host(MemoryClient(self.store))
        source = host._prompt_source()
        self.assertTrue(callable(source))
        first = source()
        self.assertIn(MEMORY_PROMPT_RULES, first)
        self.assertIn("目前还没记住任何事", first)

        self.store.remember("用户喜欢方形构图")
        second = source()
        self.assertIn("用户喜欢方形构图", second)
        # 收尾要求还在最后一条（补充段不该把它挤掉）。
        self.assertTrue(second.rstrip().endswith("图片用返回的 url 原样给出。"))


class _FakeLLM:
    """只回一句话的假模型：把每次收到的 messages 原样记下来，好断言提示词。"""

    def __init__(self, reply: str = "好的") -> None:
        self.config = LLMConfig(base_url="http://127.0.0.1:9/v1", model="fake-model")
        self.reply = reply
        self.seen: list[list[ChatMessage]] = []

    async def complete(self, messages, _tools, *, cancel=None, on_retry=None) -> ChatMessage:
        self.seen.append(list(messages))
        return ChatMessage(role="assistant", content=self.reply)

    async def close(self) -> None:
        """没什么要关的。"""


class PromptRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_thing_just_remembered_is_in_the_next_turn_prompt(self) -> None:
        """记忆进提示词的真正闭环：这一轮记下，下一轮人设里就有 —— 不必等用户再问一次。"""
        with tempfile.TemporaryDirectory(prefix="comfy-studio-memory-") as tmp:
            store = MemoryStore(Path(tmp))
            hub = McpHub([], extra_clients=[MemoryClient(store)])
            await hub.start()
            llm = _FakeLLM()
            session = AgentSession(
                hub,
                hub.tools,
                llm=llm,
                system_prompt=lambda: compose_system_prompt(store.digest()),
            )

            await session.ask("帮我把这张图改一下")
            self.assertIs(llm.seen[0][0].role, "system")
            self.assertNotIn("方形构图", llm.seen[0][0].content)

            store.remember("用户喜欢方形构图")
            await session.ask("现在再帮我改一张")
            self.assertIn("方形构图", llm.seen[1][0].content)
            # 人设是**替换**而不是再插一条：system 消息永远只有开头那一条。
            self.assertEqual([m.role for m in llm.seen[1]].count("system"), 1)

    async def test_a_prompt_source_that_comes_out_empty_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="comfy-studio-memory-") as tmp:
            hub = McpHub([], extra_clients=[MemoryClient(MemoryStore(Path(tmp)))])
            await hub.start()
            with self.assertRaises(AgentError):
                AgentSession(hub, hub.tools, llm=_FakeLLM(), system_prompt=lambda: "   ")


class ComposePromptTests(unittest.TestCase):
    def test_no_sections_is_exactly_the_default_prompt(self) -> None:
        self.assertEqual(compose_system_prompt(), DEFAULT_SYSTEM_PROMPT)

    def test_the_closing_line_stays_last(self) -> None:
        text = compose_system_prompt("关于长期记忆：……")
        self.assertTrue(text.rstrip().endswith("图片用返回的 url 原样给出。"))
        self.assertLess(text.index("关于长期记忆"), text.index("图片用返回的 url"))

    def test_empty_sections_are_skipped(self) -> None:
        self.assertEqual(compose_system_prompt("", "  ", None), DEFAULT_SYSTEM_PROMPT)  # type: ignore[arg-type]
        self.assertNotIn("\n\n\n", compose_system_prompt("", "一段补充"))


if __name__ == "__main__":
    unittest.main()
