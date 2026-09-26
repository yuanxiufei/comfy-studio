"""画布通道：工具表、事件形状、回程、取消与超时。

这里全程用假壳（一个记录事件并立刻回话的 ``emit``），不起 Electron、不起页面——
那条真实的「宿主 → 桌面壳 → 画布页面」链路归 ``test_host_e2e`` 与前端 vitest。
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from comfy_studio.canvas import (
    CANVAS_TOOLS,
    CanvasChannel,
    CanvasClient,
    CanvasError,
    bind_emit,
    unbind_emit,
)
from comfy_studio.cancel import CancelToken, Cancelled
from comfy_studio.mcp import McpHub
from comfy_studio.rpc import RpcError
from comfy_studio.server import StudioHost
from comfy_studio.skills import SkillCatalog


def _make_host(channel: CanvasChannel | None) -> StudioHost:
    """只挂画布通道的最小宿主（MCP 一个都不拉）。"""
    extra: list[Any] = [CanvasClient(channel)] if channel is not None else []
    hub = McpHub([], extra_clients=extra)
    return StudioHost(hub, SkillCatalog(hub), canvas=channel)


class ChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_sends_canvas_call_and_reads_text_back(self) -> None:
        channel = CanvasChannel(timeout=1.0)
        client = CanvasClient(channel)
        sent: list[tuple[str, dict[str, Any]]] = []

        async def emit(method: str, params: dict[str, Any]) -> None:
            sent.append((method, params))
            # 模拟桌面壳：拿到 canvas_call 就去页面执行，然后把结果送回来。
            channel.resolve(params["call_id"], ok=True, result={"node_count": 3})

        token = bind_emit(emit)
        try:
            result = await client.call_tool("canvas_snapshot", {})
        finally:
            unbind_emit(token)

        self.assertFalse(result["isError"])
        self.assertEqual(json.loads(result["content"][0]["text"]), {"node_count": 3})
        method, params = sent[0]
        self.assertEqual(method, "agent/event")
        self.assertEqual(params["type"], "canvas_call")
        self.assertEqual(params["op"], "snapshot")
        # include_widgets 有默认值，模型不传时也要出现在动作里。
        self.assertEqual(params["args"], {"include_widgets": False})
        self.assertEqual(channel.pending, 0)

    async def test_page_error_becomes_is_error_not_exception(self) -> None:
        channel = CanvasChannel(timeout=1.0)
        client = CanvasClient(channel)

        async def emit(_method: str, params: dict[str, Any]) -> None:
            channel.resolve(params["call_id"], ok=False, error="画布里没有根图")

        token = bind_emit(emit)
        try:
            result = await client.call_tool("canvas_snapshot", {})
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("画布里没有根图", result["content"][0]["text"])

    async def test_timeout_is_explicit(self) -> None:
        client = CanvasClient(CanvasChannel(timeout=0.05))

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            return  # 没人接这条通道：永远不回话

        token = bind_emit(emit)
        try:
            result = await client.call_tool("canvas_snapshot", {})
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("没有回音", result["content"][0]["text"])

    async def test_no_shell_bound_is_explicit(self) -> None:
        result = await CanvasClient(CanvasChannel()).call_tool("canvas_snapshot", {})
        self.assertTrue(result["isError"])
        self.assertIn("没有绑定桌面壳通道", result["content"][0]["text"])

    async def test_cancelled_token_stops_before_dispatching(self) -> None:
        channel = CanvasChannel(timeout=1.0)
        client = CanvasClient(channel)
        sent: list[Any] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)

        cancel = CancelToken()
        cancel.cancel("用户中止")
        token = bind_emit(emit)
        try:
            with self.assertRaises(Cancelled):
                await client.call_tool("canvas_snapshot", {}, cancel=cancel)
        finally:
            unbind_emit(token)

        # 取消发生在起跑前：一个动作都不该派出去。
        self.assertEqual(sent, [])
        self.assertEqual(channel.pending, 0)

    async def test_cancel_while_waiting_abandons_the_call(self) -> None:
        channel = CanvasChannel(timeout=5.0)
        client = CanvasClient(channel)
        cancel = CancelToken()
        emitted = asyncio.Event()

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            emitted.set()  # 派出去之后就不回话了，模拟页面还在忙

        token = bind_emit(emit)
        try:
            task = asyncio.ensure_future(client.call_tool("canvas_snapshot", {}, cancel=cancel))
            await emitted.wait()
            cancel.cancel("用户中止")
            # 取消**不是工具失败**：Cancelled 要一路冒到 agent 循环去补账
            # （loop._run_tool 特意不吞它），不能在这里被压成一段 isError 文本。
            with self.assertRaises(Cancelled):
                await asyncio.wait_for(task, timeout=2.0)
        finally:
            unbind_emit(token)

        self.assertEqual(channel.pending, 0)

    async def test_bad_arguments_never_reach_the_page(self) -> None:
        channel = CanvasChannel(timeout=1.0)
        client = CanvasClient(channel)
        sent: list[Any] = []

        async def emit(_method: str, params: dict[str, Any]) -> None:
            sent.append(params)

        token = bind_emit(emit)
        try:
            result = await client.call_tool("canvas_load_workflow", {"graph": "不是对象"})
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("graph", result["content"][0]["text"])
        self.assertEqual(sent, [])

    async def test_unknown_tool_is_a_protocol_error(self) -> None:
        client = CanvasClient(CanvasChannel())
        with self.assertRaises(Exception) as caught:
            await client.call_tool("canvas_teleport", {})
        self.assertIn("canvas_teleport", str(caught.exception))

    async def test_fail_all_releases_waiting_calls(self) -> None:
        channel = CanvasChannel(timeout=5.0)
        client = CanvasClient(channel)
        cancel = CancelToken()
        emitted = asyncio.Event()

        async def emit(_method: str, _params: dict[str, Any]) -> None:
            emitted.set()

        token = bind_emit(emit)
        try:
            task = asyncio.ensure_future(client.call_tool("canvas_snapshot", {}, cancel=cancel))
            await emitted.wait()
            self.assertEqual(channel.fail_all("宿主关停"), 1)
            result = await asyncio.wait_for(task, timeout=2.0)
        finally:
            unbind_emit(token)

        self.assertTrue(result["isError"])
        self.assertIn("宿主关停", result["content"][0]["text"])


class ToolTableTests(unittest.IsolatedAsyncioTestCase):
    async def test_hub_exposes_the_canvas_tools(self) -> None:
        hub = McpHub([], extra_clients=[CanvasClient(CanvasChannel())])
        await hub.start()
        names = sorted(tool.qualified_name for tool in hub.tools)
        self.assertEqual(names, ["canvas__canvas_load_workflow", "canvas__canvas_snapshot"])
        for tool in hub.tools:
            self.assertEqual(tool.server, "canvas")
            self.assertEqual(tool.input_schema["type"], "object")
        self.assertEqual(len(CANVAS_TOOLS), 2)

    async def test_canvas_tool_description_warns_about_replacing_the_graph(self) -> None:
        spec = next(s for s in CANVAS_TOOLS if s.name == "canvas_load_workflow")
        self.assertIn("替换", spec.description)


class HostResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_result_is_delivered_once_and_then_idempotent(self) -> None:
        channel = CanvasChannel()
        host = _make_host(channel)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        channel._pending["canvas-1"] = future

        first = host.agent_canvas_result(
            {"call_id": "canvas-1", "ok": True, "result": {"node_count": 3}}, None
        )
        self.assertEqual(first, {"call_id": "canvas-1", "delivered": True})
        self.assertEqual(await future, {"ok": True, "result": {"node_count": 3}, "error": None})

        # 又来一条同一个 call_id：这一轮已经收过了，不当错误。
        late = host.agent_canvas_result({"call_id": "canvas-1", "ok": True}, None)
        self.assertEqual(late["delivered"], False)

    async def test_result_shape_is_checked(self) -> None:
        host = _make_host(CanvasChannel())
        with self.assertRaises(RpcError):
            host.agent_canvas_result({"call_id": "canvas-1", "ok": "yes"}, None)
        with self.assertRaises(RpcError):
            host.agent_canvas_result({"ok": True}, None)

    def test_host_without_canvas_reports_not_delivered(self) -> None:
        host = _make_host(None)
        self.assertEqual(
            host.agent_canvas_result({"call_id": "canvas-1", "ok": True}, None),
            {"call_id": "canvas-1", "delivered": False},
        )
        self.assertFalse(host.info(None, None)["canvas"])


class ChannelUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_on_unknown_call_id_is_a_no_op(self) -> None:
        channel = CanvasChannel()
        self.assertFalse(channel.resolve("nope", ok=True, result=1))

    async def test_resolve_after_the_future_is_done_is_a_no_op(self) -> None:
        channel = CanvasChannel()
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        future.cancel()
        channel._pending["canvas-9"] = future
        self.assertFalse(channel.resolve("canvas-9", ok=True, result=1))

    def test_call_without_a_bound_emit_raises(self) -> None:
        async def go() -> None:
            with self.assertRaises(CanvasError):
                await CanvasChannel().call("snapshot", {})

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
