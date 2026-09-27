"""进程内实现：直接操作引擎自己的队列，不绕 HTTP。

作为 custom node 被加载时（也就是我们本来就活在引擎进程里），走这条路：
入队用 ``PromptServer.instance.number`` 自增 + ``prompt_queue.put(...)``，
等完成用 ``prompt_queue.get_history(...)`` 轮询。
"""

from __future__ import annotations

import os
from typing import Any

from ..skills.runner import DEFAULT_TIMEOUT, StatusCallback
from ..skills.runner import submit_prompt as _submit_prompt
from ..skills.runner import wait_for_prompt as _wait_for_prompt
from .base import DEFAULT_BASE_URL, EngineClient, EngineError


def _server():
    try:
        from server import PromptServer  # type: ignore[import-not-found]
    except ImportError as err:  # pragma: no cover
        raise EngineError("不在 ComfyUI 引擎进程内，无法使用 InProcessEngine") from err
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        raise EngineError("PromptServer 尚未初始化")
    return instance


def _default_base_url() -> str:
    """拼一个指向本机的地址，用于生成 /view 图片链接。

    端口取引擎自己记录的 ``self.port``（``ComfyUI/server.py:1446`` 在 start() 里赋值）；
    监听地址是通配符时换成 127.0.0.1，免得生成 0.0.0.0 这种点不开的链接。
    """
    env = os.environ.get("COMFY_URL")
    if env:
        return env.rstrip("/")
    try:
        server = _server()
    except EngineError:
        return DEFAULT_BASE_URL
    port = getattr(server, "port", None)
    if port is None:
        return DEFAULT_BASE_URL
    address = str(getattr(server, "address", "127.0.0.1"))
    if address in {"0.0.0.0", "::", ""}:
        address = "127.0.0.1"
    host = f"[{address}]" if ":" in address else address
    return f"http://{host}:{port}"


class InProcessEngine(EngineClient):
    """跑在引擎进程内时的引擎句柄。"""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or _default_base_url()).rstrip("/")

    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        """取节点定义。

        注意：这里直接返回 ``INPUT_TYPES()`` 的原始结果，没有经过 server.py 里
        ``node_info()`` 的展示字段归一化（name/display_name/category 等）——
        进程内调用方只关心输入定义，不需要那些字段。
        """
        import folder_paths  # type: ignore[import-not-found]
        import nodes  # type: ignore[import-not-found]

        with folder_paths.cache_helper:
            if node_class is not None:
                cls = nodes.NODE_CLASS_MAPPINGS.get(node_class)
                if cls is None:
                    return {}
                return {node_class: cls.INPUT_TYPES()}
            out: dict[str, Any] = {}
            for name, cls in nodes.NODE_CLASS_MAPPINGS.items():
                try:
                    out[name] = cls.INPUT_TYPES()
                except Exception as err:  # 与 server.py 的 /object_info 一样：坏节点不拖垮整份清单
                    out[name] = {"error": f"{type(err).__name__}: {err}"}
            return out

    async def list_model_folders(self) -> list[str]:
        """直接问 ``folder_paths`` 要类别全集，与上游 ``GET /models`` 同一份数据。

        上游那个路由就是 ``list(folder_paths.folder_names_and_paths.keys())``
        （``ComfyUI/server.py`` 的 ``list_model_types``）。第三方节点注册的目录也在这份
        键集里，所以这里不用（也不该）再维护一张白名单。
        """
        import folder_paths  # type: ignore[import-not-found]

        return [str(name) for name in folder_paths.folder_names_and_paths]

    async def list_models(self, folder: str) -> list[str]:
        """按类别直接问 folder_paths 取列表。

        走 HTTP 时是去读节点下拉枚举，这里直接问 folder_paths，两者同源
        （节点的 INPUT_TYPES 也是调 ``folder_paths.get_filename_list``），
        且能正确覆盖 extra_model_paths 里的额外目录。**不再过探测表白名单**：
        类别算不算数由 folder_paths 说了算，第三方注册的目录（例如 F5-TTS 那种）
        因此也列得出来。
        """
        import folder_paths  # type: ignore[import-not-found]

        # 老名字先映射（``folder_paths.map_legacy`` 把 unet/clip 折到
        # diffusion_models/text_encoders），再判类别在不在。
        name = folder_paths.map_legacy(folder)
        if name not in folder_paths.folder_names_and_paths:
            raise EngineError(f"本机没有注册模型类别 {folder}")
        return [str(v) for v in folder_paths.get_filename_list(name)]

    async def submit(self, workflow: dict[str, Any]) -> str:
        return await _submit_prompt(workflow)

    async def wait(
        self, prompt_id: str, timeout: float | None = DEFAULT_TIMEOUT, on_status: StatusCallback | None = None
    ) -> dict[str, Any]:
        return await _wait_for_prompt(prompt_id, timeout=timeout, on_status=on_status)

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        entry = _server().prompt_queue.get_history(prompt_id=prompt_id).get(prompt_id)
        return entry if isinstance(entry, dict) else None

    async def queue(self) -> dict[str, Any]:
        running, pending = _server().prompt_queue.get_current_queue_volatile()
        return {"queue_running": running, "queue_pending": pending}

    async def interrupt(self) -> None:
        import nodes  # type: ignore[import-not-found]

        nodes.interrupt_processing()


__all__ = ["InProcessEngine"]
