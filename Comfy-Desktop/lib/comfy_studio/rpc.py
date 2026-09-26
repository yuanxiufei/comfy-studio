"""桌面壳 ↔ comfy_studio 宿主之间的 stdio 协议：行分隔 JSON-RPC 2.0。

为什么自己写：桌面壳是 Electron（TypeScript），要一个**它能直接说**的进程接口；
行分隔 JSON 是两边最容易对齐、也最容易照着调试的形态（stdout 只跑协议，
诊断一律走 stderr）。

与引擎侧那个 MCP server 的区别在于方向：那边是**服务端**给外部 agent 提供工具，
这边是**宿主**——既要给桌面壳提供 ``skills/*`` ``agent/*`` 这些自己的方法，
也会在长任务（``agent/chat``）进行中主动往 stdout 推 ``agent/event`` 通知，
让面板能边跑边显示。
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class RpcError(Exception):
    """想指定 JSON-RPC 错误码时抛这个。

    约定：协议层面的问题（方法不存在、参数形状不对）用 RpcError；
    业务失败（模型没配、skill 跑挂）按调用方约定回结构化结果或带码的错误。
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RpcContext:
    """handler 的调用现场：请求 id + 主动推送通知的出口。"""

    request_id: Any
    server: "StdioRpcServer"

    async def emit(self, method: str, params: dict[str, Any]) -> None:
        """推一条通知（无 id 的消息）；params 里带 requestId 让调用方能对上号。"""
        await self.server.notify(method, {**params, "requestId": self.request_id})


RpcHandler = Callable[[Any, RpcContext], "Awaitable[Any] | Any"]


class StdioRpcServer:
    """把 stdin 的每一行当作一个 JSON-RPC 请求，响应与通知写回 stdout。"""

    def __init__(self, server_info: dict[str, str]) -> None:
        self._server_info = dict(server_info)
        self._handlers: dict[str, RpcHandler] = {}
        self._write_lock = asyncio.Lock()
        #: stdin 一关就调一次（在等剩余任务之前）。用来叫停在飞的长任务——否则
        #: 关面板时一轮跑 skill 的对话会让退出卡到工具的 1800 秒超时上。
        #: 返回值忽略；返回 awaitable 会被 await。
        self.on_close: Callable[[], Any] | None = None

    def on(self, method: str, handler: RpcHandler) -> "StdioRpcServer":
        self._handlers[method] = handler
        return self

    @property
    def methods(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    async def serve(self) -> None:
        """读到 stdin EOF 为止。每个请求在自己的任务里跑，长任务不阻塞后续请求。"""
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
            if self.on_close is not None:
                closed = self.on_close()
                if asyncio.iscoroutine(closed):
                    await closed
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # ---- 内部 -----------------------------------------------------------

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
            return  # 通知，不需要响应
        if not isinstance(method, str):
            await self._send_error(msg_id, INVALID_REQUEST, "缺少 method")
            return

        handler = self._handlers.get(method)
        if handler is None:
            known = ", ".join(self.methods) or "（无）"
            await self._send_error(msg_id, METHOD_NOT_FOUND, f"未知方法 {method}；可用: {known}")
            return

        try:
            result = handler(message.get("params"), RpcContext(request_id=msg_id, server=self))
            if asyncio.iscoroutine(result):
                result = await result
        except RpcError as err:  # handler 指定的错误码
            await self._send_error(msg_id, err.code, err.message)
            return
        except Exception as err:  # 其余异常一律回 -32603，把原文带上便于排查
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
    "RpcContext",
    "RpcError",
    "RpcHandler",
    "StdioRpcServer",
]
