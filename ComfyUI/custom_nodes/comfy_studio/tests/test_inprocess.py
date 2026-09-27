"""``engine/inprocess.py``（进程内引擎）的测试。

这是 custom node 跑在引擎进程里时的**默认**实现：九条原语
（object_info / list_model_folders / list_models / submit / wait / history / queue /
interrupt / cancel_prompt）加上地址推导都在这里跑。这里用假的 ``server`` / ``folder_paths`` /
``nodes`` / ``execution`` 模块把整条路走通，不需要真的起 ComfyUI；只有取消那条用真的
``comfy_execution/jobs.py``（见下面的 ``_COMFY_ROOT``）。
"""

from __future__ import annotations

import contextlib
import os
import sys
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

# ``comfy_execution/jobs.py`` 是引擎自己的取消逻辑（分类 + 该中断还是该出队），纯函数，
# 这里直接用**真的**：它才是那套判断的事实源，假一份就等于拿替身测替身。它住在 ComfyUI
# 根下，而跑测试时 cwd 是 ``custom_nodes``，所以补一条路。
_COMFY_ROOT = Path(__file__).resolve().parents[3]
if str(_COMFY_ROOT) not in sys.path:
    sys.path.insert(0, str(_COMFY_ROOT))

from comfy_studio.engine import DEFAULT_BASE_URL, EngineError
from comfy_studio.engine import inprocess
from comfy_studio.engine.inprocess import InProcessEngine
from comfy_studio.skills.runner import SkillExecutionError


