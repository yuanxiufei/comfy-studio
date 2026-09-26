"""MCP 工具集：工具表形状、JSON Schema、每个 handler 的行为。"""

from __future__ import annotations

import json
import unittest
from typing import Any

from ..engine import EngineError, MODEL_PROBES
from ..mcp.tools import Tool, build_tools, error_result, schema_for, text_result
from ..skills import load_skills, WORKFLOWS_DIR
from ..skills.types import SkillParam
from .support import FakeEngine, make_skill

GENERIC_TOOLS = [
    "comfy_list_models",
    "comfy_list_skills",
    "comfy_run_skill",
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
        tool = tool_by_name(build_tools(FakeEngine(), ()), "comfy_get_queue")
        described = tool.describe()
        self.assertEqual(set(described), {"name", "description", "inputSchema"})
        self.assertEqual(described["inputSchema"]["type"], "object")


class ToolSurfaceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.skills = load_skills(WORKFLOWS_DIR)
        self.tools = build_tools(self.engine, self.skills)

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        return await tool_by_name(self.tools, name).handler(args or {})

    def test_exposes_seven_generic_tools_plus_one_per_skill(self) -> None:
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
        self.tools = build_tools(self.engine, load_skills(WORKFLOWS_DIR))

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
        self.tools = build_tools(self.engine, load_skills(WORKFLOWS_DIR))

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


if __name__ == "__main__":
    unittest.main()
