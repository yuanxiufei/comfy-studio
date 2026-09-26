"""模型侧：一个极薄的 OpenAI 兼容 chat completions 客户端。

配置全部来自环境变量，免密钥进仓库：

* ``COMFY_STUDIO_LLM_MODEL`` —— **必填**，没有就直接报错，不猜默认模型；
* ``COMFY_STUDIO_LLM_BASE_URL``（回退 ``OPENAI_BASE_URL``，再回退官方地址）；
* ``COMFY_STUDIO_LLM_API_KEY``（回退 ``OPENAI_API_KEY``；本地服务通常不需要）。

环境变量给的是**默认**模型；面板里的模型切换是在这之上换一个（见
:meth:`OpenAIChatClient.list_models`：可选清单直接问服务端的
``GET {base_url}/models``，本地 Ollama / LM Studio / vLLM 都实现了这个口）。

请求失败会**按策略重试**（常量见下）：传输层错误、超时、限流、服务端 5xx、以及
"200 但回答是空的"都会重试；认证与参数错误**不重试**，因为再试也不会变好。
重试过程通过 ``on_retry`` 往外报，面板可以据此显示"正在重试第 N 次"。

用 aiohttp 而不是 ``urllib``：引擎 venv 里本来就有 aiohttp（ComfyUI 的依赖），
不额外引入新包。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Awaitable, Callable

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

#: ``on_retry(第几次失败, 总共几次, 等多久, 失败原因)``；返回 awaitable 就会被 await。
RetryListener = Callable[[int, int, float, str], "Awaitable[None] | None"]


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
        )


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
        """
        session = await self._get_session()
        try:
            async with session.request(method, url, headers=self._headers(), **kwargs) as resp:
                return resp.status, await resp.text(), self._retry_after(resp.headers)
        except aiohttp.ClientError as err:
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
            try:
                return await race(partial(self._complete_once, messages, tools), cancel, what="模型请求")
            except LLMError as err:
                if not err.retryable or attempt >= self.max_attempts:
                    raise
                delay = self._backoff(attempt, err.retry_after)
                if on_retry is not None:
                    reported = on_retry(attempt, self.max_attempts, delay, str(err))
                    if reported is not None:
                        await reported
                await race(partial(asyncio.sleep, delay), cancel, what="重试等待")
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
    ) -> ChatMessage:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": self.config.temperature,
        }
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
        return ChatMessage(role="assistant", content=str(content), tool_calls=calls)


__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "RETRYABLE_STATUS",
    "LLMConfig",
    "LLMError",
    "OpenAIChatClient",
    "RetryListener",
]
