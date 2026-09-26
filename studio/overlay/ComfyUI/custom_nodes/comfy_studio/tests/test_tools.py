"""MCP 工具集：工具表形状、JSON Schema、每个 handler 的行为。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from ..engine import EngineError, MODEL_PROBES
from ..mcp.tools import Tool, build_tools, error_result, schema_for, text_result
from ..skills import SkillRegistry, load_skills, WORKFLOWS_DIR
from ..skills.types import SkillParam
from .support import FakeEngine, WORKFLOW, make_skill


def registry_of(skills: tuple[Any, ...]) -> SkillRegistry:
    """只有内存里这几份 skill 的视图（工具测试不碰磁盘）。"""
    return SkillRegistry.in_memory(skills)

GENERIC_TOOLS = [
    "comfy_list_models",
    "comfy_list_skills",
    "comfy_run_skill",
    "comfy_save_skill",
    "comfy_submit_workflow",
    "comfy_get_history",
    "comfy_get_queue",
    "comfy_interrupt",
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

    def test_list_models_enum_covers_every_known_folder(self) -> None:
        schema = tool_by_name(self.tools, "comfy_list_models").input_schema
        self.assertEqual(schema["properties"]["folder"]["enum"], list(MODEL_PROBES))

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


if __name__ == "__main__":
    unittest.main()
