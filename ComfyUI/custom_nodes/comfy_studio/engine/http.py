"""进程外实现：对着本机引擎说 HTTP。

MCP server 被 Claude / Cursor 之类的宿主 spawn 出来时走这条路；用到的接口都是
上游既有路由（``ComfyUI/server.py``）：``/object_info``、``/prompt``、``/history``、
``/queue``、``/interrupt``，列模型清单用的 ``/models``、``/models/{folder}``，以及
撤下某个已提交 prompt 的 ``/api/jobs/{job_id}/cancel``。

前缀：上游会把每条路由再复制一份加 ``/api``（``ComfyUI/server.py`` 的 ``add_routes``
里那句 ``"/api" + route.path``），所以注册成 ``/prompt`` 的既能用 ``/prompt`` 也能用
``/api/prompt``，这里一律用不带前缀的短路径。**只有 ``/api/jobs/...`` 是例外**：它注册
时就带着 ``/api``，复制出来的那份是 ``/api/api/...``，反倒没有不带前缀的形式 —— 那一条
必须按原样拼（见 :meth:`HttpEngine.cancel_prompt`）。

后三条都是后加的路由，老引擎上没有 —— 见 :meth:`HttpEngine.list_model_folders`、
:meth:`HttpEngine.list_models` 的退路与 :meth:`HttpEngine.cancel_prompt` 的报错。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import aiohttp

from ..skills.runner import DEFAULT_TIMEOUT, POLL_INTERVAL, StatusCallback
from .base import DEFAULT_BASE_URL, EngineClient, EngineError

#: 老类别名 → 现用名。同一份表在引擎侧（``ComfyUI/folder_paths.py`` 的 ``map_legacy``）。
#: 抄在这里是因为走 HTTP 的实现拿不到 ``folder_paths``：那个模块只在引擎进程里 import 得到，
#: 而 HttpEngine 恰恰是"没活在引擎进程里"时才用的。
FOLDER_NAME_ALIASES: dict[str, str] = {"unet": "diffusion_models", "clip": "text_encoders"}

#: 撤下一个已提交的 prompt 时等引擎回话的上限（秒）。
#: 比常规请求（``request_timeout``，默认 60 秒）短得多：这条路走在"用户刚按下停止"上，
#: 引擎要是没反应，宁可快点放弃，也不能让一次取消干等一分钟。
CANCEL_TIMEOUT = 10.0


class HttpEngine(EngineClient):
    """通过 HTTP 访问一个已经在跑的 ComfyUI。"""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, request_timeout: float = 60.0) -> None:
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

    async def _get_json_soft(self, path: str) -> tuple[int, Any]:
        """GET 一个 JSON 路由，**把状态码原样交回调用方**。

        与 :meth:`_json` 的区别只有一个：``_json`` 把 4xx/5xx 直接当错误抛掉，而模型列表
        这边要拿状态码去分辨"类别没注册"和"这个引擎还没有 ``/models`` 路由"（两者都是
        404），所以单独走一条。网络层故障照旧抛 :class:`EngineError`。
        """
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        try:
            async with session.get(url) as resp:
                status = resp.status
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise EngineError(f"连不上引擎 {url}: {err}") from err
        if not text:
            return status, None
        try:
            return status, _json_loads(text)
        except ValueError as err:
            # 4xx/5xx 的正文不一定是 JSON：引擎没这条路由时是 aiohttp 那段 "404: Not Found"
            # 文本，而"这个类别没注册"恰恰是靠 404 认出来的 —— 所以错误状态码一律原样交回，
            # 正文带着给人看（调用方只会截一小段塞进错误信息），只有 2xx 的非 JSON 才是异常。
            if status >= 400:
                return status, text
            raise EngineError(f"GET {path} 返回的不是 JSON: {err}") from err

    async def _model_folders_if_supported(self) -> list[str] | None:
        """引擎带 ``/models`` 就回类别全集；比它老（404）就回 ``None``。"""
        status, data = await self._get_json_soft("/models")
        if status == 404:
            return None
        if status >= 400:
            raise EngineError(f"GET /models 返回 {status}: {_short(str(data))}")
        if not isinstance(data, list) or not all(isinstance(name, str) and name for name in data):
            raise EngineError(f"/models 返回了意外内容: {str(data)[:200]}")
        return list(data)

    async def list_model_folders(self) -> list[str]:
        """问引擎的 ``GET /models`` 要类别全集。

        上游那个路由（``ComfyUI/server.py`` 的 ``list_model_types``）直接回
        ``folder_paths.folder_names_and_paths`` 的键，所以第三方自定义节点注册的目录
        （例如 F5-TTS 那种）也在清单里。老引擎没有这个路由，退回探测表的键 ——
        那种机器上只能查引擎自带的那几类。
        """
        folders = await self._model_folders_if_supported()
        if folders is None:
            return await super().list_model_folders()
        return folders

    async def list_models(self, folder: str) -> list[str]:
        """按类别问引擎的 ``GET /models/{folder}``。

        该路由（``ComfyUI/server.py`` 的 ``get_models``）对没注册的类别回 404，于是 404
        有两种含义，得靠 ``/models`` 在不在来分辨：在 = 类别确实没注册，显式报错；不在 =
        这个引擎比 ``/models`` 还老，退回探测法（读节点下拉枚举）。

        另外上游那个路由**不认老名字**（它直接拿类别名查 ``folder_names_and_paths``，不做
        :func:`folder_paths.map_legacy`），而 ``folder_paths.get_filename_list`` 认 ——
        进程内那条路因此列得出 ``unet``，走 HTTP 却会被回 404。为免同一台机器两条路答得
        不一样，404 时拿 :data:`FOLDER_NAME_ALIASES` 里的新名字再问一次。
        """
        alias = FOLDER_NAME_ALIASES.get(folder)
        files = await self._files_if_registered(folder)
        if files is None and alias is not None:
            files = await self._files_if_registered(alias)
        if files is not None:
            return files

        folders = await self._model_folders_if_supported()
        if folders is None:
            return await super().list_models(folder)
        available = ", ".join(folders) or "（无）"
        if alias is None:
            raise EngineError(f"本机没有注册模型类别 {folder}；可用: {available}")
        raise EngineError(f"本机没有注册模型类别 {folder}（老名字 {alias} 也没有）；可用: {available}")

    async def _files_if_registered(self, folder: str) -> list[str] | None:
        """问 ``/models/{folder}``；类别没注册（404）就回 ``None``，其余异常照抛。"""
        path = f"/models/{quote(folder, safe='')}"
        status, data = await self._get_json_soft(path)
        if status == 200:
            if not isinstance(data, list) or not all(isinstance(name, str) for name in data):
                raise EngineError(f"GET {path} 返回了意外内容: {str(data)[:200]}")
            return list(data)
        if status != 404:
            raise EngineError(f"GET {path} 返回 {status}: {_short(str(data))}")
        return None  # 404 = 这个类别名没注册（也可能这台引擎整条路由都没有，由调用方分辨）

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
            await asyncio.sleep(POLL_INTERVAL)

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

    async def cancel_prompt(self, prompt_id: str) -> bool:
        """按 id 撤下已提交的 prompt：上游 ``POST /api/jobs/{job_id}/cancel``。

        这条路由（``ComfyUI/server.py`` 的 ``cancel_job_by_id``）是状态无关且幂等的：在跑就
        中断、在排队就出队、已经结束或根本不认识都回 ``{"cancelled": false}`` 而不是报错
        （形状核实自 ``ComfyUI/server.py`` 里那个 ``cancel_job_by_id`` 的返回值）。

        分类与动作都在引擎里做（``comfy_execution/jobs.py`` 的 ``cancel_job``），这一侧只把
        id 送过去、把布尔值取回来 —— 不自己在本地查 ``/queue`` 判断该删还是该中断：那会多出
        一份判据，还会丢掉引擎侧的原子性（中断必须和"当前跑的正是这个 id"一起判断，否则
        可能中断到快照之后刚起来的另一个 prompt）。

        404 是**另一种**意思：这台引擎没有这条路由（比它老）；不能当成"没撤到"糊过去，
        否则用户看到的"已停止"底下，那一步生成其实还在跑。超时也单独设短（见
        :data:`CANCEL_TIMEOUT`）。
        """
        session = await self._get_session()
        url = f"{self.base_url}/api/jobs/{quote(prompt_id, safe='')}/cancel"
        try:
            async with session.post(url, timeout=aiohttp.ClientTimeout(total=CANCEL_TIMEOUT)) as resp:
                status = resp.status
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise EngineError(f"连不上引擎 {url}: {err}") from err

        if status == 404:
            raise EngineError(
                "这台引擎没有 /api/jobs/{job_id}/cancel 路由（老版本 ComfyUI），"
                f"已提交的 prompt {prompt_id} 撤不下来"
            )
        if status >= 400:
            raise EngineError(f"POST /api/jobs/{prompt_id}/cancel 返回 {status}: {_short(text)}")
        data = _json_loads(text) if text else None
        cancelled = data.get("cancelled") if isinstance(data, dict) else None
        if not isinstance(cancelled, bool):
            raise EngineError(f"撤销 prompt {prompt_id} 返回了意外内容: {_short(text)}")
        return cancelled


def _json_loads(text: str) -> Any:
    import json

    return json.loads(text)


def _short(text: str, limit: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


__all__ = ["HttpEngine"]
