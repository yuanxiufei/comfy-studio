"""stdio MCP 客户端。

把任何一个说 MCP（JSON-RPC 2.0 over stdio）的 server 当子进程拉起来，
然后 :meth:`list_tools` / :meth:`call_tool` 地说话。

前端侧（Comfy-Desktop）默认连的就是引擎侧的 ``comfy_studio.mcp`` —— 也就是
``<ComfyUI>/custom_nodes/comfy_studio``。协议与后端 ``mcp/protocol.py`` 是同一套
（行分隔 JSON-RPC），这里只实现客户端方向需要的那几个方法。
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from ..cancel import CancelToken, Cancelled, race


class McpError(RuntimeError):
    """MCP 通信层面的错误（起不来、超时、协议不符、RPC 报错）。"""


@dataclass(frozen=True)
class McpServerConfig:
    """怎么把这个 server 拉起来。"""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    def spawn_args(self) -> list[str]:
        return [self.command, *self.args]


@dataclass(frozen=True)
class McpTool:
    """server 报出来的一个工具。"""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        """``<server>::<tool>``，多 server 场景下当函数名给模型用。"""
        return f"{self.server}__{self.name}"


class McpStdioClient:
    """单个 stdio server 的连接。用法：``await client.start()`` … ``await client.close()``。"""

    def __init__(self, config: McpServerConfig, request_timeout: float = 120.0) -> None:
        self.config = config
        self.request_timeout = request_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0
        self._stderr_tail: list[str] = []
        self.server_info: dict[str, Any] = {}

    # ---- 生命周期 -------------------------------------------------------

    async def start(self) -> None:
        if self._proc is not None:
            raise McpError(f"MCP server {self.config.name} 已经启动过了")
        env = {**os.environ, **self.config.env}
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.config.spawn_args(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.config.cwd,
                env=env,
            )
        except (OSError, ValueError) as err:
            raise McpError(f"启动 MCP server {self.config.name} 失败: {err}") from err

        self._reader = asyncio.create_task(self._read_loop())
        self._stderr = asyncio.create_task(self._stderr_loop())
        await self._request(
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "comfy-studio-desktop"}},
        )
        await self._notify("notifications/initialized")

    async def close(self) -> None:
        proc, self._proc = self._proc, None
        for task in (self._reader, self._stderr):
            if task is not None:
                task.cancel()
        self._reader = self._stderr = None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(McpError(f"MCP server {self.config.name} 已关闭"))
        self._pending.clear()
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    def stderr_tail(self, limit: int = 20) -> str:
        return "\n".join(self._stderr_tail[-limit:])

    # ---- 内部 IO --------------------------------------------------------

    async def _stderr_loop(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                return
            self._stderr_tail.append(line.decode("utf-8", "replace").rstrip())

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                # server 往 stdout 打了非协议内容：记进 stderr 尾巴便于排查，不打断连接
                self._stderr_tail.append(f"stdout 上的非协议内容: {text[:200]}")
                continue
            msg_id = message.get("id")
            future = self._pending.pop(msg_id, None) if msg_id is not None else None
            if future is None:
                continue  # notification 或已经超时/取消丢掉的响应
            if future.done():
                # 被超时或取消先一步收掉的响应，晚到了就当没看见：不检查的话
                # set_result 会抛 InvalidStateError，把这个读循环整个打死。
                continue
            if "error" in message:
                error = message["error"] or {}
                future.set_exception(
                    McpError(f"MCP 错误 {error.get('code')}: {error.get('message')}")
                )
            else:
                future.set_result(message.get("result") or {})

        reason = McpError(f"MCP server {self.config.name} 的 stdout 关闭了")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(reason)
        self._pending.clear()

    async def _write(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise McpError(f"MCP server {self.config.name} 没有在运行")
        self._proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        cancel: CancelToken | None = None,
    ) -> dict[str, Any]:
        if self._proc is None:
            raise McpError(f"MCP server {self.config.name} 没有在运行")
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        try:
            result = await race(
                partial(asyncio.wait_for, future, timeout=self.request_timeout),
                cancel,
                what=f"MCP {method}",
            )
        except Cancelled:
            # 我们不等了，但 server 可能还在算（跑 skill 就是这种情况）：照 MCP 的规矩
            # 告诉它别再算了。引擎侧的 comfy_studio 目前把通知一律丢掉
            # （``mcp/protocol.py`` 里 ``if msg_id is None: return``），所以这条通知
            # 现在是"发出去了但还没人接"，等引擎侧补齐后才会真的停下队列里的活。
            await self._abandon(request_id, method, "客户端取消")
            raise
        except asyncio.TimeoutError as err:
            await self._abandon(request_id, method, "客户端超时")
            raise McpError(f"{method} 超过 {self.request_timeout} 秒没响应") from err
        if method == "initialize":
            self.server_info = result
        return result

    async def _abandon(self, request_id: int, method: str, reason: str) -> None:
        """放弃一条已发出的请求：从待收表里摘掉，并补一条 ``notifications/cancelled``。

        发不出去也**不覆盖**真正的原因——连接已经断了的话，调用方该看到的是"取消"，
        而不是"写管道失败"。
        """
        self._pending.pop(request_id, None)
        if self._proc is None or self._proc.returncode is not None:
            return
        try:
            await self._notify(
                "notifications/cancelled", {"requestId": request_id, "reason": f"{method}: {reason}"}
            )
        except (McpError, OSError):
            pass

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    # ---- 对外能力 -------------------------------------------------------

    async def list_tools(self) -> list[McpTool]:
        result = await self._request("tools/list")
        raw = result.get("tools")
        if not isinstance(raw, list):
            raise McpError(f"tools/list 返回里没有 tools 数组: {json.dumps(result, ensure_ascii=False)[:200]}")
        tools: list[McpTool] = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise McpError(f"tools/list 里有形状不对的条目: {json.dumps(item, ensure_ascii=False)[:200]}")
            tools.append(
                McpTool(
                    server=self.config.name,
                    name=item["name"],
                    description=str(item.get("description") or ""),
                    input_schema=item.get("inputSchema") or {"type": "object", "properties": {}},
                )
            )
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any], *, cancel: CancelToken | None = None
    ) -> dict[str, Any]:
        return await self._request("tools/call", {"name": name, "arguments": arguments}, cancel=cancel)


__all__ = ["McpError", "McpServerConfig", "McpStdioClient", "McpTool"]
