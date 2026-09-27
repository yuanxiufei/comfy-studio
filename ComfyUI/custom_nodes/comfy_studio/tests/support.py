"""测试用的替身：一个假引擎句柄 + 一个假模型客户端。

假引擎只实现 :class:`~comfy_studio.engine.base.EngineClient` 的 6 个原语，
``run_skill`` 等上层组合直接用基类的实现 —— 这样这些用例同时在验证基类组合。
"""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable

from ..engine import EngineClient
from ..skills import Skill
from ..skills.runner import DEFAULT_TIMEOUT, StatusCallback
from ..skills.types import SkillParam

#: 一个最小的合法工作流（结构对齐引擎自带节点）。
WORKFLOW: dict[str, dict[str, Any]] = {
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ""}},
    "3": {
        "class_type": "KSampler",
        "inputs": {"seed": 0, "steps": 20, "model": ["4", 0]},
    },
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "t", "images": ["3", 0]}},
}


def make_skill(
    skill_id: str = "demo",
    params: tuple[SkillParam, ...] = (),
    workflow: dict[str, dict[str, Any]] | None = None,
) -> Skill:
    """内存里拼一个 skill，绕开 JSON 加载。"""
    return Skill(
        id=skill_id,
        title=f"{skill_id} 标题",
        description=f"{skill_id} 说明",
        workflow=workflow if workflow is not None else {k: dict(v) for k, v in WORKFLOW.items()},
        params=params,
        tags=("test",),
        source="<测试>",
    )


class FakeEngine(EngineClient):
    """把每次调用都记下来，并回一份可预测的结果。"""

    def __init__(self, base_url: str = "http://engine.test") -> None:
        self.base_url = base_url
        self.submitted: list[dict[str, Any]] = []
        #: 每次 wait 的入参（用来验证 timeout / 回调有没有被透传下去）。
        self.waits: list[dict[str, Any]] = []
        self.histories: dict[str, dict[str, Any]] = {}
        self.queue_snapshot: dict[str, Any] = {"queue_running": [], "queue_pending": []}
        self.interrupts = 0
        self.object_info_map: dict[str, Any] = {}
        #: ``list_model_folders`` 的回话；None = 不覆写，走基类默认（探测表的键）。
        self.model_folders: list[str] | None = None
        #: wait 期间要推的状态序列（默认跑一遍 running → done）。
        self.wait_states: tuple[str, ...] = ("running", "done")

    async def list_model_folders(self) -> list[str]:
        if self.model_folders is None:
            return await super().list_model_folders()
        return list(self.model_folders)

    async def object_info(self, node_class: str | None = None) -> dict[str, Any]:
        if node_class is None:
            return dict(self.object_info_map)
        value = self.object_info_map.get(node_class)
        return {} if value is None else {node_class: value}

    async def submit(self, workflow: dict[str, Any]) -> str:
        self.submitted.append(workflow)
        return f"prompt-{len(self.submitted)}"

    async def wait(
        self,
        prompt_id: str,
        timeout: float | None = DEFAULT_TIMEOUT,
        on_status: StatusCallback | None = None,
    ) -> dict[str, Any]:
        self.waits.append({"prompt_id": prompt_id, "timeout": timeout, "has_status": on_status is not None})
        if on_status is not None:
            for state in self.wait_states:
                result = on_status(state, {"prompt_id": prompt_id})
                if inspect.isawaitable(result):
                    await result
        entry = self.histories.get(prompt_id)
        if entry is None:
            entry = {
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": f"{prompt_id}.png", "subfolder": "", "type": "output"}
                        ]
                    }
                },
                "status": {"completed": True, "status_str": "success"},
            }
        return entry

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        return self.histories.get(prompt_id)

    async def queue(self) -> dict[str, Any]:
        return self.queue_snapshot

    async def interrupt(self) -> None:
        self.interrupts += 1


class FakeLLM:
    """按脚本逐轮回话的模型客户端（``complete`` 被调用几次就取第几条）。"""

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.calls: list[list[Any]] = []
        self.closed = False

    async def complete(self, messages: list[Any], tools: list[dict[str, Any]] | None = None) -> Any:
        self.calls.append(list(messages))
        if not self.replies:
            raise AssertionError("假模型被问的次数超出了脚本里准备的回话")
        return self.replies.pop(0)

    async def close(self) -> None:
        self.closed = True


def record_events(sink: list[str]) -> Callable[[Any], Awaitable[None]]:
    """返回一个可 await 的事件监听器，把事件类型按顺序记下来。"""

    async def listener(event: Any) -> None:
        sink.append(event.type)

    return listener
