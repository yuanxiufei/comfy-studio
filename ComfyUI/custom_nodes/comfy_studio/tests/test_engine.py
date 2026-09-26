"""引擎句柄的公共层：模型列表探测、run_skill 组合、状态回调的透传。

两种实现（进程内 / HTTP）各自的重活在别处，这里守的是 :class:`EngineClient`
里那层「只写一遍」的组合逻辑。
"""

from __future__ import annotations

import unittest
from typing import Any

from ..engine import EngineError, MODEL_PROBES
from ..skills import build_prompt, load_skills, WORKFLOWS_DIR
from ..skills.runner import DEFAULT_TIMEOUT
from .support import FakeEngine


class ModelProbesTest(unittest.TestCase):
    def test_every_probe_is_a_node_field_pair(self) -> None:
        self.assertIn("checkpoints", MODEL_PROBES)
        for folder, probe in MODEL_PROBES.items():
            with self.subTest(folder=folder):
                self.assertEqual(len(probe), 2)
                self.assertTrue(all(isinstance(part, str) and part for part in probe))


class ListModelsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()

    async def test_reads_the_enum_off_the_node_definition(self) -> None:
        self.engine.object_info_map["CheckpointLoaderSimple"] = {
            "input": {"required": {"ckpt_name": [["a.safetensors", "b.ckpt"]]}}
        }
        self.assertEqual(await self.engine.list_models("checkpoints"), ["a.safetensors", "b.ckpt"])

    async def test_reports_unknown_folder(self) -> None:
        with self.assertRaises(EngineError) as ctx:
            await self.engine.list_models("nope")
        self.assertIn("可选: ", str(ctx.exception))

    async def test_reports_missing_node(self) -> None:
        with self.assertRaises(EngineError) as ctx:
            await self.engine.list_models("vae")
        self.assertIn("VAELoader", str(ctx.exception))

    async def test_reports_unexpected_shape(self) -> None:
        self.engine.object_info_map["VAELoader"] = {"input": {"required": {"vae_name": []}}}
        with self.assertRaises(EngineError) as ctx:
            await self.engine.list_models("vae")
        self.assertIn("无法从 VAELoader.vae_name 读取模型列表", str(ctx.exception))


class RunSkillTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = FakeEngine()
        self.skill = load_skills(WORKFLOWS_DIR)[0]

    async def test_submits_the_injected_workflow_and_collects_images(self) -> None:
        # 显式给 seed，避免默认的 -1 被换成随机值而让两份工作流不相等
        params = {"ckpt_name": "a.safetensors", "positive": "一只猫", "steps": 4, "seed": 1234}
        result = await self.engine.run_skill(self.skill, params)
        expected = build_prompt(self.skill, params)
        self.assertEqual(self.engine.submitted, [expected])
        self.assertEqual(result.prompt_id, "prompt-1")
        self.assertEqual([img.filename for img in result.images], ["prompt-1.png"])
        self.assertIn("9", result.outputs)

    async def test_status_events_flow_from_both_the_wrapper_and_wait(self) -> None:
        seen: list[tuple[str, str]] = []

        async def listener(state: str, data: dict[str, Any]) -> None:
            seen.append((state, data["prompt_id"]))

        await self.engine.run_skill(self.skill, {"ckpt_name": "a", "positive": "x"}, on_status=listener)
        self.assertEqual([state for state, _ in seen], ["queued", "running", "done"])
        self.assertTrue(all(prompt_id == "prompt-1" for _, prompt_id in seen))
        self.assertIs(self.engine.waits[0]["has_status"], True)

    async def test_sync_listener_and_no_listener_both_work(self) -> None:
        seen: list[str] = []
        await self.engine.run_skill(self.skill, {"ckpt_name": "a", "positive": "x"}, on_status=lambda s, _d: seen.append(s))
        self.assertEqual(seen, ["queued", "running", "done"])

        self.engine.waits.clear()
        result = await self.engine.run_skill(self.skill, {"ckpt_name": "a", "positive": "x"})
        self.assertIs(self.engine.waits[0]["has_status"], False)
        self.assertEqual(result.prompt_id, "prompt-2")

    async def test_timeout_is_passed_through(self) -> None:
        await self.engine.run_skill(self.skill, {"ckpt_name": "a", "positive": "x"}, timeout=12.5)
        self.assertEqual(self.engine.waits[0]["timeout"], 12.5)

        await self.engine.run_skill(self.skill, {"ckpt_name": "a", "positive": "x"})
        self.assertEqual(self.engine.waits[1]["timeout"], DEFAULT_TIMEOUT)

    async def test_bad_params_fail_before_touching_the_engine(self) -> None:
        with self.assertRaises(ValueError):
            await self.engine.run_skill(self.skill, {"positive": "x"})
        self.assertEqual(self.engine.submitted, [])
        self.assertEqual(self.engine.waits, [])


if __name__ == "__main__":
    unittest.main()
