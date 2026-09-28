"""skill 的执行：注入参数 → 入引擎队列 → 等执行结束 → 收集产物（见 outputs.py）。

走的是引擎**进程内**的队列（``server.PromptServer.instance.prompt_queue``），
不是对着本机端口发 HTTP；因此本模块只能在引擎进程里使用。
入队参数的形状照抄上游 POST /prompt 的写法（``ComfyUI/server.py:1075-1136``）：
``number`` 取 ``PromptServer.number`` 自增，prompt 先过
``execution.validate_prompt``，``outputs_to_execute`` 取校验结果的第 3 项。
"""

from __future__ import annotations

import asyncio
import copy
import random
import sys
import time
import uuid
from typing import Any, Awaitable, Callable

from .outputs import collect_media
from .params import SEED_RANDOM, merge_params
from .types import PromptWorkflow, Skill, SkillRunResult

# 状态回调：state ∈ {"queued", "running", "done"}，data 里带 prompt_id 等细节。
StatusCallback = Callable[[str, dict[str, Any]], "Awaitable[None] | None"]

# 撤下一个已提交的 prompt；回是否真的撤到了（详见 cancel_prompt）。
CancelFn = Callable[[str], Awaitable[bool]]

# 名为 seed 的参数传 -1 表示每次随机；KSampler 的 seed 上限是 0xffffffffffffffff，
# 这里取 48 位随机，避免超出 JSON 安全整数范围（对齐 TS 版 runner.ts）。
_SEED_RANGE = 0x1_0000_0000_0000

#: 等一次执行结束的默认上限（秒）。设为 None 表示不设上限。
DEFAULT_TIMEOUT = 1800.0

#: 轮询历史/队列的间隔（秒）。进程内（本模块）与 HTTP（``engine/http.py``）两条等待路径
#: 共用同一个节奏，别再各写一份。
POLL_INTERVAL = 0.5


