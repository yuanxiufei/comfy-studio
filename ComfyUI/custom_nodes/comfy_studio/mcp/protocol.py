"""MCP stdio 传输的极简实现：行分隔的 JSON-RPC 2.0（tools 能力子集）。

规范见 modelcontextprotocol.io；不引官方 SDK，避免被 SDK 版本绑住 ——
我们只需要 initialize / tools/list / tools/call 这几个方法。

与最初的 TS 实现（``packages/comfy-mcp/src/protocol.ts``）行为一致：
notification（没有 id）不回包，未知方法回 -32601，handler 抛错回 -32603。
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Awaitable, Callable

RpcHandler = Callable[[Any], "Awaitable[Any] | Any"]

#: stdin 上一行最长容忍长度（防止畸形输入把内存吃光）。
_MAX_LINE = 8 * 1024 * 1024

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """handler 想指定 JSON-RPC 错误码时抛这个。

    约定：协议层面的问题（方法不存在、参数形状不对、工具名不存在）用 RpcError，
    工具**执行**失败则照 MCP 的规矩回 ``isError`` 的工具结果，不占协议错误码。
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class StdioRpcServer:
    """把 stdin 的每行当作一个 JSON-RPC 请求，响应写回 stdout。

    stdout 只能出现协议消息，所以一切诊断输出都走 stderr。
    """

    def __init__(self, server_info: dict[str, str]) -> None:
        self._server_info = server_info
        self._handlers: dict[str, RpcHandler] = {}
        self._write_lock = asyncio.Lock()

    def on(self, method: str, handler: RpcHandler) -> "StdioRpcServer":
        self._handlers[method] = handler
        return self

    @property
    def info(self) -> dict[str, str]:
        return self._server_info

    async def serve(self) -> None:
        """读到 EOF 为止。每个请求在自己的任务里跑，长任务不阻塞后续请求。"""
        tasks: set[asyncio.Task[None]] = set()
        try:
            while True:
                line = await asyncio.to_thread(sys.stdin.readline)
                if line == "":
                    break
                text = line.strip()
                if text == "":
                    continue
                task = asyncio.create_task(self._handle_line(text))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle_line(self, text: str) -> None:
        try:
            message = json.loads(text)
        except json.JSONDecodeError as err:
            await self._send_error(None, PARSE_ERROR, f"请求不是合法 JSON: {err}")
            return

        if not isinstance(message, dict):
            await self._send_error(None, INVALID_REQUEST, "请求必须是 JSON 对象")
            return

        msg_id = message.get("id")
        method = message.get("method")
        if msg_id is None:
            return  # notification，不需要响应
        if not isinstance(method, str):
            await self._send_error(msg_id, INVALID_REQUEST, "缺少 method")
            return

        handler = self._handlers.get(method)
        if handler is None:
            await self._send_error(msg_id, METHOD_NOT_FOUND, f"未知方法: {method}")
            return

        try:
            result = handler(message.get("params"))
            if asyncio.iscoroutine(result):
                result = await result
        except RpcError as err:  # handler 指定的错误码
            await self._send_error(msg_id, err.code, err.message)
            return
        except Exception as err:  # 其余异常一律回 -32603，细节带上原文
            await self._send_error(msg_id, INTERNAL_ERROR, f"{type(err).__name__}: {err}")
            return

        await self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    async def _send(self, obj: Any) -> None:
        payload = json.dumps(obj, ensure_ascii=False)
        async with self._write_lock:
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()

    async def _send_error(self, msg_id: Any, code: int, message: str) -> None:
        await self._send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "RpcError",
    "RpcHandler",
    "StdioRpcServer",
]
