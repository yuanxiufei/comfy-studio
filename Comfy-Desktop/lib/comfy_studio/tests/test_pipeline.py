"""``comfy_studio.pipeline`` 的测试：四道静态守卫 + 一整条编排行为。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_pipeline -v

**这些守卫为什么必须有**：``STAGE_AGENT`` / ``STAGE_ARTIFACT`` 是阶段表与另外两张表之间的
**连接**。它们错了不会崩，只会静默地做错事，而且每种错法都不响：

* 智能体 id 拼错 —— ``plan()`` 会拦（行为用例里有），但得有人先跑到那儿；
* **落点写错** —— 会**建出一个新目录**，产物藏在面板看不见的地方，报告上一切正常；
* 阶段表加了 S8 而这里没跟上 —— 新阶段**永远不会被跑**，也没人知道少了东西。

三类都在这儿机械核对。行为用例一律用 :class:`FakeRunner`：**不联网、不花钱**，
把顺序、断点续跑、落盘、失败即停整条走一遍。
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

import unittest.mock

from comfy_studio import server as server_module
from comfy_studio.rpc import INTERNAL_ERROR, RpcError
from comfy_studio.server import StudioHost, _pipeline_tool_config

from comfy_studio import pipeline as pipeline_module
from comfy_studio.agent.catalog import AgentCatalog
from comfy_studio.mcp import McpError
from comfy_studio.pipeline import (
    OUTLINE_JSON,
    PIPELINE_SERVER,
    PIPELINE_TOOLS,
    RUN_AGREE,
    RUN_DECLINE,
    STATE_REL,
    STATE_VERSION,
    STAGE_TASKS,
    STAGE_TASK_BY_CODE,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    NovelToVideoPipeline,
    PipelineClient,
    PipelineError,
    main,
    plan_payload,
    state_payload,
)
from comfy_studio.projects_spec import PROJECT_DIRS, STAGE_ORDER, create_project

#: S0 那次要回一份**带合格 ```json 块**的正文 —— 机器可读大纲就从那儿取。
S0_TEXT = (
    "# 分集大纲与三表\n\n正文正文。\n\n"
    '```json\n{"集数": ["EP01"], "角色": ["CHR_001"]}\n```\n'
)


class FakeRunner:
    """假的模型出口。记下每一段收到什么，按需在指定那一段炸掉。"""

    def __init__(self, *, fail_on: str | None = None, s0_text: str = S0_TEXT) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail_on = fail_on
        self.s0_text = s0_text
        self.closed = False

    async def __call__(self, task, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((task.code, system_prompt, user_prompt))
        if self.fail_on == task.code:
            raise RuntimeError("模型炸了")
        if task.code == "S0":
            return self.s0_text
        return f"# {task.name}\n\n正文。\n"

    async def close(self) -> None:
        self.closed = True


@contextlib.contextmanager
def temp_project(episodes: int = 2):
    """临时目录里按规范建一个真项目。"""
    with tempfile.TemporaryDirectory() as tmp:
        create_project("测试剧", episodes=episodes, root=tmp, log=lambda *a, **k: None)
        yield Path(tmp) / "测试剧"


def _write_novel(project: Path, text: str = "第一章 主角在雨里醒来。") -> Path:
    novel = project.parent / "原著.txt"
    novel.write_text(text, encoding="utf-8")
    return novel


class StaticGuardTest(unittest.TestCase):
    """不建项目、不碰模型：核对三张表拧得对不对。"""

    def test_covers_every_stage_and_nothing_else(self):
        self.assertEqual([task.code for task in STAGE_TASKS], list(STAGE_ORDER))

    def test_every_agent_id_is_a_real_preset(self):
        """空的 id 是合法的（S7 不用模型），**拼错的不是**。"""
        known = {profile.id for profile in AgentCatalog().scan().profiles}
        self.assertTrue(known, "智能体目录一个都没扫到，这条守卫就白设了")
        for task in STAGE_TASKS:
            if not task.agent_id:
                continue
            with self.subTest(stage=task.code):
                self.assertIn(
                    task.agent_id,
                    known,
                    f"{task.code} 指的 {task.agent_id!r} 不在随包预置的智能体里",
                )

    def test_every_artifact_parent_is_a_known_landing(self):
        """落点的父目录必须是 ``PROJECT_DIRS`` 里的一项，否则产物没人找得到。"""
        for task in STAGE_TASKS:
            with self.subTest(stage=task.code):
                parent = os.path.dirname(task.artifact).replace("\\", "/")
                self.assertIn(parent, PROJECT_DIRS, f"{task.code} 的落点 {task.artifact!r} 不在清单里")

    def test_no_hardcoded_absolute_paths_in_source(self):
        """不许写死机器绝对路径：写死的害处不是报错，是**换台机器就静默跳过**。"""
        src = Path(pipeline_module.__file__).read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", src), "pipeline.py 里出现了盘符")
        self.assertNotIn("d:\\code", src.lower())

    def test_brief_belongs_to_whoever_does_the_work(self):
        """有智能体就得写清要它产出什么；不用模型的段不该有产出说明。"""
        for task in STAGE_TASKS:
            with self.subTest(stage=task.code):
                if task.agent_id:
                    self.assertTrue(task.brief.strip(), f"{task.code} 有智能体却没写 brief")
                else:
                    self.assertFalse(task.brief.strip(), f"{task.code} 不用模型却写了 brief")

    def test_task_codes_resolve_through_the_index(self):
        for code in STAGE_ORDER:
            self.assertIs(STAGE_TASK_BY_CODE[code].code, STAGE_TASK_BY_CODE[code].code)
            self.assertEqual(STAGE_TASK_BY_CODE[code].code, code)


class PlanTest(unittest.TestCase):
    def test_plan_is_pure(self):
        """``plan()`` 只读不写：面板点开看一眼，不该动项目、不该调模型。"""
        with temp_project() as project:
            runner = FakeRunner()
            pipe = NovelToVideoPipeline(project, _write_novel(project), runner=runner)
            before = sorted(str(p.relative_to(project)) for p in project.rglob("*"))
            tasks = pipe.plan()
            self.assertEqual(len(tasks), len(STAGE_ORDER))
            self.assertEqual(runner.calls, [])
            self.assertEqual(
                sorted(str(p.relative_to(project)) for p in project.rglob("*")),
                before,
                "plan() 动了项目文件",
            )

    def test_plan_reports_missing_agent_instead_of_running_without_one(self):
        """包被裁掉 / 人设文件被删时**当场报错**，不能拿空人设去跑。

        临时把目录扫描换成"一个人设都没有"来造这个局面 —— 真去删包内文件会把别的用例
        一起搞坏，而且它就不是"夹具"该干的事了。
        """
        with temp_project() as project:
            pipe = NovelToVideoPipeline(project, None, runner=FakeRunner())
            empty = SimpleNamespace(profiles=[], problems=[], error="")
            with unittest.mock.patch.object(AgentCatalog, "scan", return_value=empty):
                with self.assertRaises(PipelineError) as caught:
                    pipe.plan()
            self.assertIn("不在清单里", str(caught.exception))


class RunTest(unittest.TestCase):
    def test_runs_every_stage_and_writes_artifacts(self):
        with temp_project() as project:
            runner = FakeRunner()
            pipe = NovelToVideoPipeline(project, _write_novel(project), runner=runner, episodes=3)
            report = asyncio.run(pipe.run())

            self.assertTrue(report["ok"], report)
            self.assertEqual(report["ran"], list(STAGE_ORDER))
            self.assertEqual(report["not_ran"], [])
            for task in STAGE_TASKS:
                self.assertTrue((project / task.artifact).is_file(), f"{task.code} 的产物没落盘")
            # S7 不用模型，所以模型只该被叫 7 次
            self.assertEqual(
                [code for code, _, _ in runner.calls],
                [task.code for task in STAGE_TASKS if task.agent_id],
            )
            state = json.loads((project / STATE_REL).read_text(encoding="utf-8"))
            self.assertEqual(state["version"], STATE_VERSION)
            self.assertEqual(set(state["stages"]), set(STAGE_ORDER))
            self.assertEqual(
                {rec["status"] for rec in state["stages"].values()}, {STATUS_DONE}
            )

    def test_prompts_carry_the_persona_and_the_novel(self):
        """人设与原著真的进了提示词 —— 否则"编排"就只是顺序调用。"""
        with temp_project() as project:
            runner = FakeRunner()
            novel = _write_novel(project, "第一章 只有这一段能对上。")
            asyncio.run(NovelToVideoPipeline(project, novel, runner=runner).run())

            prompt_of = {code: (sys_p, user_p) for code, sys_p, user_p in runner.calls}
            self.assertIn("只有这一段能对上", prompt_of["S0"][1])
            for code, (sys_p, user_p) in prompt_of.items():
                with self.subTest(stage=code):
                    self.assertTrue(sys_p.strip(), f"{code} 的系统提示词是空的")
                    self.assertIn(STAGE_TASK_BY_CODE[code].artifact, user_p)
            # 人设是各段自己的，不是同一份
            self.assertNotEqual(prompt_of["S4"][0], prompt_of["S5"][0])

    def test_upstream_artifacts_flow_into_later_stages(self):
        with temp_project() as project:
            runner = FakeRunner()
            asyncio.run(NovelToVideoPipeline(project, _write_novel(project), runner=runner).run())
            prompt_of = {code: user for code, _, user in runner.calls}
            self.assertNotIn("上游产物", prompt_of["S0"])
            self.assertIn("上游产物", prompt_of["S5"])
            self.assertIn(STAGE_TASK_BY_CODE["S4"].artifact, prompt_of["S5"])

    def test_render_gap_is_flagged_not_silently_called_done(self):
        """文本写出去了 ≠ 这一段完成了：渲染缺口必须在报告里看得见。"""
        with temp_project() as project:
            runner = FakeRunner()
            report = asyncio.run(
                NovelToVideoPipeline(project, None, runner=runner).run()
            )
            self.assertEqual(report["render_required"], ["S2", "S3", "S5", "S6"])
            by_code = {s["code"]: s for s in report["stages"]}
            for code in ("S2", "S3", "S5", "S6"):
                self.assertTrue(by_code[code]["render_pending"], code)
                self.assertIn("引擎侧", by_code[code]["note"])
            for code in ("S0", "S1", "S4", "S7"):
                self.assertFalse(by_code[code]["render_pending"], code)

    def test_second_run_skips_everything(self):
        """断点续跑：跑过的段一次都不该再叫模型。"""
        with temp_project() as project:
            runner = FakeRunner()
            pipe = NovelToVideoPipeline(project, None, runner=runner)
            asyncio.run(pipe.run())
            calls = len(runner.calls)

            report = asyncio.run(pipe.run())
            self.assertEqual(len(runner.calls), calls, "断点续跑又调了模型")
            self.assertEqual({s["status"] for s in report["stages"]}, {STATUS_SKIPPED})
            self.assertTrue(report["ok"])

    def test_force_reruns_everything(self):
        with temp_project() as project:
            runner = FakeRunner()
            pipe = NovelToVideoPipeline(project, None, runner=runner)
            asyncio.run(pipe.run())
            calls = len(runner.calls)
            asyncio.run(pipe.run(force=True))
            self.assertEqual(len(runner.calls), calls * 2)

    def test_missing_artifact_reopens_the_stage(self):
        """账上写了 done、盘上却没了 —— 必须重跑，不能把空的阶段报成完成。"""
        with temp_project() as project:
            runner = FakeRunner()
            pipe = NovelToVideoPipeline(project, None, runner=runner)
            asyncio.run(pipe.run())
            calls = len(runner.calls)
            (project / STAGE_TASK_BY_CODE["S4"].artifact).unlink()
            report = asyncio.run(pipe.run())
            self.assertEqual(len(runner.calls), calls + 1)
            by_code = {s["code"]: s for s in report["stages"]}
            self.assertEqual(by_code["S4"]["status"], STATUS_DONE)
            self.assertEqual(by_code["S0"]["status"], STATUS_SKIPPED)

    def test_failure_stops_the_line_and_is_reported(self):
        with temp_project() as project:
            runner = FakeRunner(fail_on="S4")
            pipe = NovelToVideoPipeline(project, None, runner=runner)
            report = asyncio.run(pipe.run())

            self.assertFalse(report["ok"])
            last = report["stages"][-1]
            self.assertEqual(last["code"], "S4")
            self.assertEqual(last["status"], STATUS_FAILED)
            self.assertIn("模型炸了", last["error"])
            # 后面的段依赖这一段，不许硬着头皮往下跑
            self.assertEqual(report["not_ran"], ["S5", "S6", "S7"])
            self.assertEqual(pipe.state()["stages"]["S4"]["status"], STATUS_FAILED)

    def test_stage_outcomes_land_in_state_account(self):
        with temp_project() as project:
            runner = FakeRunner()
            pipe = NovelToVideoPipeline(project, None, runner=runner)
            asyncio.run(pipe.run(from_code="S0", to_code="S1"))
            state = pipe.state()
            self.assertEqual(set(state["stages"]), {"S0", "S1"})

    def test_slice_limits_what_runs(self):
        with temp_project() as project:
            runner = FakeRunner()
            report = asyncio.run(
                NovelToVideoPipeline(project, None, runner=runner).run(
                    from_code="S1", to_code="S3"
                )
            )
            self.assertEqual(report["ran"], ["S1", "S2", "S3"])
            self.assertEqual(report["not_ran"], [])
            self.assertEqual([code for code, _, _ in runner.calls], ["S1", "S2", "S3"])

    def test_reversed_slice_errors(self):
        with temp_project() as project:
            pipe = NovelToVideoPipeline(project, None, runner=FakeRunner())
            with self.assertRaises(PipelineError):
                asyncio.run(pipe.run(from_code="S5", to_code="S1"))

    def test_unknown_stage_code_errors_and_lists_the_valid_ones(self):
        with temp_project() as project:
            pipe = NovelToVideoPipeline(project, None, runner=FakeRunner())
            with self.assertRaises(PipelineError) as caught:
                asyncio.run(pipe.run(from_code="S9"))
            self.assertIn("S9", str(caught.exception))

    def test_missing_novel_fails_loudly(self):
        """静默给空串的失效模式是模型凭空编一部剧，而报告上一切正常。"""
        with temp_project() as project:
            with self.assertRaises(PipelineError):
                NovelToVideoPipeline(
                    project, project.parent / "没有这本.txt", runner=FakeRunner()
                )

    def test_unreadable_novel_fails_loudly(self):
        with temp_project() as project:
            novel = project.parent / "原著.txt"
            novel.write_bytes(b"\xff\xfe\x00\x00\x41")  # 不是 UTF-8
            pipe = NovelToVideoPipeline(project, novel, runner=FakeRunner())
            with self.assertRaises(PipelineError) as caught:
                asyncio.run(pipe.run(from_code="S0", to_code="S0"))
            self.assertIn("原著读不动", str(caught.exception))

    def test_bad_episodes_errors(self):
        with temp_project() as project:
            with self.assertRaises(PipelineError):
                NovelToVideoPipeline(project, None, runner=FakeRunner(), episodes=0)

    def test_state_version_mismatch_errors_instead_of_guessing(self):
        with temp_project() as project:
            pipe = NovelToVideoPipeline(project, None, runner=FakeRunner())
            pipe.state_path.parent.mkdir(parents=True, exist_ok=True)
            pipe.state_path.write_text('{"version": 99, "stages": {}}', encoding="utf-8")
            with self.assertRaises(PipelineError) as caught:
                asyncio.run(pipe.run())
            self.assertIn("99", str(caught.exception))

    def test_injected_runner_is_not_closed_by_the_pipeline(self):
        """注入的出口归调用方管；流水线不许把它随手关掉 —— 调用方还要接着用。"""
        with temp_project() as project:
            runner = FakeRunner()
            asyncio.run(
                NovelToVideoPipeline(project, None, runner=runner).run(
                    from_code="S1", to_code="S1"
                )
            )
            self.assertFalse(runner.closed)

    def test_second_run_on_the_same_project_is_refused(self):
        """同一项目不许两条同时跑。

        靠"两条都写完再看谁赢"是发现不了的：那种坏法**不报错**，只是进度账少记一条、
        模型调用多烧一倍。所以这里真把第一条卡在半路（``Blocking`` 跑到 S0 就等着），
        再看第二条的结果。
        """
        with temp_project() as project:
            started = asyncio.Event()
            release = asyncio.Event()

            class Blocking:
                async def __call__(self, task, system_prompt, user_prompt):
                    started.set()
                    await release.wait()
                    return "# 正文\n\n正文。\n"

            async def scenario() -> str:
                first = NovelToVideoPipeline(project, None, runner=Blocking())
                flying = asyncio.ensure_future(first.run(from_code="S0", to_code="S0"))
                await started.wait()
                self.assertIn(str(project), pipeline_module.RUNNING_PROJECTS)
                second = NovelToVideoPipeline(project, None, runner=FakeRunner())
                with self.assertRaises(PipelineError) as caught:
                    await second.run(from_code="S0", to_code="S0")
                release.set()
                await flying
                # **门要放回去**：不然第一条跑完之后这个项目就再也开不了了，
                # 而现象是"点一下说在跑，等多久还是说在跑"。
                self.assertNotIn(str(project), pipeline_module.RUNNING_PROJECTS)
                return str(caught.exception)

            message = asyncio.run(scenario())
            self.assertIn("已经有一条流水线在跑", message)

            # 门收干净了：同一个项目再来一条照跑（这一段上次跑过，这次是 skipped）。
            again = asyncio.run(NovelToVideoPipeline(project, None, runner=FakeRunner()).run())
            self.assertEqual(again["stages"][0]["status"], STATUS_SKIPPED)

    def test_a_stage_that_never_answers_times_out_and_stops_the_line(self):
        """收不住的模型要变成**一条写着阶段与用时的失败**，不是"外面看着永远卡住"。

        请求是非流式的：回第一个字节之前没有任何生命迹象，所以"还在编"与"已经挂了"
        在外面长得一样。这条上限是唯一能把两者分开的东西。
        """

        class Hanging:
            async def __call__(self, task, system_prompt, user_prompt):
                await asyncio.sleep(30)
                return "不该跑到这儿"

        with temp_project() as project:
            report = asyncio.run(
                NovelToVideoPipeline(project, None, runner=Hanging(), stage_timeout=0.05).run()
            )
            first = report["stages"][0]
            self.assertEqual(first["status"], STATUS_FAILED)
            self.assertIn("超过单段上限", first["error"] or "")
            self.assertIn("S0", first["error"] or "")
            self.assertFalse(report["ok"])
            # 失败即停：后面的段一段都不许跑。
            self.assertEqual(len(report["not_ran"]), len(STAGE_ORDER) - 1)

    def test_stage_timeout_env_is_read_and_a_bad_value_errors(self):
        """上限写错了要**当场报错**，不悄悄回落到默认值 —— 那会让人以为开关没用。"""
        with temp_project() as project:
            with unittest.mock.patch.dict(
                os.environ, {pipeline_module.STAGE_TIMEOUT_ENV: "600"}
            ):
                pipeline = NovelToVideoPipeline(project, None, runner=FakeRunner())
                self.assertEqual(pipeline.stage_timeout, 600.0)
            for bad in ("0", "-1", "一会儿"):
                with self.subTest(bad=bad):
                    with unittest.mock.patch.dict(
                        os.environ, {pipeline_module.STAGE_TIMEOUT_ENV: bad}
                    ):
                        with self.assertRaises(PipelineError) as caught:
                            NovelToVideoPipeline(project, None, runner=FakeRunner())
                        self.assertIn("必须是正数", str(caught.exception))


class OutlineTest(unittest.TestCase):
    """S0 的机器可读大纲 —— 这是 ``MIGRATIONS`` 专门警告过的那条路径。"""

    def test_outline_is_written_when_absent(self):
        with temp_project() as project:
            asyncio.run(NovelToVideoPipeline(project, None, runner=FakeRunner()).run())
            data = json.loads((project / OUTLINE_JSON).read_text(encoding="utf-8"))
            self.assertEqual(data, {"集数": ["EP01"], "角色": ["CHR_001"]})

    def test_existing_outline_is_never_overwritten(self):
        """人改过的大纲不许被模型新生成的覆盖 —— 这正是 MIGRATIONS 警告的失效模式。"""
        with temp_project() as project:
            outline = project / OUTLINE_JSON
            outline.parent.mkdir(parents=True, exist_ok=True)
            outline.write_text('{"人改过": true}', encoding="utf-8")

            report = asyncio.run(NovelToVideoPipeline(project, None, runner=FakeRunner()).run())
            self.assertEqual(outline.read_text(encoding="utf-8"), '{"人改过": true}')
            self.assertIn("没动它", report["stages"][0]["note"])

    def test_missing_json_block_is_reported_not_faked(self):
        with temp_project() as project:
            runner = FakeRunner(s0_text="# 大纲\n\n正文，没有 JSON 块。\n")
            report = asyncio.run(NovelToVideoPipeline(project, None, runner=runner).run())
            self.assertFalse((project / OUTLINE_JSON).exists())
            self.assertIn("没落盘", report["stages"][0]["note"])

    def test_broken_json_block_is_reported_not_faked(self):
        with temp_project() as project:
            runner = FakeRunner(s0_text="# 大纲\n\n```json\n{这不是 JSON}\n```\n")
            report = asyncio.run(NovelToVideoPipeline(project, None, runner=runner).run())
            self.assertFalse((project / OUTLINE_JSON).exists())
            self.assertIn("没落盘", report["stages"][0]["note"])

    def test_non_object_json_block_is_rejected(self):
        with temp_project() as project:
            runner = FakeRunner(s0_text='# 大纲\n\n```json\n["EP01"]\n```\n')
            report = asyncio.run(NovelToVideoPipeline(project, None, runner=runner).run())
            self.assertFalse((project / OUTLINE_JSON).exists())
            self.assertIn("顶层不是对象", report["stages"][0]["note"])


class CheckStageTest(unittest.TestCase):
    """S7 是机械体检，不是合规审核 —— 报告里必须自己说清这一点。"""

    def test_check_report_says_it_is_not_a_compliance_review(self):
        with temp_project() as project:
            asyncio.run(NovelToVideoPipeline(project, None, runner=FakeRunner()).run())
            body = (project / STAGE_TASK_BY_CODE["S7"].artifact).read_text(encoding="utf-8")
            self.assertIn("不是合规审核", body)
            self.assertIn("待引擎侧渲染", body)
            self.assertIn("S5", body)


class EventTest(unittest.TestCase):
    def test_events_tell_the_frontend_what_is_happening(self):
        with temp_project() as project:
            events: list[dict] = []
            asyncio.run(
                NovelToVideoPipeline(
                    project, None, runner=FakeRunner(), on_event=events.append
                ).run(from_code="S6", to_code="S7")
            )
            phases = [e["phase"] for e in events]
            self.assertEqual(phases[0], "start")
            self.assertEqual(phases[-1], "finished")
            # 每段两条：开工一条、收工一条（收工那条才带状态与产物路径）
            self.assertEqual(len([p for p in phases if p == "stage_start"]), 2)
            self.assertEqual(len([p for p in phases if p == "stage"]), 2)
            self.assertEqual([e["code"] for e in events if e["phase"] == "stage"], ["S6", "S7"])
            self.assertTrue(all(e["type"] == "pipeline" for e in events))


class CliTest(unittest.TestCase):
    def test_plan_prints_and_does_not_run(self):
        with temp_project() as project:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["--project", str(project), "--plan"])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            for code in STAGE_ORDER:
                self.assertIn(code, out)
            self.assertIn("引擎侧渲染", out)
            self.assertFalse((project / STATE_REL).exists())

    def test_bad_project_exits_two_without_traceback(self):
        with temp_project() as project:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                rc = main(["--project", str(project.parent / "没有这个项目"), "--plan"])
            self.assertEqual(rc, 2)
            self.assertIn("错误", err.getvalue())


class RpcWiringTest(unittest.TestCase):
    """RPC 三件套：注册过、形状对、纯查询不碰模型。

    **不拉起整个 ``StudioHost``**（那要 ComfyUI 路径、引擎 venv 一堆环境，测试会变成环境考试）。
    这里只把三个处理器当函数喂一个最小的 ``self`` —— 它们实际用到的只有 ``novels`` 与
    ``_make_pipeline`` / ``_pipeline_novel_path`` 两个方法。
    """

    @staticmethod
    def _host(novels=None):
        host = SimpleNamespace(novels=novels)
        host._pipeline_novel_path = types.MethodType(StudioHost._pipeline_novel_path, host)
        host._make_pipeline = types.MethodType(StudioHost._make_pipeline, host)
        return host

    def test_methods_are_registered(self):
        """注册漏一条，面板就永远点不到它，而且**不报错** —— 所以拿源码机械核一遍。"""
        src = Path(server_module.__file__).read_text(encoding="utf-8")
        for name in ("pipeline/plan", "pipeline/run", "pipeline/state"):
            self.assertIn(f'self.server.on("{name}"', src, f"{name} 没注册")

    def test_plan_returns_the_stage_list(self):
        with temp_project() as project:
            got = StudioHost.pipeline_plan(self._host(), {"name": str(project)}, None)
            self.assertEqual([s["code"] for s in got["stages"]], list(STAGE_ORDER))
            self.assertEqual(got["render_required"], ["S2", "S3", "S5", "S6"])
            self.assertEqual(got["state"], {})
            self.assertFalse((project / STATE_REL).exists(), "plan 不该落盘")

    def test_state_on_a_fresh_project_is_empty_not_an_error(self):
        with temp_project() as project:
            got = StudioHost.pipeline_state(self._host(), {"name": str(project)}, None)
            self.assertEqual(got["stages"], {})
            self.assertEqual(got["version"], STATE_VERSION)

    def test_unknown_novel_name_is_rejected_with_the_available_ones(self):
        shelf = SimpleNamespace(
            list=lambda limit: {"novels": [{"name": "另一本.txt", "path": "x", "text": True}]}
        )
        with self.assertRaises(RpcError) as caught:
            StudioHost.pipeline_plan(
                self._host(novels=shelf), {"name": "随便", "novel": "没有这本.txt"}, None
            )
        self.assertIn("另一本.txt", str(caught.exception))

    def test_missing_project_name_is_rejected(self):
        with self.assertRaises(RpcError):
            StudioHost.pipeline_plan(self._host(), {}, None)

    def test_non_text_novel_is_rejected(self):
        shelf = SimpleNamespace(
            list=lambda limit: {"novels": [{"name": "图.png", "path": "x", "text": False}]}
        )
        with self.assertRaises(RpcError) as caught:
            StudioHost.pipeline_plan(
                self._host(novels=shelf), {"name": "随便", "novel": "图.png"}, None
            )
        self.assertIn("不是 txt/md", str(caught.exception))

    def test_slice_rejects_wrong_shapes(self):
        for bad in ({"from": 5}, {"to": ["S1"]}, {"force": "yes"}):
            with self.subTest(args=bad), self.assertRaises(RpcError):
                StudioHost._pipeline_slice(bad)

    def test_slice_reads_the_three_switches(self):
        self.assertEqual(
            StudioHost._pipeline_slice({"from": "S1", "to": "S3", "force": True}),
            ("S1", "S3", True),
        )
        self.assertEqual(StudioHost._pipeline_slice({}), (None, None, False))


class FakeReview:
    """假的审核通道（鸭子型，形状照 :meth:`comfy_studio.review.ReviewChannel.ask`）。

    工具层只调 ``ask`` 这一个方法，所以这里不必拉起 ``ReviewChannel`` —— 真通道要面板回话，
    测试里没人接。
    """

    def __init__(self, answer: str = RUN_AGREE) -> None:
        self.answer = answer
        self.asked: list[tuple[str, tuple[str, ...]]] = []

    async def ask(
        self,
        question: str,
        options: list[str] | None = None,
        *,
        cancel=None,
        timeout=None,
    ) -> str:
        self.asked.append((question, tuple(options or ())))
        return self.answer


def _shelf(name: str = "书.txt", *, text: bool = True, path: str = ""):
    """假的原文库：只满足 :func:`comfy_studio.novels.resolve_novel` 用到的那一面。"""
    return SimpleNamespace(
        list=lambda limit: {"novels": [{"name": name, "path": path, "text": text}]}
    )


class PipelineToolTest(unittest.TestCase):
    """对话里那两张流水线工具：``pipeline__plan`` 与 ``pipeline__run``。

    **不联网、不花钱、不拉起 StudioHost**：模型出口是 :class:`FakeRunner`，审核通道是
    :class:`FakeReview`。这一组钉的是"什么情况下**不**动手"（plan 只读、run 没点头不跑），
    以及工具与面板**形状同源**。
    """

    @staticmethod
    def _client(*, runner=None, review=None, novels=None) -> PipelineClient:
        return PipelineClient(
            novels=novels,
            review=review,
            runner=runner if runner is not None else FakeRunner(),
        )

    @staticmethod
    def _call(client: PipelineClient, name: str, arguments: dict) -> dict:
        return asyncio.run(client.call_tool(name, arguments))

    @staticmethod
    def _text(result: dict) -> str:
        return result["content"][0]["text"]

    # ---- 工具表本身 -----------------------------------------------------

    def test_the_table_is_exactly_plan_and_run(self):
        tools = asyncio.run(self._client().list_tools())
        self.assertEqual(
            [tool.qualified_name for tool in tools], ["pipeline__plan", "pipeline__run"]
        )
        for tool in tools:
            with self.subTest(tool=tool.name):
                self.assertEqual(tool.server, PIPELINE_SERVER)
                self.assertEqual(tool.input_schema["required"], ["name"])
                self.assertIn("name", tool.input_schema["properties"])

    def test_descriptions_do_not_leak_the_repository_layout(self):
        """描述与参数表是给模型看的：仓库路径对模型没用，而且会随仓库搬家变成假话。"""
        blob = json.dumps(
            [
                {"description": spec.description, "schema": spec.input_schema}
                for spec in PIPELINE_TOOLS
            ],
            ensure_ascii=False,
        )
        self.assertIsNone(re.search(r"[A-Za-z]:[\\/]", blob), "工具描述里出现了盘符")
        for needle in ("lib/comfy_studio", "Comfy-Desktop", "AI漫剧", "07-智能体运行时"):
            self.assertNotIn(needle, blob)

    # ---- plan：只看不动 -------------------------------------------------

    def test_plan_tool_is_read_only(self):
        with temp_project() as project:
            runner = FakeRunner()
            client = self._client(runner=runner, novels=_shelf())
            before = sorted(str(p.relative_to(project)) for p in project.rglob("*"))
            got = self._call(client, "plan", {"name": str(project)})
            self.assertFalse(got["isError"], self._text(got))
            self.assertEqual(runner.calls, [], "plan 不该调模型")
            self.assertEqual(
                sorted(str(p.relative_to(project)) for p in project.rglob("*")),
                before,
                "plan 动了项目文件",
            )

    def test_plan_and_the_panel_return_one_shape(self):
        """面板（``pipeline/plan``）与工具回的是同一份：各拼一份不会报错，只会让两边说法打架。"""
        with temp_project() as project:
            pipe = NovelToVideoPipeline(project, None, runner=FakeRunner())
            payload = json.loads(self._text(self._call(self._client(), "plan", {"name": str(project)})))
            self.assertEqual(payload, plan_payload(pipe))
            self.assertEqual(payload["state"], state_payload(pipe)["stages"])

    # ---- run：先问人，再动手 --------------------------------------------

    def test_run_asks_before_spending_a_cent(self):
        """没点头就一个字节都不写 —— 这是这张工具最要紧的一条。"""
        with temp_project() as project:
            runner = FakeRunner()
            review = FakeReview(RUN_DECLINE)
            got = self._call(
                self._client(runner=runner, review=review),
                "run",
                {"name": str(project), "from": "S0", "to": "S1"},
            )
            self.assertTrue(got["isError"])
            self.assertIn(RUN_AGREE, self._text(got), "得告诉模型怎么才能跑起来")
            self.assertEqual(review.asked[0][1], (RUN_AGREE, RUN_DECLINE))
            self.assertEqual(runner.calls, [], "没点头却调了模型")
            self.assertFalse((project / STATE_REL).exists(), "没点头却落了状态账")

    def test_run_without_a_channel_refuses(self):
        """接不上人就不跑：这一步花的钱与时间都不是能默许的。"""
        with temp_project() as project:
            runner = FakeRunner()
            got = self._call(self._client(runner=runner, review=None), "run", {"name": str(project)})
            self.assertTrue(got["isError"])
            self.assertIn("确认", self._text(got))
            self.assertEqual(runner.calls, [])
            self.assertFalse((project / STATE_REL).exists())

    def test_run_after_a_nod_really_runs(self):
        with temp_project() as project:
            runner = FakeRunner()
            got = self._call(
                self._client(runner=runner, review=FakeReview(RUN_AGREE)),
                "run",
                {"name": str(project), "from": "S0", "to": "S1"},
            )
            self.assertFalse(got["isError"], self._text(got))
            report = json.loads(self._text(got))
            self.assertTrue(report["ok"], report)
            self.assertEqual(report["ran"], ["S0", "S1"])
            self.assertEqual([code for code, _sys, _user in runner.calls], ["S0", "S1"])
            self.assertTrue((project / STATE_REL).is_file())

    def test_confirm_summary_says_what_it_will_cost(self):
        """确认文案要说清跑几段、哪几段跑完还得渲染 —— 用户才好点头。"""
        with temp_project() as project:
            review = FakeReview(RUN_DECLINE)
            self._call(self._client(review=review), "run", {"name": str(project)})
            question = review.asked[0][0]
            self.assertIn("测试剧", question)
            self.assertIn("S2", question, "要渲染的段没写出来")
            self.assertIn("引擎侧渲染", question)

    # ---- 错误与形状 -----------------------------------------------------

    def test_unknown_tool_name_is_a_protocol_error(self):
        with self.assertRaises(McpError) as caught:
            self._call(self._client(), "pipeline", {})
        self.assertIn("plan", str(caught.exception))

    def test_wrong_argument_shapes_are_rejected(self):
        for bad in (
            {},
            {"name": "   "},
            {"name": "x", "episodes": 0},
            {"name": "x", "episodes": True},
            {"name": "x", "from": 5},
            {"name": "x", "force": "yes"},
            {"name": "x", "novel": 7},
        ):
            with self.subTest(args=bad):
                got = self._call(self._client(), "plan", bad)
                self.assertTrue(got["isError"], bad)

    def test_novel_is_resolved_through_the_shelf(self):
        with temp_project() as project:
            novel = _write_novel(project)
            got = self._call(
                self._client(novels=_shelf("书.txt", path=str(novel))),
                "plan",
                {"name": str(project), "novel": "书.txt"},
            )
            self.assertFalse(got["isError"], self._text(got))
            self.assertEqual(json.loads(self._text(got))["novel"], str(novel))

    def test_unknown_novel_is_reported_with_the_available_ones(self):
        with temp_project() as project:
            got = self._call(
                self._client(novels=_shelf("另一本.txt")),
                "plan",
                {"name": str(project), "novel": "没有这本.txt"},
            )
            self.assertTrue(got["isError"])
            self.assertIn("另一本.txt", self._text(got))

    def test_novel_without_a_shelf_is_reported(self):
        with temp_project() as project:
            got = self._call(
                self._client(novels=None), "plan", {"name": str(project), "novel": "书.txt"}
            )
            self.assertTrue(got["isError"])
            self.assertIn("原文", self._text(got))


class ToolWiringTest(unittest.TestCase):
    """机械守卫：工具表真挂上了宿主，而且面板与工具**共用同一份形状**。"""

    @staticmethod
    def _src() -> str:
        return Path(server_module.__file__).read_text(encoding="utf-8")

    def test_the_host_mounts_the_pipeline_client(self):
        src = self._src()
        self.assertIn("PipelineClient(", src, "流水线工具没挂进工具表")
        self.assertIn("config_provider=", src, "没接上当前生效的那套模型配置")

    def test_the_panel_and_the_tools_share_one_payload(self):
        """server.py 里自己再拼一遍形状就走偏了 —— 那份形状只在 pipeline.py 里。"""
        src = self._src()
        self.assertIn("plan_payload(pipeline)", src)
        self.assertIn("state_payload(pipeline)", src)
        self.assertIn("resolve_novel(", src, "按名字取原文又出了一份规则")

    def test_the_model_config_comes_from_the_host(self):
        """``run`` 取的模型配置与面板聊天同一份；取不到时翻成**工具错误**。

        ``RpcError`` 冒出去会穿出 MCP 循环，用户看到的就不是一句说得清的话，而是一次莫名的调用
        失败 —— 工具层只认 :class:`PipelineError`（``PipelineClient.call_tool`` 的 ``except``）。
        """
        sentinel = SimpleNamespace(model="哨兵")
        host = SimpleNamespace(_session_config=lambda: sentinel)
        self.assertIs(_pipeline_tool_config([host]), sentinel)

        def broken():
            raise RpcError(INTERNAL_ERROR, "settings.json 读不出来")

        with self.assertRaises(PipelineError) as caught:
            _pipeline_tool_config([SimpleNamespace(_session_config=broken)])
        self.assertIn("settings.json", str(caught.exception))

        with self.assertRaises(PipelineError) as empty:
            _pipeline_tool_config([])
        self.assertIn("宿主", str(empty.exception))


if __name__ == "__main__":
    unittest.main()
