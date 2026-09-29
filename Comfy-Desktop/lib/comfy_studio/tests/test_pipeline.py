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
    DEFAULT_JOURNAL_LIMIT,
    MAX_JOURNAL_LIMIT,
    OUTLINE_JSON,
    PIPELINE_SERVER,
    PIPELINE_TOOLS,
    RUN_AGREE,
    RUN_DECLINE,
    STATE_REL,
    STATE_VERSION,
    STAGE_ARTIFACT,
    STAGE_RENDER,
    STAGE_RENDER_NOTE,
    STAGE_TASKS,
    STAGE_TASK_BY_CODE,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED,
    NovelToVideoPipeline,
    PipelineClient,
    PipelineError,
    journal_payload,
    main,
    plan_payload,
    read_ledger,
    state_payload,
    steps_payload,
)
from comfy_studio.projects import ProjectLibrary
from comfy_studio.projects_spec import (
    PROJECT_DIRS,
    STAGE_ORDER,
    STEP_ORDER,
    WORKBENCH_STEPS,
    ProjectError,
    create_project,
    step_gaps,
    step_of_stage,
    step_stages,
)

#: S0 那次要回一份**带合格 ```json 块**的正文 —— 机器可读大纲就从那儿取。
S0_TEXT = (
    "# 分集大纲与三表\n\n正文正文。\n\n"
    '```json\n{"集数": ["EP01"], "角色": ["CHR_001"]}\n```\n'
)