class _StubNode:
    """只实现 ``INPUT_TYPES()`` 的节点替身；给了 error 就在调用时抛。"""

    def __init__(self, inputs: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._inputs = inputs or {}
        self._error = error

    def INPUT_TYPES(self) -> dict[str, Any]:
        if self._error is not None:
            raise self._error
        return {"required": dict(self._inputs)}


class _FakeQueue:
    """引擎的 prompt 队列：只留我们真用到的那几个方法。"""

    def __init__(self) -> None:
        self.puts: list[tuple[Any, ...]] = []
        self.history: dict[str, dict[str, Any]] = {}
        self.running: list[tuple[Any, ...]] = []
        self.pending: list[tuple[Any, ...]] = []
        #: 被要求"如果正是你在跑就中断"的 prompt_id（取消走这条，不是 interrupt_processing）。
        self.interrupted: list[str] = []

    def put(self, item: tuple[Any, ...]) -> None:
        self.puts.append(item)

    def get_history(self, prompt_id: str | None = None) -> dict[str, dict[str, Any]]:
        if prompt_id is None:
            return dict(self.history)
        entry = self.history.get(prompt_id)
        return {} if entry is None else {prompt_id: entry}

    def get_current_queue_volatile(self) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        return (list(self.running), list(self.pending))

    def get_current_queue(self) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        return (list(self.running), list(self.pending))

    def interrupt_if_running(self, prompt_id: str) -> bool:
        """引擎那个带 mutex 的原子中断；这里只要"确实在跑才动它、且回真话"这个语义。"""
        self.interrupted.append(prompt_id)
        for index, item in enumerate(self.running):
            if item[1] == prompt_id:
                self.running.pop(index)
                return True
        return False

    def delete_queue_item(self, predicate: Any) -> bool:
        for index, item in enumerate(self.pending):
            if predicate(item):
                self.pending.pop(index)
                return True
        return False


class _FakePromptServer:
    def __init__(self, *, port: int | None = 8188, address: str = "127.0.0.1") -> None:
        self.number = 1
        self.port = port
        self.address = address
        self.prompt_queue = _FakeQueue()


class InProcessEngineTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.server_obj = _FakePromptServer()
        self.queue = self.server_obj.prompt_queue

        self.nodes = types.ModuleType("nodes")
        self.nodes.NODE_CLASS_MAPPINGS = {
            "Good": _StubNode({"prompt": ("STRING", {"default": "hi"})}),
            "Broken": _StubNode(error=RuntimeError("坏节点")),
        }
        self.nodes.interrupt_processing = mock.Mock()

        self.folder_paths = types.ModuleType("folder_paths")
        self.folder_paths.cache_helper = contextlib.nullcontext()
        self.folder_paths.folder_names_and_paths = {"checkpoints": [], "diffusion_models": []}
        self.folder_paths.files = {"checkpoints": ["a.safetensors"], "diffusion_models": ["b.safetensors"]}
        self.folder_paths.map_legacy = lambda name: "diffusion_models" if name == "unet" else name
        self.folder_paths.get_filename_list = lambda name: self.folder_paths.files.get(name, [])

        self.validate_result: tuple[Any, ...] = (True, None, ["1"], {})
        self.execution = types.ModuleType("execution")
        self.execution.SENSITIVE_EXTRA_DATA_KEYS = []
        self.execution.validate_prompt = self._validate_prompt

        self.server_module = types.ModuleType("server")
        self.server_module.PromptServer = type("PromptServer", (), {"instance": self.server_obj})

        modules = {
            "server": self.server_module,
            "folder_paths": self.folder_paths,
            "nodes": self.nodes,
            "execution": self.execution,
        }
        modules_patcher = mock.patch.dict(sys.modules, modules)
        modules_patcher.start()
        self.addCleanup(modules_patcher.stop)

        # 地址推导会读 COMFY_URL：默认按"没设"来，单个用例要测它时自己再 patch。
        env_patcher = mock.patch.dict(os.environ, {"COMFY_URL": ""})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    async def _validate_prompt(self, prompt_id: str, prompt: Any, extra: Any) -> tuple[Any, ...]:
        self.last_validated = (prompt_id, prompt, extra)
        return self.validate_result

    # ---- object_info ----------------------------------------------------

    async def test_object_info_returns_one_node_or_empty_when_unknown(self) -> None:
        engine = InProcessEngine()
        self.assertEqual(
            await engine.object_info("Good"),
            {"Good": {"required": {"prompt": ("STRING", {"default": "hi"})}}},
        )
        self.assertEqual(await engine.object_info("没有这个节点"), {})

    async def test_object_info_all_nodes_does_not_let_one_broken_node_break_the_list(self) -> None:
        info = await InProcessEngine().object_info()
        self.assertIn("Good", info)
        self.assertEqual(info["Broken"], {"error": "RuntimeError: 坏节点"})

    # ---- 模型清单 -------------------------------------------------------

    async def test_list_model_folders_uses_folder_paths_keys(self) -> None:
        self.assertEqual(await InProcessEngine().list_model_folders(), ["checkpoints", "diffusion_models"])

    async def test_list_models_maps_legacy_name_and_rejects_unknown_folder(self) -> None:
        engine = InProcessEngine()
        self.assertEqual(await engine.list_models("unet"), ["b.safetensors"])
        self.assertEqual(await engine.list_models("checkpoints"), ["a.safetensors"])
        with self.assertRaises(EngineError) as ctx:
            await engine.list_models("没有这个类别")
        self.assertIn("没有这个类别", str(ctx.exception))

    # ---- 入队与等待 -----------------------------------------------------

    async def test_submit_puts_the_prompt_on_the_engine_queue(self) -> None:
        prompt_id = await InProcessEngine().submit({"1": {"class_type": "Good"}})

        self.assertEqual(len(self.queue.puts), 1)
        number, queued_id, prompt, extra, outputs_to_execute, sensitive = self.queue.puts[0]
        self.assertEqual((number, queued_id, prompt, outputs_to_execute, sensitive), (1, prompt_id, {"1": {"class_type": "Good"}}, ["1"], {}))
        self.assertEqual(self.server_obj.number, 2, "入队后 number 必须自增，否则两条 prompt 会撞号")
        self.assertIn("create_time", extra)

    async def test_submit_reports_validation_failure_with_node_errors(self) -> None:
        self.validate_result = (False, {"message": "节点 1 缺输入"}, [], {"1": {"errors": ["缺 prompt"]}})
        with self.assertRaises(SkillExecutionError) as ctx:
            await InProcessEngine().submit({"1": {}})

        self.assertIn("节点 1 缺输入", str(ctx.exception))
        self.assertEqual(ctx.exception.node_errors, {"1": {"errors": ["缺 prompt"]}})
        self.assertEqual(self.queue.puts, [], "校验没过就不该入队")

    async def test_wait_returns_the_history_entry_and_reports_done(self) -> None:
        engine = InProcessEngine()
        prompt_id = await engine.submit({"1": {}})
        self.queue.history[prompt_id] = {
            "status": {"completed": True},
            "outputs": {"9": {"images": [{"filename": "x.png", "subfolder": "", "type": "output"}]}},
        }

        states: list[str] = []

        async def on_status(state: str, _data: dict[str, Any]) -> None:
            states.append(state)

        entry = await engine.wait(prompt_id, timeout=5, on_status=on_status)

        self.assertEqual(entry["outputs"]["9"]["images"][0]["filename"], "x.png")
        self.assertEqual(states, ["done"])

    async def test_wait_reports_execution_failure_instead_of_returning_half_a_result(self) -> None:
        engine = InProcessEngine()
        prompt_id = await engine.submit({"1": {}})
        self.queue.history[prompt_id] = {
            "status": {"completed": False, "status_str": "error", "messages": [["execution_error", "炸了"]]}
        }

        with self.assertRaises(SkillExecutionError) as ctx:
            await engine.wait(prompt_id, timeout=5)
        self.assertIn("炸了", str(ctx.exception))

    async def test_wait_times_out_and_points_at_the_queue_tool(self) -> None:
        with self.assertRaises(SkillExecutionError) as ctx:
            await InProcessEngine().wait("从来没入过队", timeout=-1)

        self.assertIn("超时", str(ctx.exception))
        self.assertIn("/queue", str(ctx.exception), "超时错误里要给出排查手段（这是给人看的）")

    async def test_history_is_none_when_the_prompt_is_unknown(self) -> None:
        engine = InProcessEngine()
        self.assertIsNone(await engine.history("还没跑过"))
        self.queue.history["abc"] = {"status": {"completed": True}}
        self.assertEqual(await engine.history("abc"), {"status": {"completed": True}})

    async def test_queue_and_interrupt_reach_the_engine(self) -> None:
        self.queue.running = [(1, "running-id")]
        self.queue.pending = [(2, "pending-id")]
        engine = InProcessEngine()

        self.assertEqual(
            await engine.queue(), {"queue_running": [(1, "running-id")], "queue_pending": [(2, "pending-id")]}
        )
        await engine.interrupt()
        self.nodes.interrupt_processing.assert_called_once_with()

    # ---- 取消：按 id 把活从队列里撤下来 ---------------------------------

    async def test_cancel_prompt_interrupts_the_job_that_is_running(self) -> None:
        # 分类与动作都交给引擎自己的 cancel_job：在跑就中断，且只动这一个。
        self.queue.running = [(1, "running-id")]
        self.queue.pending = [(2, "someone-else")]

        self.assertTrue(await InProcessEngine().cancel_prompt("running-id"))

        self.assertEqual(self.queue.interrupted, ["running-id"])
        self.assertEqual([item[1] for item in self.queue.running], [])
        self.assertEqual([item[1] for item in self.queue.pending], ["someone-else"], "别人的活不许动")

    async def test_cancel_prompt_dequeues_the_job_that_is_only_pending(self) -> None:
        self.queue.pending = [(1, "pending-id"), (2, "someone-else")]

        self.assertTrue(await InProcessEngine().cancel_prompt("pending-id"))

        self.assertEqual([item[1] for item in self.queue.pending], ["someone-else"])
        self.assertEqual(self.queue.interrupted, [], "还没开跑就谈不上中断")

    async def test_cancel_prompt_is_a_no_op_for_finished_or_unknown_ids(self) -> None:
        # 与上游 POST /api/jobs/{job_id}/cancel 一样幂等：回 False，不当成错误。
        self.queue.history["done-id"] = {"status": {"completed": True}}
        engine = InProcessEngine()

        self.assertFalse(await engine.cancel_prompt("done-id"))
        self.assertFalse(await engine.cancel_prompt("从来没入过队"))

    # ---- 地址推导（/view 图片链接要用）-----------------------------------

    def test_base_url_follows_the_engine_port(self) -> None:
        self.assertEqual(InProcessEngine().base_url, "http://127.0.0.1:8188")

    def test_base_url_prefers_comfy_url_env(self) -> None:
        with mock.patch.dict(os.environ, {"COMFY_URL": "http://10.0.0.5:9000/"}):
            self.assertEqual(InProcessEngine().base_url, "http://10.0.0.5:9000")

    def test_base_url_replaces_wildcard_listen_address(self) -> None:
        self.server_obj.address = "0.0.0.0"
        self.server_obj.port = 1234
        self.assertEqual(InProcessEngine().base_url, "http://127.0.0.1:1234", "0.0.0.0 拼出来的链接点不开")

    def test_base_url_brackets_ipv6_address(self) -> None:
        self.server_obj.address = "::1"
        self.server_obj.port = 1234
        self.assertEqual(InProcessEngine().base_url, "http://[::1]:1234")

    def test_base_url_falls_back_to_default_when_port_is_unknown(self) -> None:
        self.server_obj.port = None
        self.assertEqual(InProcessEngine().base_url, DEFAULT_BASE_URL)

    def test_missing_server_module_is_reported_not_swallowed(self) -> None:
        with mock.patch.dict(sys.modules, {"server": None}):
            with self.assertRaises(EngineError) as ctx:
                inprocess._server()
            self.assertIn("InProcessEngine", str(ctx.exception))
            # 拿不到引擎对象时地址退回默认值：这条路不该反过来把构造也弄崩。
            self.assertEqual(InProcessEngine().base_url, DEFAULT_BASE_URL)


if __name__ == "__main__":
    unittest.main()
