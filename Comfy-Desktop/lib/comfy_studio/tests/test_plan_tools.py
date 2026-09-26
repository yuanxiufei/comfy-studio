"""任务拆解：工具表、事件形状、回程、进度通知、取消与超时。

和审核通道一样的纪律——全程用假壳（一个记录事件并按剧本回话的 ``emit``），不起 Electron、
不起面板；真实的「宿主 → 桌面壳 → 清单卡」链路归 ``test_host_e2e`` 与前端 vitest。
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from comfy_studio.cancel import CancelToken, Cancelled
from comfy_studio.channel import bind_emit, unbind_emit
from comfy_studio.mcp import McpError, McpHub
from comfy_studio.plan import (
    MAX_STEPS,
    MIN_STEPS,
    PLAN_TOOLS,
    PROGRESS_STATES,
    PlanChannel,
    PlanClient,
    PlanError,
)
from comfy_studio.review import DEFAULT_ASK_TIMEOUT
from comfy_studio.rpc import RpcError
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog


def _make_host(plan: PlanChannel | None) -> StudioHost:
    """只挂计划通道的最小宿主（MCP 一个都不拉）。"""
    extra: list[Any] = [PlanClient(plan)] if plan is not None else []
    hub = McpHub([], extra_clients=extra)
    return StudioHost(hub, SkillCatalog(hub), plan=plan)


#: 一个形状正常的清单。
STEPS = [
    {"title": "查本机有没有 SDXL", "tool": "comfy-studio__comfy_list_models"},
    {"title": "跑 4 张草图"},
    {"title": "挑一张放大到 2048"},
]


class ChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_sends_the_plan_and_reads_the_verdict_back(self) -> None:
        channel = PlanChannel(timeout=1.0)
        client = PlanClient(channel)
        sent: list[tuple[str, dict[str, Any]]] = []

        async def emit(method: str, params: dict[str, Any]) -> None:
            sent.append((method, params))
            # 模拟面板：画成清单卡，用户点了「就按这个来」。
            channel.resolve(params["call_id"], ok=True, result={"approved": True, "feedback": ""})

        token = bind_emit(emit)
        try:
            result = await client.call_tool("submit", {"goal": "一张海报感的猫", "steps": STEPS})
        finally:
            unbind_emit(token)

        self.assertFalse(result["isError"])
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["goal"], "一张海报感的猫")
        self.assertEqual([s["title"] for s in payload["steps"]], [s["title"] for s in STEPS])
        self.assertEqual(payload["steps"][0]["tool"], "comfy-studio__comfy_list_models")
        self.assertIs(payload["approved"], True)
        self.assertEqual(payload["feedback"], "")

        method, params = sent[0]
        self.assertEqual(method, "agent/event")
        self.assertEqual(params["type"], "plan")
        self.assertEqual(params["goal"], "一张海报感的猫")
        self.assertEqual(len(params["steps"]), 3)
        self.assertIsNone(params["notes"])
        self.assertTrue(str(params["call_id"]).startswith("plan-"))
        self.assertEqual(channel.pending, 0)

    async def test_a_rejected_plan_comes_back_with_feedback(self) -> None:
        channel = PlanChannel(timeout=1.0)
        client = PlanClient(channel)

        async def emit(_method: str, params: dict[str, Any]) -> None:
            channel.resolve(
                params["call_id"],
                ok=True,
                result={"approved": False, "feedback": "  第 2 步换成 Flux 那套  "},
            )

        token = bind_emit(emit)
        try:
            result = await client.call_tool("submit", {"goal": "一张海报感的猫", "steps": STEPS})
        finally:
            unbind_emit(token)

        payload = json.loads(result["content"][0]["text"])
        # 否掉不算工具失败：模型要拿着这句反馈去改清单，而不是把整件事当出错。
        self.assertFalse(result["isError"])
        self.assertIs(payload["approved"], False)
        self.assertEqual(payload["feedback"], "第 2 步换成 Flux 那套")

    async def test_steps_accept_bare_strings_and_objects_alike(self) -> None:
        channel = PlanChannel(timeout=1.0)
        client = PlanClient(channel)
        sent: list[dict[str, Any]] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)
            channel.resolve(params["call_id"], ok=True, result={"approved": True})

        token = bind_emit(emit)
        try:
            await client.call_tool("submit", {"goal": "g", "steps": ["先看素材", "再跑图"]})
        finally:
            unbind_emit(token)

        self.assertEqual(
            sent[0]["steps"],
            [
                {"title": "先看素材", "detail": "", "tool": None},
                {"title": "再跑图", "detail": "", "tool": None},
            ],
        )

    async def test_a_rejection_without_feedback_is_an_error(self) -> None:
        channel = PlanChannel(timeout=1.0)
        client = PlanClient(channel)

        async def emit(_method: str, params: dict[str, Any]) -> None:
            channel.resolve(params["call_id"], ok=True, result={"approved": False, "feedback": "   "})

        token = bind_emit(emit)
        try:
            result = await client.call_tool("submit", {"goal": "g", "steps": STEPS})
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("feedback", result["content"][0]["text"])

    async def test_a_verdict_without_approved_is_an_error(self) -> None:
        channel = PlanChannel(timeout=1.0)
        client = PlanClient(channel)

        async def emit(_method: str, params: dict[str, Any]) -> None:
            channel.resolve(params["call_id"], ok=True, result={"feedback": "嗯"})

        token = bind_emit(emit)
        try:
            result = await client.call_tool("submit", {"goal": "g", "steps": STEPS})
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("approved", result["content"][0]["text"])

    async def test_progress_is_a_one_way_notification(self) -> None:
        channel = PlanChannel(timeout=0.05)
        client = PlanClient(channel)
        sent: list[dict[str, Any]] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)
            # 故意不回话：进度通知不回话也应该立刻返回，不能像 submit 那样等超时。

        token = bind_emit(emit)
        try:
            result = await asyncio.wait_for(
                client.call_tool("progress", {"step": 2, "status": "running", "note": "正在跑草图"}),
                timeout=2.0,
            )
        finally:
            unbind_emit(token)

        self.assertFalse(result["isError"])
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            {"step": 2, "status": "running", "note": "正在跑草图"},
        )
        self.assertEqual(sent[0]["type"], "plan_progress")
        self.assertEqual(sent[0]["step"], 2)
        self.assertEqual(channel.pending, 0)  # 没建 future

    async def test_progress_without_a_shell_is_explicit(self) -> None:
        result = await PlanClient(PlanChannel()).call_tool("progress", {"step": 1, "status": "done"})
        self.assertTrue(result["isError"])
        self.assertIn("没有绑定桌面壳通道", result["content"][0]["text"])

    async def test_timeout_is_explicit(self) -> None:
        client = PlanClient(PlanChannel(timeout=0.05))

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            return  # 没人接这条通道

        token = bind_emit(emit)
        try:
            result = await client.call_tool("submit", {"goal": "g", "steps": STEPS})
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("没有回音", result["content"][0]["text"])
        self.assertIn("对话面板", result["content"][0]["text"])

    async def test_no_shell_bound_is_explicit(self) -> None:
        result = await PlanClient(PlanChannel()).call_tool("submit", {"goal": "g", "steps": STEPS})
        self.assertTrue(result["isError"])
        self.assertIn("没有绑定桌面壳通道", result["content"][0]["text"])

    async def test_cancelled_token_stops_before_dispatching(self) -> None:
        channel = PlanChannel(timeout=1.0)
        client = PlanClient(channel)
        sent: list[Any] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)

        cancel = CancelToken()
        cancel.cancel("用户中止")
        token = bind_emit(emit)
        try:
            with self.assertRaises(Cancelled):
                await client.call_tool("submit", {"goal": "g", "steps": STEPS}, cancel=cancel)
        finally:
            unbind_emit(token)

        self.assertEqual(sent, [])
        self.assertEqual(channel.pending, 0)

    async def test_bad_arguments_never_reach_the_user(self) -> None:
        channel = PlanChannel(timeout=1.0)
        client = PlanClient(channel)
        sent: list[Any] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)

        token = bind_emit(emit)
        try:
            cases = (
                {},  # 没有 goal
                {"goal": "   ", "steps": STEPS},
                {"goal": "g"},  # 没有 steps
                {"goal": "g", "steps": "先看素材"},  # steps 不是数组
                {"goal": "g", "steps": ["只有一步"]},  # 一步不值得拆
                {"goal": "g", "steps": ["a", "b", "c", "d", "e", "f", "g", "h", "i"]},  # 超上限
                {"goal": "g", "steps": ["a", {"detail": "没有标题"}]},  # 缺 title
                {"goal": "g", "steps": [123, "b"]},  # 第 1 步形状不对
                {"goal": "g", "steps": STEPS, "notes": 7},  # notes 不是字符串
                {"step": 0, "status": "done"},  # progress：序号从 1 数
                {"step": "2", "status": "done"},
                {"step": 1, "status": "跑了"},  # status 不在枚举里
            )
            for case in cases:
                tool = "progress" if "step" in case else "submit"
                result = await client.call_tool(tool, case)
                self.assertTrue(result["isError"], case)
        finally:
            unbind_emit(token)

        # 形状不对就别拿去让用户白看一遍：一张卡都不该弹出来。
        self.assertEqual(sent, [])

    async def test_unknown_tool_is_a_protocol_error(self) -> None:
        client = PlanClient(PlanChannel())
        with self.assertRaises(McpError) as caught:
            await client.call_tool("submit_the_plan", {})
        self.assertIn("submit_the_plan", str(caught.exception))

    async def test_fail_all_releases_waiting_confirmations(self) -> None:
        channel = PlanChannel(timeout=5.0)
        client = PlanClient(channel)
        emitted = asyncio.Event()

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            emitted.set()

        token = bind_emit(emit)
        try:
            task = asyncio.ensure_future(client.call_tool("submit", {"goal": "g", "steps": STEPS}))
            await emitted.wait()
            self.assertEqual(channel.fail_all("宿主关停"), 1)
            result = await asyncio.wait_for(task, timeout=2.0)
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("宿主关停", result["content"][0]["text"])


class ToolTableTests(unittest.IsolatedAsyncioTestCase):
    async def test_hub_exposes_the_plan_tools(self) -> None:
        hub = McpHub([], extra_clients=[PlanClient(PlanChannel())])
        await hub.start()
        self.assertEqual(
            [t.qualified_name for t in hub.tools], ["plan__submit", "plan__progress"]
        )
        submit = next(t for t in hub.tools if t.name == "submit")
        self.assertEqual(submit.input_schema["required"], ["goal", "steps"])
        progress = next(t for t in hub.tools if t.name == "progress")
        self.assertEqual(progress.input_schema["properties"]["status"]["enum"], list(PROGRESS_STATES))

    def test_description_tells_the_model_to_ask_before_going_multi_step(self) -> None:
        submit = next(s for s in PLAN_TOOLS if s.name == "submit")
        self.assertIn("一句想法", submit.description)
        self.assertIn("approved=false", submit.description)
        self.assertIn(f"{MIN_STEPS}", submit.description)
        self.assertIn(f"{MAX_STEPS}", submit.description)

    def test_the_waiting_limit_matches_the_review_one(self) -> None:
        # 都在等人：量级得一致，不然会出现"问一句等 10 分钟、看一眼计划 1 分钟"的怪事。
        self.assertEqual(PlanChannel().timeout, DEFAULT_ASK_TIMEOUT)


class HostResultTests(unittest.IsolatedAsyncioTestCase):
    async def _submitting(self, channel: PlanChannel) -> tuple[asyncio.Task[dict[str, Any]], str]:
        """真起一次 ``submit``，把面板那头的 call_id 拿到手（不碰私有状态）。"""
        emitted = asyncio.Event()
        seen: dict[str, str] = {}

        async def emit(_method: str, params: dict[str, Any]) -> None:
            seen["call_id"] = params["call_id"]
            emitted.set()

        token = bind_emit(emit)
        self.addCleanup(unbind_emit, token)
        task = asyncio.ensure_future(PlanClient(channel).call_tool("submit", {"goal": "g", "steps": STEPS}))
        await asyncio.wait_for(emitted.wait(), timeout=2.0)
        return task, seen["call_id"]

    async def test_verdict_is_delivered_once_and_then_idempotent(self) -> None:
        channel = PlanChannel()
        host = _make_host(channel)
        task, call_id = await self._submitting(channel)

        first = host.agent_plan_result({"call_id": call_id, "approved": True}, None)
        self.assertEqual(first, {"call_id": call_id, "delivered": True})
        payload = json.loads((await asyncio.wait_for(task, timeout=2.0))["content"][0]["text"])
        self.assertIs(payload["approved"], True)
        self.assertEqual(channel.pending, 0)

        # 答晚了不是错误：这一轮已经不等了，如实回 false（与另外两条通道一致）。
        late = host.agent_plan_result({"call_id": call_id, "approved": False, "feedback": "换一套"}, None)
        self.assertEqual(late, {"call_id": call_id, "delivered": False})

    async def test_feedback_is_stripped_and_reachable(self) -> None:
        channel = PlanChannel()
        host = _make_host(channel)
        task, call_id = await self._submitting(channel)

        host.agent_plan_result(
            {"call_id": call_id, "approved": False, "feedback": "  第 2 步换 Flux  "}, None
        )
        payload = json.loads((await asyncio.wait_for(task, timeout=2.0))["content"][0]["text"])
        self.assertIs(payload["approved"], False)
        self.assertEqual(payload["feedback"], "第 2 步换 Flux")

    def test_result_shape_is_checked(self) -> None:
        host = _make_host(PlanChannel())
        with self.assertRaises(RpcError):
            host.agent_plan_result({"call_id": "plan-1"}, None)  # 没有 approved
        with self.assertRaises(RpcError):
            host.agent_plan_result({"call_id": "plan-1", "approved": "yes"}, None)
        with self.assertRaises(RpcError):
            host.agent_plan_result({"approved": True}, None)  # 没有 call_id
        with self.assertRaises(RpcError):
            # 否掉却不说要改哪里：模型只能瞎猜，这里就得挡回去。
            host.agent_plan_result({"call_id": "plan-1", "approved": False}, None)
        with self.assertRaises(RpcError):
            host.agent_plan_result(
                {"call_id": "plan-1", "approved": False, "feedback": "  "}, None
            )
        with self.assertRaises(RpcError):
            host.agent_plan_result({"call_id": "plan-1", "approved": True, "feedback": 7}, None)

    def test_host_without_plan_reports_not_delivered(self) -> None:
        host = _make_host(None)
        self.assertEqual(
            host.agent_plan_result({"call_id": "plan-1", "approved": True}, None),
            {"call_id": "plan-1", "delivered": False},
        )
        self.assertFalse(host.info({}, None)["plan"])

    def test_host_with_plan_says_so_in_info(self) -> None:
        self.assertTrue(_make_host(PlanChannel()).info({}, None)["plan"])


class ChannelUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_on_unknown_call_id_is_a_no_op(self) -> None:
        self.assertFalse(PlanChannel().resolve("nope", ok=True, result={"approved": True}))

    def test_submit_without_a_bound_emit_raises(self) -> None:
        async def go() -> None:
            with self.assertRaises(PlanError):
                await PlanChannel().submit("g", [])

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
