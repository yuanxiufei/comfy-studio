"""取消一轮对话的令牌与"放弃一个 awaitable"的工具函数。

**为什么不用 ``asyncio.Task.cancel()`` 直接杀这一轮**：

* 取消是**预期结果**，不是异常。用户点停止时，历史里那句 assistant 已经带上了
  工具调用，必须把对应的 tool 消息补齐才能继续下一轮（OpenAI 形状要求每个
  tool_call 都有对应的 tool 消息），所以取消点要能"记账"而不是立刻炸穿调用栈；
* 取消要穿过两层等待：等模型（aiohttp 的 HTTP 请求）与等引擎（MCP 子进程）。
  这两处都只是在等一个 awaitable，用 :func:`race` 精确放弃它即可；
* 令牌还能顺手回答"这一轮有没有被要求停下"，供 RPC 层做幂等的停止接口。

形态贴着 JS 那套 ``AbortSignal``（``abort()`` / ``aborted`` / 事件监听）：
参考实现 deepseek-harness 的 agent 循环就是这么贯穿取消的
（``packages/core/agent-loop/src/agent.ts`` 的 ``cancel()`` 与 ``exec.signal``）。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")

#: 没给理由时的默认文案（面板上会显示）。
DEFAULT_REASON = "用户中止"


class Cancelled(RuntimeError):
    """这一轮被取消了。

    故意**不是** :class:`~comfy_studio.agent.AgentError`：取消不是失败，
    调用方（RPC 层）要把它翻成一个正常结果，而不是 -32603。
    """


class CancelToken:
    """一次可取消操作的令牌。创建即"未取消"，:meth:`cancel` 置位后不可撤销。"""

    def __init__(self, reason: str = DEFAULT_REASON) -> None:
        self._event = asyncio.Event()
        self._reason = reason

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def cancel(self, reason: str | None = None) -> bool:
        """置位；返回本次调用是否真的改变了状态（重复取消返回 False）。"""
        if self._event.is_set():
            return False
        if reason:
            self._reason = reason
        self._event.set()
        return True

    def raise_if_cancelled(self, where: str) -> None:
        """在"还没开始"的位置做检查：这时放弃是免费的。"""
        if self._event.is_set():
            raise Cancelled(f"{self._reason}（{where}前停下）")

    async def wait(self) -> None:
        await self._event.wait()


async def race(
    start: Callable[[], Awaitable[T]],
    cancel: CancelToken | None,
    *,
    what: str,
) -> T:
    """等 ``start()`` 起出来的 awaitable；期间令牌被置位就放弃它并抛 :class:`Cancelled`。

    ``start`` 传的是**怎么起这个 awaitable**（而不是 awaitable 本身）：令牌已经置位时
    我们要在起跑前就退出，那时若手里已经攥着一个协程对象，它就成了"没人 await 的协程"。

    放弃的做法是 ``task.cancel()``：aiohttp 会把 HTTP 请求真的断掉；MCP 那侧由
    :meth:`~comfy_studio.mcp.client.McpStdioClient._request` 自己补一条
    ``notifications/cancelled``，让 server 知道别再算了。
    """
    if cancel is not None:
        cancel.raise_if_cancelled(what)
    task = asyncio.ensure_future(start())
    if cancel is None:
        return await task

    waiter = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait({task, waiter}, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        # 外层（宿主关停）把我们取消掉：两层都收干净再往上抛。
        task.cancel()
        waiter.cancel()
        await asyncio.gather(task, waiter, return_exceptions=True)
        raise

    if task in done:
        waiter.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await waiter
        return task.result()

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    raise Cancelled(f"{cancel.reason}（{what}已放弃）")


__all__ = ["DEFAULT_REASON", "CancelToken", "Cancelled", "race"]