class SkillExecutionError(RuntimeError):
    """执行失败。node_errors 保留引擎给出的逐节点错误，便于直接回给调用方。"""

    def __init__(self, message: str, node_errors: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.node_errors: dict[str, Any] = node_errors or {}


def _server():
    """拿到运行中的 PromptServer；不在引擎进程里就直接报错。"""
    try:
        from server import PromptServer  # type: ignore[import-not-found]
    except ImportError as err:  # pragma: no cover - 只有脱离引擎时才会走到
        raise RuntimeError(
            "comfy_studio.skills.runner 需要在 ComfyUI 引擎进程内运行（找不到 server 模块）"
        ) from err
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        raise RuntimeError("PromptServer 尚未初始化，无法提交 prompt")
    return instance


def build_prompt(skill: Skill, params: dict[str, Any] | None) -> PromptWorkflow:
    """合并参数并注入工作流（深拷贝，不改动 skill 自带的模板）。"""
    merged = merge_params(skill, params)
    prompt = copy.deepcopy(skill.workflow)
    for param in skill.params:
        if param.name not in merged:
            continue
        value = merged[param.name]
        if param.name == "seed" and value == SEED_RANDOM:
            value = random.randrange(_SEED_RANGE)
        prompt[param.node]["inputs"][param.field] = value
    return prompt


async def submit_prompt(prompt: PromptWorkflow) -> str:
    """校验并入队，返回 prompt_id（不等待执行）。"""
    import execution  # type: ignore[import-not-found]

    server = _server()
    prompt_id = str(uuid.uuid4())
    valid = await execution.validate_prompt(prompt_id, prompt, None)
    if not valid[0]:
        error = valid[1] or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise SkillExecutionError(f"工作流校验失败: {message}", valid[3])

    extra_data: dict[str, Any] = {"create_time": int(time.time() * 1000)}
    sensitive: dict[str, Any] = {}
    for key in execution.SENSITIVE_EXTRA_DATA_KEYS:
        if key in extra_data:
            sensitive[key] = extra_data.pop(key)

    number = server.number
    server.number += 1
    server.prompt_queue.put((number, prompt_id, prompt, extra_data, valid[2], sensitive))
    return prompt_id


def _is_running(prompt_id: str) -> bool:
    running, _queued = _server().prompt_queue.get_current_queue_volatile()
    return any(item[1] == prompt_id for item in running)


async def wait_for_prompt(
    prompt_id: str,
    timeout: float | None = DEFAULT_TIMEOUT,
    on_status: StatusCallback | None = None,
) -> dict[str, Any]:
    """等到该 prompt 出现在 history 里，返回它的 history 条目。"""
    queue = _server().prompt_queue
    deadline = None if timeout is None else time.monotonic() + timeout
    last_state = ""

    while True:
        entry = queue.get_history(prompt_id=prompt_id).get(prompt_id)
        if entry is not None:
            status = entry.get("status") or {}
            if status.get("completed") is False or status.get("status_str") == "error":
                raise SkillExecutionError(
                    f"执行失败（prompt {prompt_id}）: {status.get('messages') or status.get('status_str')}"
                )
            if on_status is not None and last_state != "done":
                await _emit(on_status, "done", {"prompt_id": prompt_id})
            return entry

        state = "running" if _is_running(prompt_id) else "queued"
        if on_status is not None and state != last_state:
            await _emit(on_status, state, {"prompt_id": prompt_id})
        last_state = state

        if deadline is not None and time.monotonic() > deadline:
            raise SkillExecutionError(
                f"等待 prompt {prompt_id} 超时（{timeout} 秒）；可用 interrupt 工具中断，"
                "或查看 /queue 判断它是否还排在队列里"
            )
        await asyncio.sleep(POLL_INTERVAL)


async def _emit(callback: StatusCallback, state: str, data: dict[str, Any]) -> None:
    result = callback(state, data)
    if result is not None:
        await result


async def cancel_prompt(prompt_id: str) -> bool:
    """把已提交的 prompt 从引擎队列里撤下来：还在排队就出队，已经在跑就中断它。

    判据与动作都交给上游 ``comfy_execution/jobs.py`` 的 ``cancel_job``，这里不另写一份。
    它把两件很容易写错的事办好了：中断必须走 ``PromptQueue.interrupt_if_running``
    （``ComfyUI/execution.py``，带 mutex 的原子判断，否则取消可能落到快照之后刚起来的
    **另一个** prompt 上），而 pending→running 的竞态按"实际做没做到"回话，不硬说撤到了。
    参数形状对齐引擎自己的取消路由（``ComfyUI/server.py`` 的 ``cancel_job_by_id``）：
    ``history`` 要传全量，因为 ``classify_job_for_cancel`` 用的是 ``prompt_id in history``。

    返回是否真的撤到了东西，语义与 ``POST /api/jobs/{job_id}/cancel`` 的 ``cancelled``
    一致：已经跑完或根本不认识的 id 回 ``False``，不算错。
    """
    try:
        from comfy_execution.jobs import (  # type: ignore[import-not-found]
            CANCEL_PENDING,
            CANCEL_RUNNING,
            cancel_job,
        )
    except ImportError as err:  # pragma: no cover - 只有很老的引擎才缺这个模块
        raise SkillExecutionError(
            "本引擎没有 comfy_execution.jobs（老版本 ComfyUI），无法撤销已提交的 prompt"
        ) from err

    queue = _server().prompt_queue
    running, queued = queue.get_current_queue()
    result = cancel_job(
        prompt_id,
        running,
        queued,
        queue.get_history(),
        queue.interrupt_if_running,
        lambda item_id: queue.delete_queue_item(lambda item: item[1] == item_id),
    )
    return result in (CANCEL_RUNNING, CANCEL_PENDING)


async def cancel_quietly(prompt_id: str, cancel: CancelFn | None = None) -> None:
    """取消路径上的撤队列：失败只记一行 stderr，绝不改变"已取消"这个结论。

    按下停止是调用方的意图，撤队列只是顺手把已经没人要的活从引擎队列里清掉。清理失败
    （引擎连不上、太老、队列不接受）不该把 ``CancelledError`` 换成别的异常 —— 那会让宿主
    看到"引擎坏了"而不是"已停止"，而取消本身早就生效了。
    """
    cancel = cancel or cancel_prompt
    try:
        await cancel(prompt_id)
    except Exception as err:  # CancelledError 是 BaseException，不受这里影响，继续往外传
        print(
            f"[skills] 撤销 prompt {prompt_id} 没成功（已忽略，取消照常生效）: "
            f"{type(err).__name__}: {err}",
            file=sys.stderr,
            flush=True,
        )


async def run_skill(
    skill: Skill,
    params: dict[str, Any] | None = None,
    on_status: StatusCallback | None = None,
    timeout: float | None = DEFAULT_TIMEOUT,
) -> SkillRunResult:
    """跑一个 skill 并等到结束。"""
    prompt = build_prompt(skill, params)
    prompt_id = await submit_prompt(prompt)
    if on_status is not None:
        await _emit(on_status, "queued", {"prompt_id": prompt_id})
    try:
        entry = await wait_for_prompt(prompt_id, timeout=timeout, on_status=on_status)
    except asyncio.CancelledError:
        # 光停下"等结果"这一侧不够：活已经在引擎队列里了，不撤下来的话它照样占着 GPU
        # 跑完 —— 按了停止的人以为它停了。
        await cancel_quietly(prompt_id)
        raise
    return SkillRunResult(
        prompt_id=prompt_id,
        media=collect_media(entry),
        outputs=entry.get("outputs") or {},
    )


__all__ = [
    "DEFAULT_TIMEOUT",
    "POLL_INTERVAL",
    "SEED_RANDOM",
    "SkillExecutionError",
    "build_prompt",
    "cancel_prompt",
    "cancel_quietly",
    "run_skill",
    "submit_prompt",
    "wait_for_prompt",
]
