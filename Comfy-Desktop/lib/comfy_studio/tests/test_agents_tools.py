"""``comfy_studio.agent.catalog`` 与它在宿主里那两个方法（``agent/agents`` / ``agent/agent``）的测试。

纯本地：拿临时目录当智能体目录，不起子进程、不连模型。真起一次子进程走完整往返的那种
在 ``test_host_e2e.py`` 里。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_agents_tools -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from comfy_studio.agent import (
    BASE_SYSTEM_PROMPT,
    BUILTIN_PROFILES,
    CLOSING_SYSTEM_PROMPT,
    DEFAULT_SYSTEM_PROMPT,
    GENERAL_AGENT_ID,
    SUMMARY_CHARS,
    AgentCatalog,
    AgentCatalogError,
    AgentError,
)
from comfy_studio.mcp import McpHub
from comfy_studio.rpc import INVALID_PARAMS, RpcError
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog


def _make_host(agents: AgentCatalog | None = None) -> StudioHost:
    """只挂智能体目录的最小宿主（MCP 一个都不拉）。"""
    hub = McpHub([], extra_clients=[])
    return StudioHost(hub, SkillCatalog(hub), agents=agents)


def _write(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


class AgentCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-agents-")
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---- 内置那几项 -----------------------------------------------------

    def test_builtins_are_available_even_without_a_directory(self) -> None:
        # 用户一份文件都没放过（目录还不存在）也得有得选，头一个就是通用助手。
        listing = AgentCatalog(self.dir / "nope").scan()
        self.assertEqual(listing.problems, ())
        self.assertIsNone(listing.error)
        ids = [profile.id for profile in listing.profiles]
        self.assertEqual(ids[0], GENERAL_AGENT_ID)
        self.assertEqual(ids, [profile.id for profile in BUILTIN_PROFILES])
        self.assertEqual(listing.profiles[0].prompt, "", "通用助手不该带角色段")

    def test_builtin_ids_are_unique(self) -> None:
        ids = [profile.id for profile in BUILTIN_PROFILES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_builtins_only_carry_a_brief(self) -> None:
        # 内置写的是提要：一句说明 + 一小段角色，不是一整份搬过来的配置文档。
        for profile in BUILTIN_PROFILES:
            self.assertTrue(profile.summary, profile.id)
            self.assertLessEqual(len(profile.summary), SUMMARY_CHARS + 1, profile.id)
            self.assertLess(len(profile.prompt), 500, f"{profile.id} 的角色段像抄来的长文")

    # ---- 用户自己的文件 -------------------------------------------------

    def test_a_file_becomes_an_agent(self) -> None:
        _write(
            self.dir,
            "director.md",
            "# 我的导演\n> 一句话说明\n\n你是导演，先把镜头定下来。\n",
        )
        profile = AgentCatalog(self.dir).get("director")
        self.assertEqual(profile.name, "我的导演")
        self.assertEqual(profile.summary, "一句话说明")
        self.assertEqual(profile.prompt, "你是导演，先把镜头定下来。")
        self.assertFalse(profile.builtin)
        self.assertEqual(profile.file, "director.md")

    def test_name_and_summary_are_optional(self) -> None:
        _write(self.dir, "plain.md", "就一段正文，没有标题也没有说明。\n")
        profile = AgentCatalog(self.dir).get("plain")
        self.assertEqual(profile.name, "plain", "没写名字就用文件名")
        self.assertEqual(profile.summary, "")
        self.assertEqual(profile.prompt, "就一段正文，没有标题也没有说明。")

    def test_markdown_emphasis_is_stripped_from_the_summary(self) -> None:
        # 说明是给人看的一行字，** 这类记号留在下拉里只是噪点。
        _write(self.dir, "a.md", "# 甲\n> **定位：** 拆镜头\n\n正文\n")
        self.assertEqual(AgentCatalog(self.dir).get("a").summary, "定位： 拆镜头")

    def test_a_long_summary_is_cut_to_fit(self) -> None:
        _write(self.dir, "b.md", f"# 乙\n> {'长' * (SUMMARY_CHARS * 3)}\n\n正文\n")
        summary = AgentCatalog(self.dir).get("b").summary
        self.assertEqual(len(summary), SUMMARY_CHARS + 1)  # 尾巴那个省略号
        self.assertTrue(summary.endswith("…"))

    def test_scan_sees_a_file_dropped_in_later(self) -> None:
        catalog = AgentCatalog(self.dir)
        self.assertNotIn("later", [profile.id for profile in catalog.scan().profiles])
        _write(self.dir, "later.md", "# 后加的\n\n正文\n")
        # 不重启宿主也能认出来：每次扫描都读盘。
        self.assertIn("later", [profile.id for profile in catalog.scan().profiles])

    def test_only_markdown_files_are_picked_up(self) -> None:
        # 认 .md；目录里的笔记、导出的 json 不该悄悄变成智能体。
        _write(self.dir, "notes.txt", "# 不是智能体\n\n正文\n")
        (self.dir / "config.json").write_text('{"name": "也不是"}', encoding="utf-8")
        listing = AgentCatalog(self.dir).scan()
        ids = [profile.id for profile in listing.profiles]
        self.assertNotIn("notes", ids)
        self.assertNotIn("config", ids)
        self.assertEqual(listing.problems, ())

    # ---- 读不了的那些 ---------------------------------------------------

    def test_a_file_without_a_body_is_reported(self) -> None:
        # 只有标题和说明：这不能当成"通用助手"，得说清楚它缺什么。
        _write(self.dir, "empty.md", "# 空的\n> 就一句话\n")
        listing = AgentCatalog(self.dir).scan()
        self.assertNotIn("empty", [profile.id for profile in listing.profiles])
        self.assertEqual(len(listing.problems), 1)
        self.assertEqual(listing.problems[0].file, "empty.md")
        self.assertIn("人设正文", listing.problems[0].error)

    def test_an_undecodable_file_is_reported(self) -> None:
        (self.dir / "bin.md").write_bytes(b"\xff\xfe\x00\x01\x02")
        listing = AgentCatalog(self.dir).scan()
        self.assertEqual([problem.file for problem in listing.problems], ["bin.md"])
        self.assertIn("读不了", listing.problems[0].error)

    def test_a_name_clash_with_a_builtin_is_reported(self) -> None:
        # 内置的不能被顶掉：重名是一条错误（改个文件名就行），不是静默覆盖。
        _write(self.dir, f"{GENERAL_AGENT_ID}.md", "# 我才是通用\n\n正文\n")
        listing = AgentCatalog(self.dir).scan()
        general = next(p for p in listing.profiles if p.id == GENERAL_AGENT_ID)
        self.assertTrue(general.builtin)
        self.assertEqual(general.name, "通用助手")
        self.assertEqual([problem.file for problem in listing.problems], [f"{GENERAL_AGENT_ID}.md"])
        self.assertIn("重名", listing.problems[0].error)

    def test_one_broken_file_does_not_take_the_others_down(self) -> None:
        _write(self.dir, "good.md", "# 好的\n\n正文\n")
        _write(self.dir, "empty.md", "# 空的\n")
        listing = AgentCatalog(self.dir).scan()
        self.assertIn("good", [profile.id for profile in listing.profiles])
        self.assertEqual([problem.file for problem in listing.problems], ["empty.md"])

    def test_a_directory_path_that_is_a_file_is_reported(self) -> None:
        path = _write(self.dir, "not-a-dir.md", "正文\n")
        listing = AgentCatalog(path).scan()
        self.assertIsNotNone(listing.error)
        self.assertIn("不是目录", listing.error or "")
        self.assertEqual(
            [profile.id for profile in listing.profiles],
            [profile.id for profile in BUILTIN_PROFILES],
        )

    def test_get_reports_the_ids_it_knows(self) -> None:
        with self.assertRaises(AgentCatalogError) as caught:
            AgentCatalog(self.dir).get("no-such")
        self.assertIn("no-such", str(caught.exception))
        self.assertIn(GENERAL_AGENT_ID, str(caught.exception))


class HostAgentTests(unittest.IsolatedAsyncioTestCase):
    """宿主的两个方法：清单怎么报、切了之后人设怎么变、出毛病时说什么。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-agents-")
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _host(self) -> StudioHost:
        return _make_host(AgentCatalog(self.dir))

    def test_info_reports_the_current_agent(self) -> None:
        info = self._host().info({}, None)
        self.assertEqual(info["agent"], GENERAL_AGENT_ID)
        self.assertEqual(info["agent_name"], "通用助手")
        self.assertIsNone(info["agent_error"])
        self.assertEqual(info["agents_dir"], str(self.dir))
        self.assertIsNone(info["agents_error"])

    async def test_listing_never_ships_the_prompt(self) -> None:
        _write(self.dir, "a.md", "# 甲\n\n我是甲。\n")
        listing = await self._host().agent_agents({}, None)  # type: ignore[arg-type]
        self.assertEqual(listing["current"], GENERAL_AGENT_ID)
        self.assertIsNone(listing["missing"])
        self.assertEqual(listing["dir"], str(self.dir))
        ids = [agent["id"] for agent in listing["agents"]]
        self.assertIn(GENERAL_AGENT_ID, ids)
        self.assertIn("a", ids)
        # 人设正文不往面板搬：清单只说"有哪些、叫什么"。
        self.assertTrue(all("prompt" not in agent for agent in listing["agents"]))

    async def test_switch_changes_the_prompt_every_session_will_use(self) -> None:
        _write(self.dir, "a.md", "# 甲\n> 我是甲\n\n只讲一句话：先定镜头。\n")
        host = self._host()
        source = host._prompt_source()
        before = source()
        self.assertEqual(before, DEFAULT_SYSTEM_PROMPT)

        result = await host.agent_agent({"agent": "a"}, None)  # type: ignore[arg-type]
        self.assertEqual(result, {"agent": "a", "changed": True, "name": "甲", "error": None})

        # 用的还是**同一份 source**（会话建好时拿到的就是它）：换智能体不用重建会话，
        # 下一轮 ask 重算人设时就换了。
        after = source()
        self.assertIn("先定镜头", after)
        self.assertNotEqual(before, after)
        # 底座规则（开头）与收尾要求（结尾）都还在，只是中间多了一段角色。
        self.assertTrue(after.startswith(BASE_SYSTEM_PROMPT))
        self.assertIn(CLOSING_SYSTEM_PROMPT, after)

    async def test_switching_back_restores_the_plain_prompt(self) -> None:
        _write(self.dir, "a.md", "# 甲\n\n我是甲。\n")
        host = self._host()
        await host.agent_agent({"agent": "a"}, None)  # type: ignore[arg-type]
        await host.agent_agent({"agent": GENERAL_AGENT_ID}, None)  # type: ignore[arg-type]
        self.assertEqual(host._prompt_source()(), DEFAULT_SYSTEM_PROMPT)

    async def test_reading_the_current_agent_does_not_change_it(self) -> None:
        result = await self._host().agent_agent({}, None)  # type: ignore[arg-type]
        self.assertEqual(
            result,
            {"agent": GENERAL_AGENT_ID, "changed": False, "name": "通用助手", "error": None},
        )

    async def test_an_unknown_or_empty_agent_is_refused(self) -> None:
        host = self._host()
        for bad in ("no-such", "", "   ", 7, ["a"]):
            with self.assertRaises(RpcError) as caught:
                await host.agent_agent({"agent": bad}, None)  # type: ignore[arg-type]
            self.assertEqual(caught.exception.code, INVALID_PARAMS)
        self.assertIsNone(host.default_agent, "被拒的值不该改掉当前智能体")

    async def test_a_vanished_file_is_reported_and_the_turn_refuses(self) -> None:
        path = _write(self.dir, "a.md", "# 甲\n\n我是甲。\n")
        host = self._host()
        await host.agent_agent({"agent": "a"}, None)  # type: ignore[arg-type]
        path.unlink()

        info = host.info({}, None)
        self.assertEqual(info["agent"], "a")
        self.assertIsNone(info["agent_name"], "文件没了就别说它叫甲")
        self.assertIn("a", info["agent_error"])

        listing = await host.agent_agents({}, None)  # type: ignore[arg-type]
        self.assertIn("不在了", listing["missing"] or "")

        # 人设读不出来时**当场报错**，不悄悄退回通用助手 —— 用户写的那份被吞掉才是最坏的结果。
        with self.assertRaises(AgentError) as caught:
            host._prompt_source()()
        self.assertIn("a", str(caught.exception))

    async def test_a_broken_file_stays_visible_in_the_listing(self) -> None:
        _write(self.dir, "good.md", "# 好的\n\n正文\n")
        _write(self.dir, "empty.md", "# 空的\n")
        listing = await self._host().agent_agents({}, None)  # type: ignore[arg-type]
        self.assertIn("good", [agent["id"] for agent in listing["agents"]])
        self.assertEqual([problem["file"] for problem in listing["problems"]], ["empty.md"])
