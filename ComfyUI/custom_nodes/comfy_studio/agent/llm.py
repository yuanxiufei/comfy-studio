"""模型侧：一个极薄的 OpenAI 兼容 chat completions 客户端。

配置全部来自环境变量，避免把密钥写进仓库：

* ``COMFY_STUDIO_LLM_BASE_URL``（回退 ``OPENAI_BASE_URL``，再回退官方地址）
* ``COMFY_STUDIO_LLM_API_KEY``（回退 ``OPENAI_API_KEY``；本地服务通常不需要）
* ``COMFY_STUDIO_LLM_MODEL``（必填，没有就直接报错，不猜默认模型）
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import aiohttp

from .types import ChatMessage, ToolCall


class LLMError(RuntimeError):
    """模型侧的错误（配置缺失、HTTP 失败、返回结构不符预期）。"""


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

    def __init__(self, config: LLMConfig) -> None:
        self.config = config
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

    async def complete(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None
    ) -> ChatMessage:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": self.config.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        url = f"{self.config.base_url}/chat/completions"
        session = await self._get_session()
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                text = await resp.text()
        except aiohttp.ClientError as err:
            raise LLMError(f"连不上模型服务 {url}: {err}") from err

        if resp.status >= 400:
            raise LLMError(f"模型服务返回 {resp.status}: {text[:500]}")
        try:
            data = json.loads(text)
        except ValueError as err:
            raise LLMError(f"模型返回的不是 JSON: {err}；原文: {text[:300]}") from err

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError(f"模型返回里没有 choices: {text[:300]}")
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
        return ChatMessage(role="assistant", content=str(content), tool_calls=calls)


__all__ = ["LLMConfig", "LLMError", "OpenAIChatClient"]
