"""回程通道：把一次「宿主 → 桌面壳 → 对面」的往返收成一个 future。

有些能力宿主进程自己够不着：

* 画布在 ComfyUI 前端页面里 —— 只有那一页拿着用户手头未必保存过的图；
* 「这样做行不行」得问用户本人 —— 只有桌面壳连着一个能回答的人。

这两件事的形状是一样的：宿主推一条 ``agent/event`` 通知出去，桌面壳接住、办完再用一条
RPC 把结果送回来，唤醒等着的 future。所以实现只留一份：:class:`Channel` 管「发事件 +
等 future + 收结果」，事件类型、call_id 前缀、报错措辞由用它的模块定下来
（见 :mod:`comfy_studio.canvas` 与 :mod:`comfy_studio.review`）。

emit 用 contextvars 而不是成员变量：一个宿主进程里可以同时跑好几个会话的一轮，工具执行
又都在 ``asyncio.create_task`` 里，正好顺着 context 传下去。
"""

from __future__ import annotations

import asyncio
import contextvars
from typing import Any, Awaitable, Callable

from .cancel import CancelToken, race

#: 往本轮 RPC 现场推一条通知的形状（就是 ``RpcContext.emit``）。
Emit = Callable[[str, dict[str, Any]], Awaitable[None]]

#: 当前这一轮的 emit（由 :meth:`~comfy_studio.server.StudioHost.agent_chat` 起跑前绑定）。
_CURRENT_EMIT: contextvars.ContextVar[Emit | None] = contextvars.ContextVar(
    "comfy_studio_shell_emit", default=None
)


def bind_emit(emit: Emit) -> contextvars.Token[Emit | None]:
    """把这一轮的 emit 绑到当前 context；返回的 token 用来 :func:`unbind_emit`。"""
    return _CURRENT_EMIT.set(emit)


def unbind_emit(token: contextvars.Token[Emit | None]) -> None:
    _CURRENT_EMIT.reset(token)


class ChannelError(RuntimeError):
    """回程通道层面的错误：没人接、对面说失败、等超时。"""


class Channel:
    """一条回程：推一条事件出去，等结果回来。

    子类负责把三件事定下来：``event_type``（``agent/event`` 里的 ``type``）、call_id 前缀、
    以及超时/失败时怎么措辞；然后包一层面向工具的出参形状，对外只暴露那个方法。
    """

    def __init__(
        self,
        event_type: str,
        *,
        timeout: float,
        id_prefix: str,
        peer: str,
        error_type: type[ChannelError] = ChannelError,
    ) -> None:
        self.event_type = event_type
        self.timeout = timeout
        self.id_prefix = id_prefix
        #: 对面是谁，只用在报错措辞里（"画布页面没在跑" / "对话面板没在响应"）。
        self.peer = peer
        self.error_type = error_type
        #: call_id → 等结果的 future；对面回话或超时后都必须摘掉，别攒着。
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._next_id = 0

    @property
    def pending(self) -> int:
        """还等着的往返数（面板/诊断用）。"""
        return len(self._pending)

    async def _round_trip(
        self,
        payload: dict[str, Any],
        *,
        what: str,
        cancel: CancelToken | None = None,
        timeout: float | None = None,
    ) -> Any:
        """派一条事件出去并等结果；失败/超时/取消一律往上抛，不返回半成品。"""
        emit = _CURRENT_EMIT.get()
        if emit is None:
            raise self.error_type("这一轮没有绑定桌面壳通道：这个工具只能在 agent/chat 里用")
        if cancel is not None:
            cancel.raise_if_cancelled(what)

        self._next_id += 1
        call_id = f"{self.id_prefix}-{self._next_id}"
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        limit = self.timeout if timeout is None else timeout
        try:
            await emit("agent/event", {"type": self.event_type, "call_id": call_id, **payload})
            try:
                reply = await race(
                    lambda: asyncio.wait_for(future, limit), cancel, what=what
                )
            except asyncio.TimeoutError as err:
                raise self.error_type(
                    f"{what}等了 {limit:g} 秒没有回音：桌面壳没接这条通道，或者{self.peer}"
                ) from err
        finally:
            self._pending.pop(call_id, None)

        if reply.get("ok") is not True:
            raise self.error_type(str(reply.get("error") or f"{what}失败"))
        return reply.get("result")

    def resolve(
        self, call_id: str, *, ok: bool, result: Any = None, error: str | None = None
    ) -> bool:
        """收下对面的结果；返回是否真的有人收（false = 这一轮已经不等了）。"""
        future = self._pending.get(call_id)
        if future is None or future.done():
            return False
        future.set_result({"ok": ok, "result": result, "error": error})
        return True

    def fail_all(self, reason: str) -> int:
        """宿主关停时把还等着的往返都放掉，别让它们拖到超时。"""
        waiting = [f for f in self._pending.values() if not f.done()]
        for future in waiting:
            future.set_exception(self.error_type(reason))
        self._pending.clear()
        return len(waiting)


__all__ = [
    "Channel",
    "ChannelError",
    "Emit",
    "bind_emit",
    "unbind_emit",
]
