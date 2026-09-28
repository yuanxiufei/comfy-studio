"""引擎客户端的公共接口。

同一个 MCP server / agent 既可能跑在引擎进程里（作为 custom node 被加载），
也可能被外部进程拉起来（Claude / Cursor 直接 spawn 一个 stdio server）。
所以把「对引擎的操作」抽象成一组原语，由两种实现各自补齐：

* :mod:`comfy_studio.engine.inprocess` —— 进程内直连 PromptServer 的队列；
* :mod:`comfy_studio.engine.http` —— 对着 ``COMFY_URL`` 说 HTTP。

与 skill 有关的上层组合（注入参数、等完成、收图片）只写一遍，放在本模块。
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from ..skills import Skill, SkillRunResult, build_prompt, collect_media
from ..skills.runner import DEFAULT_TIMEOUT, StatusCallback, cancel_quietly


class EngineError(RuntimeError):
    """引擎侧的错误（校验失败、执行失败、连不上等）。"""


#: **老引擎的回退探测表**：每类模型用哪个节点的枚举字段去问。
#: 字段名核实自引擎自带节点：CheckpointLoaderSimple.ckpt_name、VAELoader.vae_name、
#: LoraLoader.lora_name、CLIPLoader.clip_name、UNETLoader.unet_name、
#: ControlNetLoader.control_net_name、UpscaleModelLoader.model_name。
#:
#: 新引擎（带了 ``GET /models`` 与 ``GET /models/{folder}`` 两个路由的版本，见
#: ``ComfyUI/server.py`` 的 ``list_model_types`` / ``get_models``）不再需要它：类别全集
#: 直接问 ``folder_paths.folder_names_and_paths``，第三方自定义节点注册的目录
#: （例如 F5-TTS 那种）也在里面。这张表只在老引擎上兜底 —— 它只能覆盖引擎自带的
#: 那几类，而且要求对应节点已注册，节点没装时会误报"没有这类模型"。
MODEL_PROBES: dict[str, tuple[str, str]] = {
    "checkpoints": ("CheckpointLoaderSimple", "ckpt_name"),
    "vae": ("VAELoader", "vae_name"),
    "loras": ("LoraLoader", "lora_name"),
    "text_encoders": ("CLIPLoader", "clip_name"),
    "diffusion_models": ("UNETLoader", "unet_name"),
    "controlnet": ("ControlNetLoader", "control_net_name"),
    "upscale_models": ("UpscaleModelLoader", "model_name"),
}


#: 引擎的默认地址：走 HTTP 且没给 ``COMFY_URL`` 时用它。
#: 进程内那条路只在拿不到 ``PromptServer.port`` 时才回退到它（``engine/inprocess.py``）。
DEFAULT_BASE_URL = "http://127.0.0.1:8188"


class EngineClient(ABC):
    """对引擎的最小操作集。子类只需实现这 7 个原语。"""

    #: 引擎的对外地址，用于拼 /view 图片链接。
    base_url: str = DEFAULT_BASE_URL

    @abstractmethod
    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        """取 /object_info（可只取单个节点）。"""

    @abstractmethod
    async def submit(self, workflow: dict[str, Any]) -> str:
        """提交 API 格式工作流，返回 prompt_id（不等待）。"""

    @abstractmethod
    async def wait(
        self, prompt_id: str, timeout: float | None = DEFAULT_TIMEOUT, on_status: StatusCallback | None = None
    ) -> dict[str, Any]:
        """等该 prompt 结束，返回 history 条目。"""

    @abstractmethod
    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        """查某个 prompt 的 history 条目，没有就返回 None。"""

    @abstractmethod
    async def queue(self) -> dict[str, Any]:
        """取队列快照 {"queue_running": [...], "queue_pending": [...]}。"""

    @abstractmethod
    async def interrupt(self) -> None:
        """中断当前执行。"""

    @abstractmethod
    async def cancel_prompt(self, prompt_id: str) -> bool:
        """把**指定**的那个 prompt 从引擎队列里撤下来：在跑就中断，在排队就出队。

        返回是否真的撤到了东西：已经跑完或根本不认识的 id 回 ``False``，不算错。

        与 :meth:`interrupt` 的区别是「精确到 id」：``interrupt`` 是不管三七二十一停掉
        当前正在跑的那个（可能压根不是你要撤的），取消一个 skill 必须走这个原语，
        否则会误伤队列里别人的活。
        """

    async def list_model_folders(self) -> list[str]:
        """本机**已注册的模型类别全集**（ComfyUI ``folder_paths`` 的那些键）。

        默认只回退到探测表的键：老引擎没有 ``GET /models`` 这个路由，问不到全集。
        带该路由的新引擎由子类覆写成真正的全集 —— 除引擎自带类别外，还包括第三方
        自定义节点自己注册的目录（它们走 ``folder_paths.add_model_folder_path``）。
        """
        return list(MODEL_PROBES)

    async def list_models(self, folder: str) -> list[str]:
        """按类别列出可用模型文件名（**老引擎回退路径**）。

        做法与前端一致：读对应节点输入上的下拉枚举值，而不是自己去翻 models 目录，
        这样多出来的 extra_model_paths 配置也能被算进去。覆盖范围只有探测表那几类，
        新引擎由子类覆写成直接按类别问 ``folder_paths``（第三方目录也能列）。
        """
        probe = MODEL_PROBES.get(folder)
        if probe is None:
            raise EngineError(f"未知 folder: {folder}；可选: {', '.join(MODEL_PROBES)}")
        node_class, field = probe
        info = await self.object_info(node_class)
        node = info.get(node_class)
        if node is None:
            raise EngineError(f"节点 {node_class} 不存在（相关模型类型未安装？）")
        required = (node.get("input") or {}).get("required") or {}
        entry = required.get(field)
        values = entry[0] if isinstance(entry, (list, tuple)) and entry else None
        if not isinstance(values, list):
            raise EngineError(f"无法从 {node_class}.{field} 读取模型列表")
        return [str(v) for v in values]

    async def run_skill(
        self,
        skill: Skill,
        params: dict[str, Any] | None = None,
        on_status: StatusCallback | None = None,
        timeout: float | None = DEFAULT_TIMEOUT,
    ) -> SkillRunResult:
        """注入参数 → 提交 → 等完成 → 收图片。"""
        prompt = build_prompt(skill, params)
        prompt_id = await self.submit(prompt)
        if on_status is not None:
            result = on_status("queued", {"prompt_id": prompt_id})
            if result is not None:
                await result
        try:
            entry = await self.wait(prompt_id, timeout=timeout, on_status=on_status)
        except asyncio.CancelledError:
            # 光停下"等结果"这一侧不够：活已经进引擎队列了（HTTP 那条路尤其看不见它），
            # 不撤下来的话它照样占着 GPU 跑完 —— 按了停止的人以为它停了。
            await cancel_quietly(prompt_id, self.cancel_prompt)
            raise
        return SkillRunResult(
            prompt_id=prompt_id,
            media=collect_media(entry),
            outputs=entry.get("outputs") or {},
        )


__all__ = ["DEFAULT_BASE_URL", "EngineClient", "EngineError", "MODEL_PROBES"]
