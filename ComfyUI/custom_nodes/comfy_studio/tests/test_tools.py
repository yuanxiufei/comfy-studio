"""MCP 工具集：工具表形状、JSON Schema、每个 handler 的行为。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from ..engine import EngineError, MODEL_PROBES
from ..mcp.tools import Tool, build_tools, error_result, schema_for, skill_entry, text_result
from ..skills import SkillRegistry, load_skills, WORKFLOWS_DIR
from ..skills.render import RENDER_TARGETS, WORKFLOWS_ENV, RenderError, find_target
from ..skills.types import SkillParam
from .support import FakeEngine, WORKFLOW, make_skill


def registry_of(skills: tuple[Any, ...]) -> SkillRegistry:
    """只有内存里这几份 skill 的视图（工具测试不碰磁盘）。"""
    return SkillRegistry.in_memory(skills)

GENERIC_TOOLS = [
    "comfy_list_models",
    "comfy_list_model_folders",
    "comfy_list_skills",
    "comfy_run_skill",
    "comfy_save_skill",
    "comfy_submit_workflow",
    "comfy_get_history",
    "comfy_get_queue",
    "comfy_interrupt",
    "comfy_list_renders",
    "comfy_render",
]


def tool_by_name(tools: list[Tool], name: str) -> Tool:
    found = next((t for t in tools if t.name == name), None)
    if found is None:
        raise AssertionError(f"工具表里没有 {name}；现有: {[t.name for t in tools]}")
    return found


def as_json(result: dict[str, Any]) -> Any:
    """取出工具返回里的文本并解析成 JSON（模型看到的就是这段文本）。"""
    return json.loads(result["content"][0]["text"])


class ToolResultTest(unittest.TestCase):
    def test_text_result_wraps_strings_and_json(self) -> None:
        self.assertEqual(text_result("hi"), {"content": [{"type": "text", "text": "hi"}]})
        listed = text_result([1, {"a": 2}])
        self.assertEqual(as_json(listed), [1, {"a": 2}])
        self.assertFalse(listed.get("isError"))

    def test_text_result_never_crashes_on_odd_objects(self) -> None:
        text = text_result({"path": object()})["content"][0]["text"]
        self.assertIn("<object object", text)

    def test_error_result_marks_is_error_and_names_the_type(self) -> None:
        result = error_result(ValueError("坏了"))
        self.assertIs(result["isError"], True)
        self.assertIn("ValueError: 坏了", result["content"][0]["text"])


class SchemaTest(unittest.TestCase):
    def test_schema_follows_the_param_table(self) -> None:
        skill = make_skill(
            params=(
                SkillParam(
                    name="positive",
                    type="string",
                    node="4",
                    field="ckpt_name",
                    description="正向提示词",
                    required=True,
                ),
                SkillParam(name="steps", type="integer", node="3", field="steps", default=20),
                SkillParam(name="opt", type="string", node="3", field="seed", required=False),
            )
        )
        schema = schema_for(skill)
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["required"], ["positive"])
        self.assertEqual(schema["properties"]["positive"]["description"], "正向提示词")
        self.assertEqual(schema["properties"]["steps"]["default"], 20)
        self.assertNotIn("default", schema["properties"]["opt"])

    def test_schema_without_required_params_omits_the_key(self) -> None:
        self.assertNotIn("required", schema_for(make_skill()))

    def test_tool_describe_matches_the_mcp_shape(self) -> None:
        tool = tool_by_name(build_tools(FakeEngine(), registry_of(())), "comfy_get_queue")
        described = tool.describe()
        self.assertEqual(set(described), {"name", "description", "inputSchema"})
        self.assertEqual(described["inputSchema"]["type"], "object")


class ToolSurfaceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.skills = load_skills(WORKFLOWS_DIR)
        self.tools = build_tools(self.engine, registry_of(self.skills))

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await tool_by_name(self.tools, name).handler(args or {})

    def test_exposes_generic_tools_plus_one_per_skill(self) -> None:
        names = [t.name for t in self.tools]
        self.assertEqual(names[: len(GENERIC_TOOLS)], GENERIC_TOOLS)
        self.assertEqual(names[len(GENERIC_TOOLS) :], [f"skill__{s.id}" for s in self.skills])
        for tool in self.tools:
            self.assertTrue(tool.description.strip(), tool.name)

    def test_list_models_folder_is_not_pinned_to_a_fixed_enum(self) -> None:
        # 类别是引擎那边定的（第三方节点还能注册新的），硬写 enum 会把它们挡在门外；
        # 所以 folder 是自由字符串，并且要指路 comfy_list_model_folders。
        folder = tool_by_name(self.tools, "comfy_list_models").input_schema["properties"]["folder"]
        self.assertNotIn("enum", folder)
        self.assertIn("comfy_list_model_folders", folder["description"])

    async def test_list_model_folders_reads_from_the_engine(self) -> None:
        self.engine.model_folders = ["checkpoints", "loras", "f5_tts"]
        self.assertEqual(
            as_json(await self.call("comfy_list_model_folders")), ["checkpoints", "loras", "f5_tts"]
        )

        # 引擎没覆写时（老引擎）回探测表那几类，而不是回个空列表让人以为「没装模型」。
        self.engine.model_folders = None
        self.assertEqual(as_json(await self.call("comfy_list_model_folders")), list(MODEL_PROBES))

    async def test_list_models_reads_from_the_engine(self) -> None:
        self.engine.object_info_map["CheckpointLoaderSimple"] = {
            "input": {"required": {"ckpt_name": [["a.safetensors", "b.safetensors"]]}}
        }
        self.assertEqual(as_json(await self.call("comfy_list_models")), ["a.safetensors", "b.safetensors"])
        with self.assertRaises(EngineError) as ctx:
            await self.call("comfy_list_models", {"folder": "nope"})
        self.assertIn("未知 folder: nope", str(ctx.exception))
        with self.assertRaises(ValueError):
            await self.call("comfy_list_models", {"folder": 3})

        # 相关节点没装：明确说节点不存在，而不是回一个空列表让人以为「没模型」
        with self.assertRaises(EngineError) as ctx:
            await self.call("comfy_list_models", {"folder": "loras"})
        self.assertIn("节点 LoraLoader 不存在", str(ctx.exception))

        # 节点在、但字段形状不是枚举列表：同样显式报错
        self.engine.object_info_map["CheckpointLoaderSimple"] = {"input": {"required": {"ckpt_name": ["坏形状"]}}}
        with self.assertRaises(EngineError) as ctx:
            await self.call("comfy_list_models")
        self.assertIn("无法从 CheckpointLoaderSimple.ckpt_name 读取模型列表", str(ctx.exception))

    async def test_list_skills_mirrors_the_param_table(self) -> None:
        skills = as_json(await self.call("comfy_list_skills"))
        self.assertEqual([s["id"] for s in skills], ["text-to-image"])
        params = [p["name"] for p in skills[0]["params"]]
        self.assertIn("ckpt_name", params)
        required = next(p for p in skills[0]["params"] if p["name"] == "ckpt_name")
        self.assertIs(required["required"], True)
        negative = next(p for p in skills[0]["params"] if p["name"] == "negative")
        self.assertEqual(negative["default"], "bad quality, blurry")


class SkillToolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.tools = build_tools(self.engine, registry_of(load_skills(WORKFLOWS_DIR)))

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await tool_by_name(self.tools, name).handler(args or {})

    async def test_run_skill_injects_params_and_reports_images(self) -> None:
        result = await self.call(
            "comfy_run_skill",
            {"skill_id": "text-to-image", "params": {"ckpt_name": "a.safetensors", "positive": "一只猫"}},
        )
        payload = as_json(result)
        self.assertEqual(payload["prompt_id"], "prompt-1")
        self.assertEqual(payload["images"][0]["filename"], "prompt-1.png")
        self.assertTrue(payload["images"][0]["url"].startswith("http://engine.test/view?"))

        submitted = self.engine.submitted[0]
        self.assertEqual(submitted["4"]["inputs"]["ckpt_name"], "a.safetensors")
        self.assertEqual(submitted["6"]["inputs"]["text"], "一只猫")
        self.assertEqual(submitted["7"]["inputs"]["text"], "bad quality, blurry")
        self.assertNotEqual(submitted["3"]["inputs"]["seed"], -1, "seed=-1 应被换成随机值")

    async def test_run_skill_input_errors_are_explicit(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.call("comfy_run_skill", {"skill_id": ""})
        self.assertIn("skill_id", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            await self.call("comfy_run_skill", {"skill_id": "nope"})
        self.assertIn("没有 skill nope", str(ctx.exception))

        with self.assertRaises(ValueError):
            await self.call("comfy_run_skill", {"skill_id": "text-to-image", "params": []})

        # 参数校验失败（缺必填 / 拼错名字）要原样冒出来，别提交半个工作流
        with self.assertRaises(ValueError) as ctx:
            await self.call("comfy_run_skill", {"skill_id": "text-to-image", "params": {"ckptname": "a"}})
        self.assertIn("不认识这些参数", str(ctx.exception))
        self.assertEqual(self.engine.submitted, [])

    async def test_per_skill_tool_takes_params_directly(self) -> None:
        result = await self.call("skill__text-to-image", {"ckpt_name": "a.safetensors", "positive": "一只猫"})
        self.assertEqual(as_json(result)["prompt_id"], "prompt-1")
        self.assertEqual(self.engine.submitted[0]["6"]["inputs"]["text"], "一只猫")

        with self.assertRaises(ValueError):
            await self.call("skill__text-to-image", {"ckpt_name": "a.safetensors"})


class WorkflowToolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.tools = build_tools(self.engine, registry_of(load_skills(WORKFLOWS_DIR)))

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await tool_by_name(self.tools, name).handler(args or {})

    async def test_submit_workflow_passes_it_through(self) -> None:
        workflow = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "a"}}}
        self.assertEqual(as_json(await self.call("comfy_submit_workflow", {"workflow": workflow})), {"prompt_id": "prompt-1"})
        self.assertEqual(self.engine.submitted, [workflow])

        for bad in ({}, None, [], "workflow"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError) as ctx:
                    await self.call("comfy_submit_workflow", {"workflow": bad})
                self.assertIn("workflow", str(ctx.exception))

    async def test_history_queue_and_interrupt_go_to_the_engine(self) -> None:
        self.engine.histories["p1"] = {"outputs": {"9": {"images": [{"filename": "x.png"}]}}}
        self.assertEqual(as_json(await self.call("comfy_get_history", {"prompt_id": "p1"}))["outputs"]["9"]["images"][0]["filename"], "x.png")

        with self.assertRaises(EngineError) as ctx:
            await self.call("comfy_get_history", {"prompt_id": "nope"})
        self.assertIn("history 里没有 prompt nope", str(ctx.exception))
        with self.assertRaises(ValueError):
            await self.call("comfy_get_history", {})

        self.engine.queue_snapshot = {"queue_running": [[1, "p1"]], "queue_pending": []}
        self.assertEqual(as_json(await self.call("comfy_get_queue")), self.engine.queue_snapshot)

        self.assertEqual((await self.call("comfy_interrupt"))["content"][0]["text"], "interrupted")
        self.assertEqual(self.engine.interrupts, 1)


class SaveSkillToolTest(unittest.IsolatedAsyncioTestCase):
    """``comfy_save_skill``：把对话里打磨好的工作流沉淀成用户自己的 skill。

    这里刻意用**真的两个目录**（内置目录 = 随包那份，用户目录 = 临时目录），因为这条
    能力的要害就是"落盘之后立刻能用"，纯内存视图测不出这件事。
    """

    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-store-")
        self.addCleanup(self.tmp.cleanup)
        self.user_dir = Path(self.tmp.name)
        self.registry = SkillRegistry(builtin_dir=WORKFLOWS_DIR, user_dir=self.user_dir)
        self.registry.reload()
        self.tools = build_tools(self.engine, self.registry)

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await tool_by_name(self.tools, name).handler(args or {})

    def document(self, **overrides: Any) -> dict[str, Any]:
        workflow = {k: dict(v) for k, v in WORKFLOW.items()}
        workflow["6"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}}
        doc: dict[str, Any] = {
            "id": "cat-portrait",
            "title": "猫肖像",
            "description": "固定好模型与采样参数，只调提示词反复出图",
            "tags": ["人像"],
            "workflow": workflow,
            "params": [
                {"name": "ckpt_name", "type": "string", "node": "4", "field": "ckpt_name", "required": True},
                {"name": "positive", "type": "string", "node": "6", "field": "text", "default": "a cat"},
            ],
        }
        doc.update(overrides)
        return doc

    async def test_a_saved_skill_is_listable_and_runnable_right_away(self) -> None:
        saved = as_json(await self.call("comfy_save_skill", self.document()))
        self.assertEqual(saved["id"], "cat-portrait")
        self.assertEqual(Path(saved["file"]).parent, self.user_dir)
        self.assertTrue((self.user_dir / "cat-portrait.json").is_file())

        listed = {s["id"] for s in as_json(await self.call("comfy_list_skills"))}
        self.assertEqual(listed, {"text-to-image", "cat-portrait"})

        # 不用重启、也不用重建工具表，立刻就能跑它
        result = await self.call(
            "comfy_run_skill",
            {"skill_id": "cat-portrait", "params": {"ckpt_name": "b.safetensors", "positive": "黑猫"}},
        )
        self.assertEqual(as_json(result)["prompt_id"], "prompt-1")
        self.assertEqual(self.engine.submitted[0]["4"]["inputs"]["ckpt_name"], "b.safetensors")
        self.assertEqual(self.engine.submitted[0]["6"]["inputs"]["text"], "黑猫")

        with self.assertRaises(ValueError) as ctx:  # 必填项照样拦
            await self.call("comfy_run_skill", {"skill_id": "cat-portrait", "params": {}})
        self.assertIn("ckpt_name", str(ctx.exception))

    async def test_it_does_not_clobber_an_existing_skill_on_its_own(self) -> None:
        await self.call("comfy_save_skill", self.document())

        with self.assertRaises(ValueError) as ctx:
            await self.call("comfy_save_skill", self.document(title="改个名"))
        self.assertIn("overwrite", str(ctx.exception))
        self.assertEqual(self.registry.get("cat-portrait").title, "猫肖像")

        saved = as_json(await self.call("comfy_save_skill", {**self.document(title="改个名"), "overwrite": True}))
        self.assertEqual(saved["title"], "改个名")
        self.assertEqual(self.registry.get("cat-portrait").title, "改个名")

    async def test_builtin_skills_cannot_be_overwritten(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.call("comfy_save_skill", self.document(id="text-to-image", overwrite=True))
        self.assertIn("随包自带", str(ctx.exception))
        self.assertFalse((self.user_dir / "text-to-image.json").exists())

    async def test_the_document_is_checked_against_the_workflow(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.call(
                "comfy_save_skill",
                self.document(params=[{"name": "steps", "type": "integer", "node": "99", "field": "steps"}]),
            )
        self.assertIn("不在 workflow 里", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            await self.call(
                "comfy_save_skill",
                self.document(params=[{"name": "steps", "type": "integer", "node": "4", "field": "steps"}]),
            )
        self.assertIn("不是节点 4 的输入", str(ctx.exception))

        with self.assertRaises(ValueError):  # title/description 是给用户看的，不许空着
            await self.call("comfy_save_skill", self.document(title=""))
        self.assertEqual(list(self.user_dir.glob("*.json")), [])

    async def test_unknown_fields_and_bad_ids_are_refused(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.call("comfy_save_skill", {**self.document(), "nope": 1})
        self.assertIn("不认识的字段: nope", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:  # id 会成为文件名，必须安全
            await self.call("comfy_save_skill", self.document(id="../跑出去"))
        self.assertIn("不能当文件名", str(ctx.exception))

        with self.assertRaises(ValueError):
            await self.call("comfy_save_skill", {**self.document(), "overwrite": "yes"})
        self.assertEqual(list(self.user_dir.glob("*.json")), [])

    async def test_the_file_round_trips_through_a_fresh_load(self) -> None:
        await self.call("comfy_save_skill", self.document())

        # 换一个 registry 重新读盘 = 下次启动的视角
        fresh = SkillRegistry(builtin_dir=WORKFLOWS_DIR, user_dir=self.user_dir)
        fresh.reload()
        skill = fresh.get("cat-portrait")
        self.assertIsNotNone(skill)
        self.assertEqual([p.name for p in skill.params], ["ckpt_name", "positive"])
        self.assertTrue(skill.params[1].has_default)
        self.assertEqual(skill.params[1].default, "a cat")
        self.assertEqual(skill.tags, ("人像",))


#: 渲染工具用的一张最小视频图（08 补帧：只留 LoadVideo 一个节点）。
#: 真图是开发机上那 12 张（见 ``skills/render.py`` 的目标表）；这里只验"接线通了" ——
#: 真跑一次视频生成是真的占 GPU，不该塞进单测。
RENDER_DOC = {"nodes": [{"id": 1, "type": "LoadVideo", "mode": 0, "widgets_values": ["in.mp4"]}], "links": []}
RENDER_OBJECT_INFO = {
    "LoadVideo": {
        "input": {"required": {"file": [["in.mp4"], {"video_upload": True}]}},
        "output": ["VIDEO"],
    },
}


class RenderToolsTest(unittest.IsolatedAsyncioTestCase):
    """渲染工具：与 ``skills/render.py`` 同源；参数不过关先报错，绝不提交半张图。"""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory(prefix="comfy-studio-renders-")
        self.addCleanup(self._tmpdir.cleanup)
        self.workflows = Path(self._tmpdir.name, "workflows")
        self.workflows.mkdir()
        self.target = find_target("video-interpolate")
        (self.workflows / self.target.file).write_text(json.dumps(RENDER_DOC), encoding="utf-8")
        # 工作流目录按环境变量换掉（render.py 就是这么发现的，不写死机器路径）
        env = mock.patch.dict(os.environ, {WORKFLOWS_ENV: str(self.workflows)})
        env.start()
        self.addCleanup(env.stop)

    def tools(self, engine: FakeEngine) -> dict[str, Tool]:
        return {tool.name: tool for tool in build_tools(engine, registry_of(()))}

    async def test_list_renders_reports_every_target_and_the_file_state(self) -> None:
        payload = as_json(await self.tools(FakeEngine())["comfy_list_renders"].handler({}))
        self.assertEqual(payload["workflows_dir"], str(self.workflows))
        self.assertIsNone(payload["note"])
        self.assertEqual([item["id"] for item in payload["targets"]], [t.id for t in RENDER_TARGETS])
        by_id = {item["id"]: item for item in payload["targets"]}
        self.assertIs(by_id["video-interpolate"]["file_exists"], True)
        self.assertIs(by_id["video-draft"]["file_exists"], False, "缺的图要如实标 false，不许假装能跑")
        self.assertIs(by_id["video-draft"]["reference_images"], True)
        self.assertNotIn("reference_images", by_id["video-interpolate"])

    async def test_list_renders_says_so_when_the_directory_is_gone(self) -> None:
        missing = Path(self._tmpdir.name, "没有这个目录")
        with mock.patch.dict(os.environ, {WORKFLOWS_ENV: str(missing)}):
            payload = as_json(await self.tools(FakeEngine())["comfy_list_renders"].handler({}))
        self.assertIn(WORKFLOWS_ENV, payload["note"])
        self.assertEqual(len(payload["targets"]), len(RENDER_TARGETS), "列不出来也要把目标表给全")
        self.assertTrue(all(not item["file_exists"] for item in payload["targets"]))

    async def test_render_params_use_the_exact_keys_skill_params_use(self) -> None:
        """前端与桌面宿主只认一套字段。

        这条是防回归的：渲染目标那份参数表一度用 ``has_default`` / ``hint``，与 skill 的
        ``default`` / ``description`` 漂成了两种形状 —— 调用方得写两份解析。键名逐字对着。
        里面必须有 ``hasDefault``：只有 ``default`` 分不开"默认值就是 null"与"没有默认值"
        （见 ``skills/params.py::param_entry``），而"这个参数能不能省"正靠它判。
        """
        listing = as_json(await self.tools(FakeEngine())["comfy_list_renders"].handler({}))
        render_param = listing["targets"][0]["params"][0]
        skill = make_skill(
            params=(SkillParam(name="positive", type="string", node="4", field="text", description="正向提示词"),)
        )
        self.assertEqual(set(render_param), set(skill_entry(skill)["params"][0]))
        self.assertEqual(
            set(render_param),
            {"name", "type", "required", "default", "description", "hasDefault"},
        )

    async def test_bad_arguments_are_rejected_before_anything_is_submitted(self) -> None:
        engine = FakeEngine()
        handler = self.tools(engine)["comfy_render"].handler
        cases = [
            ({}, "target_id"),
            ({"target_id": self.target.id, "params": "prompt"}, "params 必须是对象"),
            ({"target_id": self.target.id, "images": "a.png"}, "必须是数组"),
            ({"target_id": self.target.id, "images": ["a.png", 2]}, "非空字符串"),
            ({"target_id": self.target.id, "duration_sec": "5"}, "必须是数字"),
            ({"target_id": self.target.id, "duration_sec": 0}, "大于 0"),
            ({"target_id": self.target.id, "output_dir": "   "}, "output_dir"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValueError) as ctx:
                    await handler(args)
                self.assertIn(message, str(ctx.exception))
        self.assertEqual(engine.submitted, [], "参数不过关就不该提交任何东西")

    async def test_unknown_target_lists_the_alternatives(self) -> None:
        engine = FakeEngine()
        with self.assertRaises(RenderError) as ctx:
            await self.tools(engine)["comfy_render"].handler({"target_id": "视频试片"})
        self.assertIn("video-draft", str(ctx.exception))
        self.assertEqual(engine.submitted, [])

    async def test_render_runs_the_target_and_hands_back_the_target_id(self) -> None:
        engine = FakeEngine()
        engine.object_info_map = dict(RENDER_OBJECT_INFO)
        payload = as_json(
            await self.tools(engine)["comfy_render"].handler(
                {"target_id": self.target.id, "params": {"file": "in.mp4"}}
            )
        )
        self.assertEqual(payload["prompt_id"], "prompt-1")
        self.assertEqual(payload["target"], self.target.id)
        self.assertEqual(len(engine.submitted), 1)
        self.assertEqual(engine.submitted[0]["1"]["inputs"]["file"], "in.mp4")

    async def test_output_dir_saves_the_media_and_returns_paths(self) -> None:
        engine = FakeEngine()
        engine.object_info_map = dict(RENDER_OBJECT_INFO)
        saved = Path(self._tmpdir.name, "out", "shot-001.mp4")
        saver = mock.AsyncMock(return_value=(saved,))
        with mock.patch("comfy_studio.mcp.tools.save_media_batch", saver):
            payload = as_json(
                await self.tools(engine)["comfy_render"].handler(
                    {"target_id": self.target.id, "params": {"file": "in.mp4"}, "output_dir": str(saved.parent)}
                )
            )
        self.assertEqual(payload["saved"], [str(saved)])
        self.assertEqual(len(saver.await_args.args[0]), 1, "假引擎回一份产物，落盘就只该收到这一份")
        self.assertEqual(saver.await_args.args[1], str(saved.parent))
        self.assertEqual(saver.await_args.kwargs["base_url"], engine.base_url)


if __name__ == "__main__":
    unittest.main()
