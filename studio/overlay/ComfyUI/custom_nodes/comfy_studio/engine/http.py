"""进程外实现：对着本机引擎说 HTTP。

MCP server 被 Claude / Cursor 之类的宿主 spawn 出来时走这条路；用到的接口都是
上游既有路由（``ComfyUI/server.py``）：``/object_info``、``/prompt``、``/history``、
``/queue``、``/interrupt``。这些路由同时挂在 ``/`` 与 ``/api`` 前缀下
（``ComfyUI/server.py:1231-1242`` 做的复制），这里用不带前缀的短路径。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import aiohttp

from ..skills.runner import DEFAULT_TIMEOUT, StatusCallback
from .base import EngineClient, EngineError

_POLL_INTERVAL = 0.5


class HttpEngine(EngineClient):
    """通过 HTTP 访问一个已经在跑的 ComfyUI。"""

    def __init__(self, base_url: str = "http://127.0.0.1:8188", request_timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _json(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        try:
            async with session.request(method, url, json=payload) as resp:
                text = await resp.text()
                if resp.status >= 400:
                    raise EngineError(f"{method} {path} 返回 {resp.status}: {_short(text)}")
                if not text:
                    return None
                try:
                    return _json_loads(text)
                except ValueError as err:
                    raise EngineError(f"{method} {path} 返回的不是 JSON: {err}") from err
        except aiohttp.ClientError as err:
            raise EngineError(f"连不上引擎 {url}: {err}") from err

    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        path = "/object_info" if node_class is None else f"/object_info/{node_class}"
        data = await self._json("GET", path)
        if not isinstance(data, dict):
            raise EngineError(f"/object_info 返回了意外内容: {type(data).__name__}")
        return data

    async def submit(self, workflow: dict[str, Any]) -> str:
        session = await self._get_session()
        url = f"{self.base_url}/prompt"
        try:
            async with session.post(url, json={"prompt": workflow}) as resp:
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise EngineError(f"连不上引擎 {url}: {err}") from err

        data = _json_loads(text) if text else None
        if resp.status >= 400:
            detail = data.get("error") if isinstance(data, dict) else None
            message = detail.get("message") if isinstance(detail, dict) else _short(text)
            node_errors = data.get("node_errors") if isinstance(data, dict) else None
            raise EngineError(f"提交被拒: {message}（node_errors={node_errors}）")
        if not isinstance(data, dict) or "prompt_id" not in data:
            raise EngineError(f"提交返回了意外内容: {_short(text)}")
        return str(data["prompt_id"])

    async def _is_running(self, prompt_id: str) -> bool:
        snapshot = await self.queue()
        for item in snapshot.get("queue_running") or []:
            if isinstance(item, (list, tuple)) and len(item) > 1 and item[1] == prompt_id:
                return True
        return False

    async def wait(
        self, prompt_id: str, timeout: float | None = DEFAULT_TIMEOUT, on_status: StatusCallback | None = None
    ) -> dict[str, Any]:
        deadline = None if timeout is None else time.monotonic() + timeout
        last_state = ""
        while True:
            entry = await self.history(prompt_id)
            if entry is not None:
                status = entry.get("status") or {}
                if status.get("completed") is False or status.get("status_str") == "error":
                    raise EngineError(
                        f"执行失败（prompt {prompt_id}）: {status.get('messages') or status.get('status_str')}"
                    )
                if on_status is not None and last_state != "done":
                    result = on_status("done", {"prompt_id": prompt_id})
                    if result is not None:
                        await result
                return entry

            state = "running" if await self._is_running(prompt_id) else "queued"
            if on_status is not None and state != last_state:
                result = on_status(state, {"prompt_id": prompt_id})
                if result is not None:
                    await result
            last_state = state

            if deadline is not None and time.monotonic() > deadline:
                raise EngineError(f"等待 prompt {prompt_id} 超时（{timeout} 秒）")
            await asyncio.sleep(_POLL_INTERVAL)

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        data = await self._json("GET", f"/history/{prompt_id}")
        if not isinstance(data, dict):
            return None
        entry = data.get(prompt_id)
        return entry if isinstance(entry, dict) else None

    async def queue(self) -> dict[str, Any]:
        data = await self._json("GET", "/queue")
        if not isinstance(data, dict):
            raise EngineError("/queue 返回了意外内容")
        return data

    async def interrupt(self) -> None:
        await self._json("POST", "/interrupt")


def _json_loads(text: str) -> Any:
    import json

    return json.loads(text)


def _short(text: str, limit: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


__all__ = ["HttpEngine"]