def _stage(report: dict, code: str) -> dict:
    """报告里某一段那一行。

    **按代码取，不按下标** —— 链前面补了 S0a（原文解析）之后，``report["stages"][0]``
    已经不是 S0 了。这种错法不响：断言照样过，只是断在了另一段上。
    """
    return {s["code"]: s for s in report["stages"]}[code]


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

    def test_render_bindings_match_the_stages_that_need_a_render(self):
        """``STAGE_RENDER`` 的键集必须与 ``needs_render=True`` 的那几段**一字不差**。

        两种错法都不响，而且坏在不同地方：少一条 = 卡片画不出「去出图」、用户又得自己在引擎
        那 12 张里认（认错只会出成另一张图）；多一条 = 卡片摆出一个"出图"按钮，而这一步的
        完成判定压根不看图 —— 跑出来的东西没人验，也没人知道该不该验。

        ``_check_render_bindings()`` 在 ``_build_tasks()`` 里已经拦了一道（表**本来就**配错），
        这条再钉一次，钉的是"以后有人改了 needs_render 却忘了同步那张表"。
        """
        pending = {code for code, (_, needs) in STAGE_ARTIFACT.items() if needs}
        self.assertEqual(set(STAGE_RENDER), pending)
        self.assertEqual(
            sorted(code for code, task in STAGE_TASK_BY_CODE.items() if task.needs_render),
            sorted(pending),
        )
        for task in STAGE_TASKS:
            with self.subTest(stage=task.code):
                self.assertEqual(
                    task.needs_render,
                    bool(task.render_lands),
                    f"{task.code} 的 needs_render 与它绑的图对不上：说不用出图却绑了图，"
                    "或者反过来说要出图却没绑",
                )
                for target, land in task.render_lands:
                    self.assertRegex(target, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                    # 落点必须在**这一段自己的**体检目录里：不在的话，图出得成、也确实落了盘，
                    # 只是落在体检不看的地方 —— 卡片上「还缺图」永远不消，人以为白跑一趟。
                    self.assertIn(
                        land,
                        task.check_dirs,
                        f"{task.code} 给 {target} 绑的落点 {land!r} 不在体检目录里",
                    )
                self.assertEqual(
                    task.render_targets,
                    tuple(target for target, _ in task.render_lands),
                    f"{task.code} 的 render_targets 与 render_lands 分家了",
                )
        # 附言挂在没绑图的那一段就成了没人看得见的一句话。
        self.assertLessEqual(set(STAGE_RENDER_NOTE), set(STAGE_RENDER))

    def test_render_binding_guard_rejects_a_landing_outside_the_check_dirs(self):
        """落点写歪了要**当场**说，而不是等跑完一遍才看出来图落错了地方。

        ``_check_render_bindings`` 是模块导入时跑的（``STAGE_TASKS = _build_tasks()``），
        所以这条在真实运行里的表现是"程序起不来" —— 这正是想要的：表配错了，一动就报。
        """
        with unittest.mock.patch.dict(
            pipeline_module.STAGE_RENDER,
            {"S2": (("character-sheet", "09_SHOTS"),)},
        ):
            with self.assertRaises(PipelineError) as caught:
                pipeline_module._check_render_bindings()
        message = str(caught.exception)
        self.assertIn("09_SHOTS", message)
        self.assertIn("不在这一段的体检目录里", message)

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
            # 链上的**第一段**没有上游产物可塞（它是最前面那一段，不是"S0"这个代号 ——
            # S0a 原文解析补进来之后就不是 S0 了）。
            self.assertNotIn("上游产物", prompt_of[STAGE_ORDER[0]])
            self.assertIn("上游产物", prompt_of["S5"])
            self.assertIn(STAGE_TASK_BY_CODE["S4"].artifact, prompt_of["S5"])

    def test_render_gap_is_flagged_not_silently_called_done(self):
        """文本写出去了 ≠ 这一段完成了：渲染缺口必须在报告里看得见。"""
        with temp_project() as project:
            runner = FakeRunner()
            report = asyncio.run(
                NovelToVideoPipeline(project, None, runner=runner).run()
            )
            self.assertEqual(report["render_required"], ["S2", "S3", "S5", "S6", "S7a"])
            by_code = {s["code"]: s for s in report["stages"]}
            for code in ("S2", "S3", "S5", "S6", "S7a"):
                self.assertTrue(by_code[code]["render_pending"], code)
                self.assertIn("引擎侧", by_code[code]["note"])
                # "还缺"还得说得出"缺的那几张叫什么"：面板上那枚「去出图」全靠这一条
                # （认错图不会报错，只会出成另一张 —— 见 STAGE_RENDER 的注释）。
                self.assertEqual(
                    by_code[code]["render_targets"], [t for t, _ in STAGE_RENDER[code]], code
                )
                # 还得说得出"出完存进哪一格"：面板把它拼上项目根当 output_dir，图才落进
                # 体检真看的目录（不然卡片上「还缺图」永远不消）。
                self.assertEqual(by_code[code]["render_lands"], dict(STAGE_RENDER[code]), code)
                self.assertEqual(by_code[code]["render_note"], STAGE_RENDER_NOTE.get(code, ""), code)
            for code in ("S0a", "S0", "S1", "S4", "S4a", "S7"):
                self.assertFalse(by_code[code]["render_pending"], code)
                self.assertEqual(by_code[code]["render_targets"], [], code)
                self.assertEqual(by_code[code]["render_lands"], {}, code)

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
            self.assertEqual(report["not_ran"], ["S4a", "S5", "S6", "S7", "S7a"])
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
            # 按代码取 S0：第一趟是 `--from S0 --to S0` 只跑了它，而这一趟是整条链，
            # 排在它前面的 S0a 是这一趟才跑的 —— "上次跑过的段这次 skipped"说的是 S0。
            by_code = {s["code"]: s for s in again["stages"]}
            self.assertEqual(by_code["S0"]["status"], STATUS_SKIPPED)

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
            self.assertEqual(first["code"], STAGE_ORDER[0], "失败的是链上第一段")
            self.assertEqual(first["status"], STATUS_FAILED)
            self.assertIn("超过单段上限", first["error"] or "")
            self.assertIn(STAGE_ORDER[0], first["error"] or "")
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
            self.assertIn("没动它", _stage(report, "S0")["note"])

    def test_missing_json_block_is_reported_not_faked(self):
        with temp_project() as project:
            runner = FakeRunner(s0_text="# 大纲\n\n正文，没有 JSON 块。\n")
            report = asyncio.run(NovelToVideoPipeline(project, None, runner=runner).run())
            self.assertFalse((project / OUTLINE_JSON).exists())
            self.assertIn("没落盘", _stage(report, "S0")["note"])

    def test_broken_json_block_is_reported_not_faked(self):
        with temp_project() as project:
            runner = FakeRunner(s0_text="# 大纲\n\n```json\n{这不是 JSON}\n```\n")
            report = asyncio.run(NovelToVideoPipeline(project, None, runner=runner).run())
            self.assertFalse((project / OUTLINE_JSON).exists())
            self.assertIn("没落盘", _stage(report, "S0")["note"])

    def test_non_object_json_block_is_rejected(self):
        with temp_project() as project:
            runner = FakeRunner(s0_text='# 大纲\n\n```json\n["EP01"]\n```\n')
            report = asyncio.run(NovelToVideoPipeline(project, None, runner=runner).run())
            self.assertFalse((project / OUTLINE_JSON).exists())
            self.assertIn("顶层不是对象", _stage(report, "S0")["note"])


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


class WorkbenchStepsTest(unittest.TestCase):
    """八步工作台的读数：每一步凭什么算"做完了"。

    面板左侧那八步全靠一份 :func:`steps_payload`。它错的方式全是**静默**的：预置空表被
    算成产物、阶段被判成"下一步该做这个"、某一步的落点根本没进回话 —— 界面上都只是
    "看起来正常"。所以这里逐条钉，不靠肉眼看面板。
    """

    @staticmethod
    def _pair(project: Path) -> tuple[NovelToVideoPipeline, ProjectLibrary]:
        """项目 + 它所在的库（:func:`temp_project` 已经把项目建在 ``project.parent`` 下了）。"""
        return (
            NovelToVideoPipeline(project, None, runner=FakeRunner()),
            ProjectLibrary(project.parent),
        )

    @staticmethod
    def _step(report: dict, key: str) -> dict:
        return {step["key"]: step for step in report["steps"]}[key]

    @classmethod
    def _stage(cls, report: dict, key: str, code: str) -> dict:
        return {s["code"]: s for s in cls._step(report, key)["stages"]}[code]

    def test_the_eight_steps_cover_the_eleven_stages_exactly_once(self):
        """八步 × 11 阶段：**每个阶段恰好归一步**，一段都不许漏、不许两边挂。

        ``step_gaps()`` 为空就是这条（它同时看住落点覆盖与 ``needs`` 指向）。漏一段的
        失效模式是那一段从导航里**消失**，挂两段的失效模式是它被跑两遍 —— 两种都不报错。
        """
        self.assertEqual(step_gaps(), ())
        seen = [code for step in WORKBENCH_STEPS for code in step.stages]
        self.assertEqual(sorted(seen), sorted(STAGE_ORDER))
        self.assertEqual(len(seen), len(set(seen)))

    def test_stages_inside_a_step_keep_the_machine_order(self):
        """一步之内的阶段顺序**一律按 ``STAGE_ORDER``**，不按步骤表里写的先后。

        步骤的先后是**创作顺序**，12 段生产链不是照着它排的：``prompts``（提示词）那一步
        盖着 S2 与 S3，它们排在 S4（分镜）**后面**，却在生产链里排在前面。面板照步骤表
        摆导航是对的，**跑**却必须照生产链 —— 两处各排一遍的失效模式是：面板写着
        "先 S3 再 S2"，跑起来正好颠倒。
        """
        self.assertEqual(step_stages("prompts"), ("S2", "S3"))
        self.assertEqual(step_stages("cut"), ("S7", "S7a"))
        self.assertEqual(step_stages("style"), (), "没有机器阶段的一步该回空元组")
        self.assertEqual(step_of_stage("S3"), "prompts")
        for step in WORKBENCH_STEPS:
            order = [STAGE_ORDER.index(code) for code in step_stages(step.key)]
            self.assertEqual(order, sorted(order), f"{step.key} 的阶段不是生产链顺序")
        with self.assertRaises(ProjectError):
            step_stages("没有这一步")

    def test_a_fresh_project_is_empty_and_seed_tables_are_not_progress(self):
        """刚建完项目：八步**一步都不算做过**，空模板只记在 ``seed_count`` 里。

        这是这次改造最容易做错的一处：``06_对白/``、``07_素材归档/``、``05_流程/``
        里躺着建项目写下的空模板。把它们算进 ``count``，用户一步没跑就会看见
        "对白与旁白 · 已有 2 份产物"，而盘上全是空表。
        """
        with temp_project() as project:
            pipe, library = self._pair(project)
            got = steps_payload(pipe, library)

            self.assertEqual(got["gaps"], [], "八步与阶段表/落点表分家了")
            self.assertEqual([s["key"] for s in got["steps"]], list(STEP_ORDER))
            self.assertEqual({s["state"] for s in got["steps"]}, {"empty"})
            self.assertEqual(got["current"], STEP_ORDER[0], "该指向第一步")
            for step in got["steps"]:
                self.assertEqual(step["count"], 0, f"{step['key']} 把空表算成了产物")
            seeds = {step["key"]: step["seed_count"] for step in got["steps"]}
            self.assertEqual(seeds["dialogue"], 2, "两张空对白表没被认出来")
            self.assertEqual(seeds["cut"], 1, "预置的单元进度台账没被认出来")
            self.assertEqual(seeds["parse"], 2, "素材归档的两张空表没被认出来")
            self.assertEqual(got["render_required"], ["S2", "S3", "S5", "S6", "S7a"])

    def test_a_step_turns_done_only_when_its_own_stages_are(self):
        """做完两段，头两步才变 ``done``，``current`` 跟着挪到第三步。

        面板拿 ``current`` 当"你现在该看哪一步"。自己再数一遍就会与这里的判据分家 ——
        分家之后面板指的那一步跟跑出来的那一步不是同一步，而两边看着都对。
        """
        with temp_project() as project:
            pipe, library = self._pair(project)
            asyncio.run(pipe.run(from_code="S0a", to_code="S1"))  # 解析 + 建纲/资产设计
            got = steps_payload(pipe, library)

            self.assertEqual(self._step(got, "parse")["state"], "done")
            self.assertEqual(self._step(got, "cast")["state"], "done")
            self.assertEqual(got["current"], "board")
            self.assertEqual(self._step(got, "board")["blocked_by"], [])
            self.assertTrue(self._step(got, "board")["ready"])
            # 上游与"上游里还欠哪几个"是两件事：面板只摆欠的那几个。
            self.assertEqual(self._step(got, "dialogue")["blocked_by"], ["board"])
            self.assertFalse(self._step(got, "dialogue")["ready"])
            self.assertEqual(self._step(got, "style")["blocked_by"], [])

    def test_a_render_stage_is_text_not_done(self):
        """只有文本那半的阶段记 ``text``，**不记 ``done``**。

        S2（出图）把提示词写出去了，图还在引擎侧排队。面板若把它说成"做完了"，
        用户就会以为资产已经出好了 —— 这正是"文本写出去了 ≠ 这一段完成了"。
        """
        with temp_project() as project:
            pipe, library = self._pair(project)
            asyncio.run(pipe.run(from_code="S2", to_code="S2"))
            got = steps_payload(pipe, library)

            stage = self._stage(got, "prompts", "S2")
            self.assertEqual(stage["state"], "text")
            self.assertTrue(stage["needs_render"], "这一步该说清实质产物要引擎侧渲染")
            self.assertEqual(self._step(got, "prompts")["state"], "partial")

    def test_an_artifact_that_vanished_is_missing_not_done(self):
        """账上写着跑完了、产物却不在 —— 报 ``missing``，不报 ``done``。

        与 :meth:`NovelToVideoPipeline._done_before` 同一个判据：盘上没有就是没做完。
        这里报成完成的话，面板会指着一个空落点说"这一步已经好了"。
        """
        with temp_project() as project:
            pipe, library = self._pair(project)
            asyncio.run(pipe.run(from_code="S4a", to_code="S4a"))
            self.assertEqual(self._stage(steps_payload(pipe, library), "dialogue", "S4a")["state"], "done")

            (project / STAGE_TASK_BY_CODE["S4a"].artifact).unlink()
            got = steps_payload(pipe, library)
            self.assertEqual(self._stage(got, "dialogue", "S4a")["state"], "missing")
            self.assertNotEqual(self._step(got, "dialogue")["state"], "done")

    def test_every_step_hands_over_its_own_landings(self):
        """每一步都把**自己那几个落点**交出来，一份都不省（空目录也要交）。

        省掉空落点的失效模式：面板上少一格，而用户不知道"这一步该往哪放东西"。
        这几条断言与 :func:`step_gaps` 是搭档：一个盯表、一个盯回话。
        """
        with temp_project() as project:
            pipe, library = self._pair(project)
            got = steps_payload(pipe, library)

            handed = [landing["rel"] for step in got["steps"] for landing in step["landings"]]
            self.assertEqual(handed, [rel for step in WORKBENCH_STEPS for rel in step.landings])
            self.assertEqual(sorted(handed), sorted(PROJECT_DIRS), "落点没盖满")
            for step in got["steps"]:
                for landing in step["landings"]:
                    self.assertTrue(landing["exists"], landing["rel"])
                    self.assertTrue(landing["title"], f"{landing['rel']} 没给人看的名字")
                    self.assertIsInstance(landing["files"], list)

    def test_reading_the_rail_costs_nothing(self):
        """看一眼**不花钱、不动盘**：与 :func:`plan_payload` 同一个保证。"""
        with temp_project() as project:
            library = ProjectLibrary(project.parent)
            runner = FakeRunner()
            pipe = NovelToVideoPipeline(project, None, runner=runner)
            before = sorted(str(p.relative_to(project)) for p in project.rglob("*"))
            steps_payload(pipe, library)
            self.assertEqual(runner.calls, [])
            self.assertFalse((project / STATE_REL).exists(), "读导航把进度账写出来了")
            self.assertEqual(
                sorted(str(p.relative_to(project)) for p in project.rglob("*")), before
            )


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
    这里只把三个处理器当函数喂一个最小的 ``self`` —— 它们实际用到的只有 ``novels`` / ``projects``
    与 ``_make_pipeline`` / ``_pipeline_novel_path`` / ``_pipeline_roots`` 三个方法。
    ``projects=None`` 就代表"宿主没挂项目目录"：这时项目名原样交给流水线，产物根不另算。
    """

    @staticmethod
    def _host(novels=None, projects=None):
        host = SimpleNamespace(novels=novels, projects=projects)
        host._pipeline_novel_path = types.MethodType(StudioHost._pipeline_novel_path, host)
        host._pipeline_roots = types.MethodType(StudioHost._pipeline_roots, host)
        host._make_pipeline = types.MethodType(StudioHost._make_pipeline, host)
        return host

    def test_methods_are_registered(self):
        """注册漏一条，面板就永远点不到它，而且**不报错** —— 所以拿源码机械核一遍。"""
        src = Path(server_module.__file__).read_text(encoding="utf-8")
        for name in (
            "pipeline/plan",
            "pipeline/run",
            "pipeline/state",
            "pipeline/steps",
            "journal/list",
        ):
            self.assertIn(f'self.server.on("{name}"', src, f"{name} 没注册")

    def test_steps_returns_the_eight_step_rail(self):
        """面板左侧那八步从这一条来：它要有 ``current``、要有八步、要与阶段表对齐。"""
        with temp_project() as project:
            host = self._host()
            host.projects = ProjectLibrary(project.parent)
            host._projects = types.MethodType(StudioHost._projects, host)
            got = StudioHost.pipeline_steps(host, {"name": str(project)}, None)
            self.assertEqual([s["key"] for s in got["steps"]], list(STEP_ORDER))
            self.assertEqual(got["gaps"], [])
            self.assertEqual(got["order"], list(STEP_ORDER))
            self.assertEqual(got["current"], STEP_ORDER[0])

    def test_plan_returns_the_stage_list(self):
        with temp_project() as project:
            got = StudioHost.pipeline_plan(self._host(), {"name": str(project)}, None)
            self.assertEqual([s["code"] for s in got["stages"]], list(STAGE_ORDER))
            self.assertEqual(got["render_required"], ["S2", "S3", "S5", "S6", "S7a"])
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


class JournalTest(unittest.TestCase):
    """记录页（``journal/list``）：把各项目的账摊平成一条时间倒序的流水。

    **这一页最容易出的两种错都不响**：把读不动的账读成"没跑过"（于是几百条记录凭空消失），
    或者一条读不出来就让整页空白。所以这里专门喂坏账、喂非对象的 json、喂根目录里的杂项文件。
    """

    @staticmethod
    def _host(projects=None):
        host = SimpleNamespace(projects=projects)
        host._projects = types.MethodType(StudioHost._projects, host)
        return host

    @staticmethod
    def _ledger(project: Path, stages: dict, updated: str = "") -> None:
        path = project / STATE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"version": STATE_VERSION, "updated": updated, "stages": stages},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @contextlib.contextmanager
    def _root(self):
        """一个只有项目根、没有别的临时目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            yield Path(tmp)

    def test_a_root_without_projects_is_empty_not_an_error(self):
        with self._root() as root:
            got = journal_payload(ProjectLibrary(root))
            self.assertTrue(got["exists"])
            self.assertEqual(got["projects"], 0)
            self.assertEqual(got["entries"], [])
            self.assertEqual(got["matched"], 0)
            self.assertFalse(got["truncated"])

    def test_an_absent_root_is_reported_as_not_existing(self):
        with self._root() as root:
            got = journal_payload(ProjectLibrary(root / "还没建过"))
            self.assertFalse(got["exists"])
            self.assertEqual(got["entries"], [])

    def test_entries_are_flattened_and_sorted_newest_first(self):
        with self._root() as root:
            self._ledger(
                root / "甲剧",
                {
                    "S0a": {"status": STATUS_DONE, "at": "2026-09-28T10:00:00", "artifact": "a.md"},
                    "S1": {"status": STATUS_FAILED, "at": "2026-09-28T11:00:00", "error": "超时"},
                },
                updated="2026-09-28T11:00:00",
            )
            self._ledger(
                root / "乙剧",
                {"S0a": {"status": STATUS_SKIPPED, "at": "2026-09-27T09:00:00"}},
                updated="2026-09-27T09:00:00",
            )
            got = journal_payload(ProjectLibrary(root))
            self.assertEqual(got["projects"], 2)
            self.assertEqual(got["matched"], 3)
            self.assertEqual(got["updated"], "2026-09-28T11:00:00")
            self.assertEqual(
                [(e["project"], e["code"]) for e in got["entries"]],
                [("甲剧", "S1"), ("甲剧", "S0a"), ("乙剧", "S0a")],
            )
            first = got["entries"][0]
            self.assertEqual(first["status"], STATUS_FAILED)
            self.assertEqual(first["error"], "超时")
            self.assertEqual(first["name"], "资产设计", "阶段中文名要带上，语言包里没有时兜底")
            self.assertEqual(got["entries"][1]["artifact"], "a.md")

    def test_entries_without_a_time_go_last_and_keep_the_chain_order(self):
        """老账（或手写的账）里可能没记时间。它们排最后，且仍按链上的先后摆。"""
        with self._root() as root:
            self._ledger(
                root / "甲剧",
                {
                    "S1": {"status": STATUS_DONE},
                    "S0a": {"status": STATUS_DONE},
                    "S0": {"status": STATUS_DONE, "at": "2026-09-28T10:00:00"},
                },
            )
            got = journal_payload(ProjectLibrary(root))
            self.assertEqual([e["code"] for e in got["entries"]], ["S0", "S0a", "S1"])

    def test_a_broken_ledger_is_listed_but_does_not_empty_the_page(self):
        """**最要紧的一条**：一份坏账不能让另外几百条记录凭空消失。"""
        with self._root() as root:
            self._ledger(root / "好剧", {"S0a": {"status": STATUS_DONE, "at": "2026-09-28T10:00:00"}})
            bad = root / "坏剧" / STATE_REL
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_text("{不是 json", encoding="utf-8")
            got = journal_payload(ProjectLibrary(root))
            self.assertEqual([e["project"] for e in got["entries"]], ["好剧"])
            self.assertEqual(len(got["problems"]), 1)
            self.assertEqual(got["problems"][0]["project"], "坏剧")
            self.assertIn("状态账读不动", got["problems"][0]["error"])

    def test_a_ledger_of_the_wrong_version_is_reported_not_guessed(self):
        with self._root() as root:
            path = root / "老剧" / STATE_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"version": 1, "stages": {"S0": {"status": "done"}}}', encoding="utf-8")
            got = journal_payload(ProjectLibrary(root))
            self.assertEqual(got["entries"], [])
            self.assertIn("版本不认", got["problems"][0]["error"])

    def test_a_ledger_that_is_not_an_object_says_what_it_is(self):
        """非对象（手改坏成数组）时要报"版本不认且是 None"，不能抛 AttributeError ——
        那句英文的 ``list object has no attribute get`` 会把真正的病因盖掉。"""
        with self._root() as root:
            path = root / "坏剧" / STATE_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaises(PipelineError) as caught:
                read_ledger(path)
            self.assertIn("版本不认", str(caught.exception))
            self.assertNotIn("AttributeError", str(caught.exception))

    def test_loose_files_in_the_root_are_not_counted_as_projects(self):
        """``.DS_Store`` 那种文件、以及点开头的目录，都不该被当成一部剧。"""
        with self._root() as root:
            (root / ".DS_Store").write_text("x", encoding="utf-8")
            (root / "备注.txt").write_text("x", encoding="utf-8")
            (root / ".git").mkdir()
            self._ledger(root / "好剧", {"S0a": {"status": STATUS_DONE, "at": "2026-09-28T10:00:00"}})
            got = journal_payload(ProjectLibrary(root))
            self.assertEqual(got["projects"], 1)
            self.assertEqual(len(got["entries"]), 1)

    def test_limit_truncates_but_matched_stays_the_total(self):
        """面板要靠 ``matched`` 与 ``len(entries)`` 两个数说清"还有多少没显示"。"""
        with self._root() as root:
            self._ledger(
                root / "甲剧",
                {
                    code: {"status": STATUS_DONE, "at": f"2026-09-2{index + 1}T00:00:00"}
                    for index, code in enumerate(("S0a", "S0", "S1", "S2"))
                },
            )
            got = journal_payload(ProjectLibrary(root), "", 2)
            self.assertEqual(len(got["entries"]), 2)
            self.assertEqual(got["matched"], 4)
            self.assertTrue(got["truncated"])
            self.assertEqual(got["limit"], 2)

    def test_query_filters_by_project_name(self):
        with self._root() as root:
            self._ledger(root / "甲剧", {"S0a": {"status": STATUS_DONE, "at": "2026-09-28T10:00:00"}})
            self._ledger(root / "乙剧", {"S0a": {"status": STATUS_DONE, "at": "2026-09-27T10:00:00"}})
            got = journal_payload(ProjectLibrary(root), "甲")
            self.assertEqual(got["projects"], 1)
            self.assertEqual([e["project"] for e in got["entries"]], ["甲剧"])

    def test_read_ledger_treats_a_missing_file_as_empty_not_an_error(self):
        with self._root() as root:
            ledger = read_ledger(root / "没有" / "state.json")
            self.assertEqual(ledger["stages"], {})
            self.assertEqual(ledger["version"], STATE_VERSION)

    # ---- RPC 那一层 -----------------------------------------------------

    def test_the_rpc_is_registered(self):
        src = Path(server_module.__file__).read_text(encoding="utf-8")
        self.assertIn('self.server.on("journal/list"', src)

    def test_the_rpc_goes_through_the_project_library(self):
        with self._root() as root:
            self._ledger(root / "甲剧", {"S0a": {"status": STATUS_DONE, "at": "2026-09-28T10:00:00"}})
            host = self._host(ProjectLibrary(root))
            got = StudioHost.journal_list(host, {}, None)
            self.assertEqual([e["project"] for e in got["entries"]], ["甲剧"])

    def test_the_rpc_without_a_project_root_says_so(self):
        with self.assertRaises(RpcError) as caught:
            StudioHost.journal_list(self._host(), {}, None)
        self.assertIn("项目管理", str(caught.exception))

    def test_the_rpc_rejects_wrong_shapes(self):
        for bad in ({"name": 7}, {"limit": 0}, {"limit": MAX_JOURNAL_LIMIT + 1}, {"limit": "多"}):
            with self.subTest(args=bad), self.assertRaises(RpcError):
                StudioHost.journal_list(self._host(ProjectLibrary(Path("."))), bad, None)

    def test_the_rpc_default_limit_is_the_module_constant(self):
        """上限在 ``pipeline.py`` 里，RPC 层不另抄一份 —— 抄了就会两边分家。"""
        src = Path(server_module.__file__).read_text(encoding="utf-8")
        self.assertIn("DEFAULT_JOURNAL_LIMIT", src)
        self.assertIn("journal_payload(", src)
        self.assertGreaterEqual(DEFAULT_JOURNAL_LIMIT, 1)
        self.assertGreater(MAX_JOURNAL_LIMIT, DEFAULT_JOURNAL_LIMIT)


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
        self.assertIn("steps_payload(pipeline,", src)
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
