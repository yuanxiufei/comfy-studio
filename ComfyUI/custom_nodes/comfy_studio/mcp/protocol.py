"""MCP stdio 传输的极简实现：行分隔的 JSON-RPC 2.0（tools 能力子集）。

规范见 modelcontextprotocol.io；不引官方 SDK，避免被 SDK 版本绑住 ——
我们只需要 initialize / tools/list / tools/call 这几个方法。

与最初的 TS 实现（``packages/comfy-mcp/src/protocol.ts``）行为一致：
notification（没有 id）不回包，未知方法回 -32601，handler 抛错回 -32603。

两处偏离这条基线，都是为了"别让畸形输入或已经没人等的请求把这一侧拖住"：

* 超过 :data:`_MAX_LINE` 的单行请求丢弃并回 -32600，**不把它整行读进内存**；
* ``notifications/cancelled``（宿主放弃一条已发出的请求时补发，见宿主侧
  ``mcp/client.py`` 的 ``_abandon``）会真的掐掉对应的请求任务 —— 否则那条请求会一直
  占着工具执行、烧 token，宿主却早已不等了。掐掉的任务带着 ``CancelledError`` 退出，
  工具层据此把已经提交进引擎队列的活也撤下来（见 ``engine/base.py`` 的 ``run_skill``）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Awaitable, Callable

RpcHandler = Callable[[Any], "Awaitable[Any] | Any"]

#: stdin 上一行最长容忍长度（防止畸形输入把内存吃光）。
#: 靠 :meth:`StdioRpcServer.serve` 里的 ``readline(_MAX_LINE + 1)`` 生效：
#: 读满上限还没碰到换行 = 这一行超长，丢弃并回一条 -32600，不整行读进内存。
_MAX_LINE = 8 * 1024 * 1024

# JSON-RPC 2.0 标准错误码
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

#: 宿主放弃一条已发出的请求时补发的通知（MCP 规范的 ``notifications/cancelled``）；
#: ``params`` 形如 ``{"requestId": <那条请求的 id>, "reason": "..."}``。
CANCELLED_NOTIFICATION = "notifications/cancelled"


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
        #: 正在跑的请求：msg_id → 它的任务。收到 ``notifications/cancelled`` 时要按这张表
        #: 找到对应的请求并掐掉 —— 否则那条请求会一直占着工具执行（宿主早已不等了）。
        self._inflight: dict[Any, asyncio.Task[None]] = {}

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
                # 多读一个字符：读满上限还没碰到换行，就说明这一行超长（见 _MAX_LINE）。
                line = await asyncio.to_thread(sys.stdin.readline, _MAX_LINE + 1)
                if line == "":
                    break
                if len(line) > _MAX_LINE and not line.endswith("\n"):
                    await self._send_error(
                        None, INVALID_REQUEST, f"单行请求超过 {_MAX_LINE} 字符上限，已丢弃"
                    )
                    await self._discard_rest_of_line()
                    continue
                text = line.strip()
                if text == "":
                    continue
                task = asyncio.create_task(self._handle_line(text))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _discard_rest_of_line(self) -> None:
        """吃掉被判超长那一行的剩余部分，免得它的尾巴被当成下一条请求。"""
        while True:
            rest = await asyncio.to_thread(sys.stdin.readline, _MAX_LINE + 1)
            if rest == "" or rest.endswith("\n"):
                return

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
            await self._handle_notification(message)
            return
        if not isinstance(method, str):
            await self._send_error(msg_id, INVALID_REQUEST, "缺少 method")
            return

        handler = self._handlers.get(method)
        if handler is None:
            await self._send_error(msg_id, METHOD_NOT_FOUND, f"未知方法: {method}")
            return

        # 登记成"在跑的请求"，取消通知才找得到它。登记要在第一个 await 之前完成。
        task = asyncio.current_task()
        if task is not None:
            self._inflight[msg_id] = task
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
        finally:
            if task is not None and self._inflight.get(msg_id) is task:
                self._inflight.pop(msg_id, None)

        await self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})

    async def _handle_notification(self, message: dict[str, Any]) -> None:
        """通知（没有 id）：按 MCP 规矩不回包。

        ``notifications/cancelled`` 在这里直接处理：要让一条在跑的请求真的停下来，只能掐掉
        它自己的那个任务（干活的是请求任务，调一个 handler 是停不下来的）；掐掉之后也**不回**
        错误包 —— 客户端本来就不等了。

        其余通知交给注册过的 handler（例如 ``notifications/initialized``）：通知没有回包的
        地方，失败只能记到 stderr。
        """
        method = message.get("method")
        if method == CANCELLED_NOTIFICATION:
            self._cancel_inflight(message.get("params"))
            return
        handler = self._handlers.get(method) if isinstance(method, str) else None
        if handler is None:
            return
        try:
            result = handler(message.get("params"))
            if asyncio.iscoroutine(result):
                await result
        except Exception as err:
            print(
                f"[mcp] 通知 {method} 处理失败: {type(err).__name__}: {err}",
                file=sys.stderr,
                flush=True,
            )

    def _cancel_inflight(self, params: Any) -> bool:
        """按 ``notifications/cancelled`` 的 ``requestId`` 掐掉对应请求。

        找不到那条请求（已经跑完、或本来就不是这一侧发的）就什么都不做：取消是尽力而为，
        MCP 也没要求为它回错误。返回是否真的掐掉了一条。
        """
        request_id = params.get("requestId") if isinstance(params, dict) else None
        task = self._inflight.get(request_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def _send(self, obj: Any) -> None:
        payload = json.dumps(obj, ensure_ascii=False)
        async with self._write_lock:
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()

    async def _send_error(self, msg_id: Any, code: int, message: str) -> None:
        await self._send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


__all__ = [
    "CANCELLED_NOTIFICATION",
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
    "RpcError",
    "RpcHandler",
    "StdioRpcServer",
]
