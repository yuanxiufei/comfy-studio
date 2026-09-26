"""审核节点：工具表、事件形状、回程、取消与超时。

和画布通道一样的纪律——这里全程用假壳（一个记录事件并立刻回话的 ``emit``），不起
Electron、不起面板；那条真实的「宿主 → 桌面壳 → 问答卡」链路归 ``test_host_e2e``
与前端 vitest。
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from comfy_studio.canvas import DEFAULT_CALL_TIMEOUT
from comfy_studio.cancel import CancelToken, Cancelled
from comfy_studio.channel import bind_emit, unbind_emit
from comfy_studio.mcp import McpHub
from comfy_studio.review import (
    DEFAULT_ASK_TIMEOUT,
    REVIEW_TOOLS,
    ReviewChannel,
    ReviewClient,
    ReviewError,
)
from comfy_studio.rpc import RpcError
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog


def _make_host(review: ReviewChannel | None, canvas: Any = None) -> StudioHost:
    """只挂审核通道的最小宿主（MCP 一个都不拉）。"""
    extra: list[Any] = [ReviewClient(review)] if review is not None else []
    hub = McpHub([], extra_clients=extra)
    return StudioHost(hub, SkillCatalog(hub), canvas=canvas, review=review)


class ChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_sends_ask_user_and_reads_the_answer_back(self) -> None:
        channel = ReviewChannel(timeout=1.0)
        client = ReviewClient(channel)
        sent: list[tuple[str, dict[str, Any]]] = []

        async def emit(method: str, params: dict[str, Any]) -> None:
            sent.append((method, params))
            # 模拟面板：把 ask_user 画成问答卡，用户点完把答案送回来。
            channel.resolve(params["call_id"], ok=True, result="用 SDXL 那套")

        token = bind_emit(emit)
        try:
            result = await client.call_tool("ask_user", {"question": "用哪套工作流？", "options": ["SDXL", "Flux"]})
        finally:
            unbind_emit(token)

        self.assertFalse(result["isError"])
        self.assertEqual(
            json.loads(result["content"][0]["text"]),
            {"question": "用哪套工作流？", "answer": "用 SDXL 那套"},
        )
        method, params = sent[0]
        self.assertEqual(method, "agent/event")
        self.assertEqual(params["type"], "ask_user")
        self.assertEqual(params["question"], "用哪套工作流？")
        self.assertEqual(params["options"], ["SDXL", "Flux"])
        self.assertTrue(str(params["call_id"]).startswith("ask-"))
        self.assertEqual(channel.pending, 0)

    async def test_options_default_to_empty_list(self) -> None:
        channel = ReviewChannel(timeout=1.0)
        client = ReviewClient(channel)
        sent: list[dict[str, Any]] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)
            channel.resolve(params["call_id"], ok=True, result="随便")

        token = bind_emit(emit)
        try:
            await client.call_tool("ask_user", {"question": "要不要覆盖？"})
        finally:
            unbind_emit(token)

        # 面板要能区分"没给选项"和"给了空选项"，所以这个键必须存在。
        self.assertEqual(sent[0]["options"], [])

    async def test_answer_is_stripped(self) -> None:
        channel = ReviewChannel(timeout=1.0)
        client = ReviewClient(channel)

        async def emit(_method: str, params: dict[str, Any]) -> None:
            channel.resolve(params["call_id"], ok=True, result="  Flux  ")

        token = bind_emit(emit)
        try:
            result = await client.call_tool("ask_user", {"question": "用哪个？"})
        finally:
            unbind_emit(token)

        self.assertEqual(json.loads(result["content"][0]["text"])["answer"], "Flux")

    async def test_empty_answer_is_an_error_not_a_silent_default(self) -> None:
        channel = ReviewChannel(timeout=1.0)
        client = ReviewClient(channel)

        async def emit(_method: str, params: dict[str, Any]) -> None:
            channel.resolve(params["call_id"], ok=True, result="   ")

        token = bind_emit(emit)
        try:
            result = await client.call_tool("ask_user", {"question": "用哪个？"})
        finally:
            unbind_emit(token)

        # 沉默不能被当成"随便你"：宁可报错让模型重问。
        self.assertTrue(result["isError"])
        self.assertIn("空回答不算答案", result["content"][0]["text"])

    async def test_timeout_is_explicit(self) -> None:
        client = ReviewClient(ReviewChannel(timeout=0.05))

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            return  # 没人接这条通道：面板没开或没人答

        token = bind_emit(emit)
        try:
            result = await client.call_tool("ask_user", {"question": "在吗？"})
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("没有回音", result["content"][0]["text"])
        self.assertIn("对话面板", result["content"][0]["text"])

    async def test_no_shell_bound_is_explicit(self) -> None:
        result = await ReviewClient(ReviewChannel()).call_tool("ask_user", {"question": "在吗？"})
        self.assertTrue(result["isError"])
        self.assertIn("没有绑定桌面壳通道", result["content"][0]["text"])

    async def test_cancelled_token_stops_before_dispatching(self) -> None:
        channel = ReviewChannel(timeout=1.0)
        client = ReviewClient(channel)
        sent: list[Any] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)

        cancel = CancelToken()
        cancel.cancel("用户中止")
        token = bind_emit(emit)
        try:
            with self.assertRaises(Cancelled):
                await client.call_tool("ask_user", {"question": "在吗？"}, cancel=cancel)
        finally:
            unbind_emit(token)

        self.assertEqual(sent, [])
        self.assertEqual(channel.pending, 0)

    async def test_cancel_while_waiting_abandons_the_question(self) -> None:
        channel = ReviewChannel(timeout=5.0)
        client = ReviewClient(channel)
        cancel = CancelToken()
        emitted = asyncio.Event()

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            emitted.set()  # 派出去了就不回话：模拟用户一直没答

        token = bind_emit(emit)
        try:
            task = asyncio.ensure_future(
                client.call_tool("ask_user", {"question": "在吗？"}, cancel=cancel)
            )
            await emitted.wait()
            cancel.cancel("用户中止")
            # 取消不是工具失败：Cancelled 要冒到 agent 循环去收尾，不能压成 isError 文本。
            with self.assertRaises(Cancelled):
                await asyncio.wait_for(task, timeout=2.0)
        finally:
            unbind_emit(token)

        self.assertEqual(channel.pending, 0)

    async def test_bad_arguments_never_reach_the_user(self) -> None:
        channel = ReviewChannel(timeout=1.0)
        client = ReviewClient(channel)
        sent: list[Any] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)

        token = bind_emit(emit)
        try:
            cases = (
                {},  # 没有 question
                {"question": "   "},
                {"question": "选一个", "options": "SDXL"},  # options 不是数组
                {"question": "选一个", "options": [""]},  # 选项里混了空串
            )
            for case in cases:
                result = await client.call_tool("ask_user", case)
                self.assertTrue(result["isError"], case)
        finally:
            unbind_emit(token)

        # 形状不对就别拿去打扰用户：一张卡都不该弹出来。
        self.assertEqual(sent, [])

    async def test_unknown_tool_is_a_protocol_error(self) -> None:
        client = ReviewClient(ReviewChannel())
        with self.assertRaises(Exception) as caught:
            await client.call_tool("ask_god", {})
        self.assertIn("ask_god", str(caught.exception))

    async def test_fail_all_releases_waiting_questions(self) -> None:
        channel = ReviewChannel(timeout=5.0)
        client = ReviewClient(channel)
        emitted = asyncio.Event()

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            emitted.set()

        token = bind_emit(emit)
        try:
            task = asyncio.ensure_future(client.call_tool("ask_user", {"question": "在吗？"}))
            await emitted.wait()
            self.assertEqual(channel.fail_all("宿主关停"), 1)
            result = await asyncio.wait_for(task, timeout=2.0)
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("宿主关停", result["content"][0]["text"])


class ToolTableTests(unittest.IsolatedAsyncioTestCase):
    async def test_hub_exposes_the_review_tool(self) -> None:
        hub = McpHub([], extra_clients=[ReviewClient(ReviewChannel())])
        await hub.start()
        self.assertEqual([t.qualified_name for t in hub.tools], ["review__ask_user"])
        tool = hub.tools[0]
        self.assertEqual(tool.server, "review")
        self.assertEqual(tool.input_schema["required"], ["question"])
        self.assertEqual(len(REVIEW_TOOLS), 1)

    def test_description_tells_the_model_to_ask_instead_of_guessing(self) -> None:
        spec = REVIEW_TOOLS[0]
        self.assertIn("关键节点", spec.description)
        self.assertIn("不要自己替用户猜", spec.description)

    def test_the_waiting_limit_is_longer_than_a_canvas_action(self) -> None:
        # 问的是人：等得比页面里一次同步调用久；但也必须有头，面板关掉时不能永远挂着。
        self.assertGreater(DEFAULT_ASK_TIMEOUT, DEFAULT_CALL_TIMEOUT)

    async def test_status_view_handles_a_client_without_a_command_line(self) -> None:
        """``mcp/servers`` 得如实报出进程内通道：它没有命令行，但不是配置坏了。"""
        hub = McpHub([], extra_clients=[ReviewClient(ReviewChannel())])
        await hub.start()
        (server,) = hub.servers()
        self.assertEqual(server["name"], "review")
        self.assertEqual(server["transport"], "in-process")
        self.assertIsNone(server["command"])
        self.assertEqual(server["args"], [])
        self.assertIs(server["alive"], True)


class HostResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_is_delivered_once_and_then_idempotent(self) -> None:
        channel = ReviewChannel()
        host = _make_host(channel)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        channel._pending["ask-1"] = future

        first = host.agent_answer({"call_id": "ask-1", "answer": "用 SDXL"}, None)
        self.assertEqual(first, {"call_id": "ask-1", "delivered": True})
        self.assertEqual(await future, {"ok": True, "result": "用 SDXL", "error": None})

        late = host.agent_answer({"call_id": "ask-1", "answer": "用 Flux"}, None)
        self.assertEqual(late["delivered"], False)

    def test_answer_shape_is_checked(self) -> None:
        host = _make_host(ReviewChannel())
        with self.assertRaises(RpcError):
            host.agent_answer({"call_id": "ask-1"}, None)  # 没有 answer
        with self.assertRaises(RpcError):
            host.agent_answer({"call_id": "ask-1", "answer": "   "}, None)
        with self.assertRaises(RpcError):
            host.agent_answer({"answer": "用 SDXL"}, None)  # 没有 call_id

    def test_host_without_review_reports_not_delivered(self) -> None:
        host = _make_host(None)
        self.assertEqual(
            host.agent_answer({"call_id": "ask-1", "answer": "用 SDXL"}, None),
            {"call_id": "ask-1", "delivered": False},
        )
        self.assertFalse(host.info(None, None)["review"])

    def test_host_with_review_says_so_in_info(self) -> None:
        self.assertTrue(_make_host(ReviewChannel()).info(None, None)["review"])


class ChannelUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_on_unknown_call_id_is_a_no_op(self) -> None:
        self.assertFalse(ReviewChannel().resolve("nope", ok=True, result="x"))

    def test_ask_without_a_bound_emit_raises(self) -> None:
        async def go() -> None:
            with self.assertRaises(ReviewError):
                await ReviewChannel().ask("在吗？", [])

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
