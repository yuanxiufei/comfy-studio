"""``mcp/protocol.py`` 的单元测试：正常往返 + 两条"别被拖住"的路径。

真起子进程、真走 stdin/stdout 的端到端在 ``test_mcp_stdio.py``（要引擎 venv，可能被跳过）；
这里用内存里的 stdin/stdout 替身钉协议层自己的行为 —— 超长行不整行读进内存、
``notifications/cancelled`` 真的掐掉在跑的请求 —— 这两条以前都没有守卫。
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import unittest
from typing import Any
from unittest import mock

from comfy_studio.mcp import protocol
from comfy_studio.mcp.protocol import CANCELLED_NOTIFICATION, INVALID_REQUEST, StdioRpcServer


def _request(msg_id: Any, method: str, params: Any = None) -> str:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    return json.dumps(payload)


def _notification(method: str, params: Any = None) -> str:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        payload["params"] = params
    return json.dumps(payload)


class StdioRpcServerTest(unittest.IsolatedAsyncioTestCase):
    """协议层行为；stdout 换成内存缓冲，好断言写出去的消息。"""

    def setUp(self) -> None:
        self.stdout = io.StringIO()
        patcher = mock.patch.object(sys, "stdout", self.stdout)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _sent(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.stdout.getvalue().splitlines() if line.strip()]

    def _server(self) -> StdioRpcServer:
        server = StdioRpcServer({"name": "test", "version": "0"})
        server.on("ping", lambda _params: {"pong": True})
        return server

    async def _serve(self, *lines: str, server: StdioRpcServer | None = None) -> list[dict[str, Any]]:
        stdin = io.StringIO("".join(f"{line}\n" for line in lines))
        with mock.patch.object(sys, "stdin", stdin):
            await (server or self._server()).serve()
        return self._sent()

    # ---- 正常往返 -------------------------------------------------------

    async def test_request_gets_a_result(self) -> None:
        sent = await self._serve(_request(1, "ping"))
        self.assertEqual(sent, [{"jsonrpc": "2.0", "id": 1, "result": {"pong": True}}])

    async def test_unknown_method_and_bad_json_still_get_an_answer(self) -> None:
        sent = await self._serve("{ 这不是 json", _request(2, "nope"))
        self.assertEqual([msg.get("error", {}).get("code") for msg in sent], [protocol.PARSE_ERROR, protocol.METHOD_NOT_FOUND])

    # ---- 超长行 ---------------------------------------------------------

    async def test_overlong_line_is_dropped_and_the_next_request_still_runs(self) -> None:
        """一行超长不能把它整行读进内存，也不能把它后面那条正常请求带坏。"""
        overlong = _request(1, "ping", {"pad": "x" * 200})
        with mock.patch.object(protocol, "_MAX_LINE", 64):
            sent = await self._serve(overlong, _request(2, "ping"))

        self.assertEqual(len(sent), 2, f"应当只有两条回包（超长行的错误 + 正常请求），实际: {sent}")
        self.assertEqual(sent[0]["id"], None)
        self.assertEqual(sent[0]["error"]["code"], INVALID_REQUEST)
        self.assertIn("64", sent[0]["error"]["message"])
        self.assertEqual(sent[1], {"jsonrpc": "2.0", "id": 2, "result": {"pong": True}})

    async def test_line_exactly_at_the_limit_is_accepted(self) -> None:
        """边界：正好卡在上限（收尾是换行）的请求不该被误判成超长。"""
        line = _request(3, "ping")
        with mock.patch.object(protocol, "_MAX_LINE", len(line)):
            sent = await self._serve(line)
        self.assertEqual(sent, [{"jsonrpc": "2.0", "id": 3, "result": {"pong": True}}])

    # ---- 取消通知 -------------------------------------------------------

    async def test_cancel_notification_stops_the_inflight_request(self) -> None:
        server = self._server()
        started = asyncio.Event()
        saw_cancel = asyncio.Event()

        async def slow(_params: Any) -> dict[str, Any]:
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                saw_cancel.set()
                raise
            return {"never": True}  # pragma: no cover - 被取消就走不到这里

        server.on("tools/call", slow)
        task = asyncio.create_task(server._handle_line(_request(7, "tools/call")))
        await started.wait()

        await server._handle_line(_notification(CANCELLED_NOTIFICATION, {"requestId": 7}))
        await asyncio.gather(task, return_exceptions=True)

        self.assertTrue(saw_cancel.is_set(), "取消通知应当真的把在跑的请求取消掉")
        self.assertTrue(task.cancelled())
        self.assertEqual(self._sent(), [], "取消之后不该再回包（客户端已经不等了）")

    async def test_cancel_for_an_unknown_request_is_ignored(self) -> None:
        server = self._server()
        await server._handle_line(_notification(CANCELLED_NOTIFICATION, {"requestId": 999}))
        await server._handle_line(_notification(CANCELLED_NOTIFICATION, "params 不是对象"))
        self.assertEqual(self._sent(), [], "取消一条不存在的请求不该有任何输出")

    async def test_cancelled_request_id_can_be_reused_afterwards(self) -> None:
        """取消登记要清干净：同一条 id 之后还能正常用。"""
        server = self._server()
        started = asyncio.Event()

        async def slow(_params: Any) -> dict[str, Any]:
            started.set()
            await asyncio.sleep(30)
            return {"never": True}  # pragma: no cover

        server.on("tools/call", slow)
        task = asyncio.create_task(server._handle_line(_request(7, "tools/call")))
        await started.wait()
        await server._handle_line(_notification(CANCELLED_NOTIFICATION, {"requestId": 7}))
        await asyncio.gather(task, return_exceptions=True)

        await server._handle_line(_request(7, "ping"))
        self.assertEqual(self._sent(), [{"jsonrpc": "2.0", "id": 7, "result": {"pong": True}}])

    # ---- 通知 handler ---------------------------------------------------

    async def test_registered_notification_handler_actually_runs(self) -> None:
        """以前 notification 被一律丢掉，注册的 handler 从来没被调用过。"""
        server = self._server()
        seen: list[Any] = []
        server.on("notifications/initialized", lambda params: seen.append(params))

        await server._handle_line(_notification("notifications/initialized", {"client": "x"}))

        self.assertEqual(seen, [{"client": "x"}])
        self.assertEqual(self._sent(), [], "通知不该有回包")


if __name__ == "__main__":
    unittest.main()
