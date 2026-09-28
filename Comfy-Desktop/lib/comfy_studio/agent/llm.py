"""模型侧：一个极薄的 OpenAI 兼容 chat completions 客户端。

配置全部来自环境变量，免密钥进仓库：

* ``COMFY_STUDIO_LLM_MODEL`` —— **必填**，没有就直接报错，不猜默认模型；
* ``COMFY_STUDIO_LLM_BASE_URL``（回退 ``OPENAI_BASE_URL``，再回退官方地址）；
* ``COMFY_STUDIO_LLM_API_KEY``（回退 ``OPENAI_API_KEY``；本地服务通常不需要）；
* ``COMFY_STUDIO_LLM_MAX_TOKENS`` —— 可选。单次回答的 token 上限；不设就不往请求里带，
  由服务端的默认值说了算。

环境变量给的是**默认**模型；面板里的模型切换是在这之上换一个（见
:meth:`OpenAIChatClient.list_models`：可选清单直接问服务端的
``GET {base_url}/models``，本地 Ollama / LM Studio / vLLM 都实现了这个口）。

请求失败会**按策略重试**（常量见下）：传输层错误、超时、限流、服务端 5xx、以及
"200 但回答是空的"都会重试；认证与参数错误**不重试**，因为再试也不会变好。
唯一夹在中间的一类是"回环地址上连接被拒绝"：它看着像传输层错误，实际是确定性结论，
归到不重试那一边（判据与实测见 :func:`_is_local_refusal`）。
重试过程通过 ``on_retry`` 往外报，面板可以据此显示"正在重试第 N 次"。

用 aiohttp 而不是 ``urllib``：引擎 venv 里本来就有 aiohttp（ComfyUI 的依赖），
不额外引入新包。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

import aiohttp

from ..cancel import CancelToken, race
from .types import ChatMessage, ToolCall

#: 一次请求最多试几次（含第一次）。
DEFAULT_MAX_ATTEMPTS = 5
#: 退避：0.5s 起、每次翻倍、封顶 10s。
RETRY_BASE_DELAY = 0.5
RETRY_MAX_DELAY = 10.0
#: 抖动比例：多个会话同时重试时错开，免得齐步走再把人打一遍。
RETRY_JITTER_RATIO = 0.1

#: 可重试的 HTTP 状态码。**认证与参数类错误（400/401/403/404）故意不在里面**：
#: 那些再试也不会变好，只会让面板白等一轮。
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: 回环地址：这几个 host 上"连接被拒绝"是**确定性结论** —— 端口后面没人监听。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_local_refusal(url: str, err: BaseException) -> bool:
    """这次失败是不是"本机端口没人监听"。

    两个条件**同时**成立才算：底层判成 :class:`ConnectionRefusedError`，且地址落在回环上。

    为什么单拎出来：本地服务的启动顺序是"先监听、再加载模型"（Ollama、LM Studio 都如此），
    所以回环地址上被拒 = 服务根本没起来，**不是**瞬时抖动 —— 重试 5 次只会拿到 5 个同样的
    答案。2026-09-28 实测（Windows + A5000）：本机拒绝**一次固定要 2.0 秒**，
    ``socket.create_connection("127.0.0.1", 1)`` 用 2.031s、aiohttp 用 2.032s —— 那 2 秒
    是 Winsock 给的，不是我们的超时，改不了它的速度；于是 5 次尝试 10s 再加 7.9s 退避，
    一轮白等 18.4s，换来的还是同一句"连不上"。所以这一类的正确做法是**立刻报错**。

    判据按 ``os_error`` 的**类型**走，不碰 ``errno``：实测那个
    ``ConnectionRefusedError`` 的 ``errno`` 是 **22**，不是 ECONNREFUSED 的 61/111，
    拿 errno 去比会永远不成立 —— 而且不会报错，只是白等，最难发现的那种。
    """
    if not isinstance(getattr(err, "os_error", None), ConnectionRefusedError):
        return False
    return (urlsplit(url).hostname or "").lower() in _LOOPBACK_HOSTS


#: ``on_retry(第几次失败, 总共几次, 等多久, 失败原因)``；返回 awaitable 就会被 await。
RetryListener = Callable[[int, int, float, str], "Awaitable[None] | None"]

#: 单次尝试耗时低于这个秒数就不写成功日志：秒回的那些没卡，全记下来只是刷屏。
#: **失败不受**这个门槛限制——重试链路上每一次失败都是排查要用的骨架。
ATTEMPT_LOG_THRESHOLD = 1.0


def usage_counts(usage: Any) -> tuple[int, int] | None:
    """从响应里取出 ``(prompt_tokens, completion_tokens)``，认不出来时返回 ``None``。

    服务端不给 ``usage``、或给的形状不是这两个整数时返回 ``None``：这个数字只用来写
    诊断日志，**不猜**——编一个出来只会让人把假数据当结论。
    """
    if not isinstance(usage, Mapping):
        return None
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    return prompt, completion


def _report_attempt(
    attempt: int,
    total: int,
    elapsed: float,
    *,
    counts: tuple[int, int] | None = None,
    error: str | None = None,
    wait: float | None = None,
) -> None:
    """记一行"这一次尝试"的账：耗时，加上 token 数（成功）或还要等多久（失败）。

    与 ``agent/loop.py`` 那行**分工不同，别混着看**：那边记的是"这一轮的第 N 次模型调用"
    （一次调用可能含下面这串重试，看到的是合计），这边记的是每次**尝试**。真发生重试时，
    各次尝试耗时相加、再加上每次的等待，才是那一轮耗时的完整去向。
    """
    if error is None:
        detail = "服务端没给 usage" if counts is None else f"prompt {counts[0]} tok / 生成 {counts[1]} tok"
        print(
            f"[llm] 第 {attempt} 次尝试成功：{elapsed:.1f}s（{detail}）",
            file=sys.stderr,
            flush=True,
        )
        return
    tail = "不再重试" if wait is None else f"等 {wait:.1f}s 再试"
    print(
        f"[llm] 第 {attempt} 次尝试失败：{elapsed:.1f}s（{error}），{tail}（共 {total} 次）",
        file=sys.stderr,
        flush=True,
    )


class LLMError(RuntimeError):
    """模型侧的错误（配置缺失、连不上、返回结构不符预期）。

    ``retryable`` 说"再试一次有没有意义"，``retry_after`` 是服务端在 ``Retry-After``
    头里要求的等待秒数（有就优先于我们自己的退避）。
    """

    def __init__(self, message: str, *, retryable: bool = False, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str | None = None
    temperature: float = 0.7
    timeout: float = 180.0
    #: 单次回答最多生成多少 token；``None`` = 不往请求里带，由服务端的默认值说了算。
    #:
    #: 它挡的是"本地模型收不住、一段话生成十几分钟"那种体感：请求是**非流式**的
    #: （见 :meth:`OpenAIChatClient._complete_once`），整段生成完才有第一个字节回来，
    #: 输出没有上限时这一等就没有头。
    max_tokens: int | None = None

    @classmethod
    def from_env(cls) -> "LLMConfig":
        model = os.environ.get("COMFY_STUDIO_LLM_MODEL", "").strip()
        if not model:
            raise LLMError(
                "没有配置模型：请设置 COMFY_STUDIO_LLM_MODEL（例如 qwen2.5:7b 或 gpt-4o-mini）。"
                "地址与密钥分别用 COMFY_STUDIO_LLM_BASE_URL / COMFY_STUDIO_LLM_API_KEY 覆盖。"
            )
        return cls(
            base_url=os.environ.get(
                "COMFY_STUDIO_LLM_BASE_URL", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            ).rstrip("/"),
            model=model,
            api_key=os.environ.get("COMFY_STUDIO_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or None,
            max_tokens=_max_tokens_from_env(),
        )


def _max_tokens_from_env() -> int | None:
    """读 ``COMFY_STUDIO_LLM_MAX_TOKENS``：没设就是不限。

    填了个不像正整数的值就**当场报错**，不悄悄忽略：配置写错了却照常跑起来，
    用户只会以为"这个开关没用"（口径同 :mod:`comfy_studio.memory` 与模型配置文件）。
    """
    raw = os.environ.get("COMFY_STUDIO_LLM_MAX_TOKENS", "").strip()
    if raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        raise LLMError(f"COMFY_STUDIO_LLM_MAX_TOKENS 必须是正整数，给的是 {raw!r}") from None
    if value <= 0:
        raise LLMError(f"COMFY_STUDIO_LLM_MAX_TOKENS 必须是正整数，给的是 {raw!r}")
    return value


class OpenAIChatClient:
    """只做一件事：发一轮 messages，拿回一条 assistant 消息。"""

    def __init__(self, config: LLMConfig, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> None:
        self.config = config
        self.max_attempts = max_attempts
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.timeout)
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> float | None:
        """读 ``Retry-After``（秒数形状）。HTTP-date 形状不猜，用我们自己的退避。"""
        raw = headers.get("Retry-After")
        if raw is None:
            return None
        try:
            seconds = float(raw)
        except ValueError:
            return None
        return seconds if seconds > 0 else None

    async def _get_text(self, method: str, url: str, **kwargs: Any) -> tuple[int, str, float | None]:
        """发一次请求并拿回 ``(状态码, 原文, Retry-After)``。

        连不上与超时都标成**可重试**：这两类是瞬时故障。参数、认证问题由调用方按
        状态码判断，不在这里下结论。

        只有"回环地址 + 连接被拒绝"不在此列 —— 那是本机服务压根没起来，见
        :func:`_is_local_refusal`。
        """
        session = await self._get_session()
        try:
            async with session.request(method, url, headers=self._headers(), **kwargs) as resp:
                return resp.status, await resp.text(), self._retry_after(resp.headers)
        except aiohttp.ClientError as err:
            if _is_local_refusal(url, err):
                raise LLMError(
                    f"{url} 上没有服务在监听（连接被拒绝：{err}）。"
                    "本地模型服务得先起来再问它（Ollama 是 ollama serve），起来后重发一次就行。"
                ) from err
            raise LLMError(f"连不上模型服务 {url}: {err}", retryable=True) from err
        except asyncio.TimeoutError as err:
            raise LLMError(f"模型服务 {url} 超过 {self.config.timeout} 秒没响应", retryable=True) from err

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    @staticmethod
    def _parse_json(text: str, what: str) -> Any:
        try:
            return json.loads(text)
        except ValueError as err:
            raise LLMError(f"{what}不是 JSON: {err}；原文: {text[:300]}") from err

    async def list_models(self) -> list[str]:
        """问服务端要可选模型清单（OpenAI 兼容的 ``GET /models``）。

        形状不对、连不上、列表为空都显式报错——宁可让面板说"拉不到列表"，
        也不要编一份列表出来让用户以为能选。
        """
        url = f"{self.config.base_url}/models"
        status, text, _retry_after = await self._get_text("GET", url)
        if status >= 400:
            raise LLMError(f"模型服务返回 {status}: {text[:500]}")
        data = self._parse_json(text, "模型列表")
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise LLMError(f"模型列表里没有 data 数组: {text[:300]}")
        models = [
            item["id"] for item in data["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        models = [name for name in models if name.strip()]
        if not models:
            raise LLMError("模型服务返回的列表是空的")
        return models

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        *,
        cancel: CancelToken | None = None,
        on_retry: RetryListener | None = None,
    ) -> ChatMessage:
        """发一轮请求，瞬时失败按策略重试，拿回一条 assistant 消息。

        ``cancel`` 置位时正在飞的 HTTP 请求会被**真的断开**（不是只丢结果），
        重试之间的等待同样可被取消。
        """
        for attempt in range(1, self.max_attempts + 1):
            started = time.monotonic()
            try:
                message, usage = await race(
                    partial(self._complete_once, messages, tools), cancel, what="模型请求"
                )
            except LLMError as err:
                elapsed = time.monotonic() - started
                if not err.retryable or attempt >= self.max_attempts:
                    _report_attempt(attempt, self.max_attempts, elapsed, error=str(err))
                    raise
                delay = self._backoff(attempt, err.retry_after)
                _report_attempt(attempt, self.max_attempts, elapsed, error=str(err), wait=delay)
                if on_retry is not None:
                    reported = on_retry(attempt, self.max_attempts, delay, str(err))
                    if reported is not None:
                        await reported
                await race(partial(asyncio.sleep, delay), cancel, what="重试等待")
            else:
                elapsed = time.monotonic() - started
                if elapsed >= ATTEMPT_LOG_THRESHOLD:
                    _report_attempt(
                        attempt, self.max_attempts, elapsed, counts=usage_counts(usage)
                    )
                return message
        # 只有 max_attempts < 1 的配置才会走到这里：显式报错，不返回一个瞎猜的结果。
        raise LLMError(f"重试次数配置为 {self.max_attempts}，一次请求都没发出去")

    @staticmethod
    def _backoff(attempt: int, retry_after: float | None) -> float:
        """第 ``attempt`` 次失败之后等多久再试。

        服务端给了 ``Retry-After`` 就听它的（那是明确指令，不再叠抖动）；否则
        0.5s 起、每次翻倍、封顶 10s，再乘一个 ±10% 的抖动错开并发。
        """
        if retry_after is not None:
            return retry_after
        base = min(RETRY_MAX_DELAY, RETRY_BASE_DELAY * (2 ** (attempt - 1)))
        return base * (1.0 + random.uniform(-RETRY_JITTER_RATIO, RETRY_JITTER_RATIO))

    async def _complete_once(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None
    ) -> tuple[ChatMessage, Any]:
        """发一次请求，拿回 ``(assistant 消息, 响应里的 usage 原文)``。

        ``usage`` **原样透传**（可能是 ``None``，也可能是形状不认识的东西），能不能用由
        调用方拿 :func:`usage_counts` 判断——这里不下结论，也不替服务端补齐。
        """
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": self.config.temperature,
        }
        if self.config.max_tokens is not None:
            payload["max_tokens"] = self.config.max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        url = f"{self.config.base_url}/chat/completions"
        status, text, retry_after = await self._get_text("POST", url, json=payload)

        if status >= 400:
            raise LLMError(
                f"模型服务返回 {status}: {text[:500]}",
                retryable=status in RETRYABLE_STATUS,
                retry_after=retry_after,
            )
        # 原文不是 JSON，多半是地址指到了别的服务：重试也是同样的结果。
        data = self._parse_json(text, "模型返回")
        if not isinstance(data, dict):
            raise LLMError(f"模型返回不是 JSON 对象: {text[:300]}")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            # 空 choices 在本地服务上多半是瞬时抖动（排队、刚换完模型），值得再试。
            raise LLMError(f"模型返回里没有 choices: {text[:300]}", retryable=True)
        message = choices[0].get("message") or {}

        calls: list[ToolCall] = []
        for index, raw in enumerate(message.get("tool_calls") or []):
            function = raw.get("function") or {}
            name = function.get("name")
            if not isinstance(name, str) or name == "":
                raise LLMError(f"第 {index} 个 tool_call 没有函数名: {json.dumps(raw, ensure_ascii=False)[:200]}")
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    parsed = json.loads(arguments) if arguments.strip() else {}
                except ValueError as err:
                    raise LLMError(f"工具 {name} 的参数不是合法 JSON: {err}；原文: {arguments[:200]}") from err
            elif isinstance(arguments, dict):
                parsed = arguments
            else:
                raise LLMError(f"工具 {name} 的参数类型不支持: {type(arguments).__name__}")
            calls.append(ToolCall(id=str(raw.get("id") or f"call_{index}"), name=name, arguments=parsed))

        content = message.get("content") or ""
        if not calls and str(content).strip() == "":
            # 既没有工具调用又没有文字：这不是一个"回答"，别把它当结论交出去。
            raise LLMError("模型返回了空回答（既没有文本也没有工具调用）", retryable=True)
        return ChatMessage(role="assistant", content=str(content), tool_calls=calls), data.get("usage")


__all__ = [
    "ATTEMPT_LOG_THRESHOLD",
    "DEFAULT_MAX_ATTEMPTS",
    "RETRYABLE_STATUS",
    "LLMConfig",
    "LLMError",
    "OpenAIChatClient",
    "RetryListener",
    "usage_counts",
]
