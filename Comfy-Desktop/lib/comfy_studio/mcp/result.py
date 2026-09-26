"""读 MCP 工具返回值的几个小工具。

MCP 的 ``tools/call`` 结果是 ``{"content": [{"type": "text", "text": ...}], "isError": bool}``：
工具**执行**失败不算协议错误，而是回一个 ``isError: true`` 的正常结果。所以上层
必须显式看这个标志位，否则会把失败当成功——这几个函数就是把这件事收口。
"""

from __future__ import annotations

import json
from typing import Any

from .client import McpError


def result_text(result: Any) -> str:
    """把结果的文本块拼起来；没有文本块就把整个结果序列化成 JSON。"""
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, default=str)
    blocks = result.get("content")
    if not isinstance(blocks, list):
        return json.dumps(result, ensure_ascii=False, default=str)
    parts = [b.get("text", "") for b in blocks if isinstance(b, dict)]
    text = "\n".join(p for p in parts if p)
    return text or json.dumps(result, ensure_ascii=False, default=str)


def error_message(result: Any) -> str | None:
    """工具报错时返回错误文本，否则 None。"""
    if isinstance(result, dict) and result.get("isError") is True:
        return result_text(result)
    return None


def result_json(result: Any, what: str) -> Any:
    """工具结果的文本按 JSON 解析。

    引擎侧的 skill 工具一律用 ``text_result`` 回 JSON 文本，所以这里是常规路径；
    工具报错或文本不是 JSON 都直接抛 :class:`McpError`，不做静默兜底。
    """
    message = error_message(result)
    if message is not None:
        raise McpError(f"{what} 失败: {message}")
    text = result_text(result)
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        raise McpError(f"{what} 的返回不是 JSON: {err}；原文: {text[:300]}") from err


def tool_text(result: Any) -> str:
    """喂给模型看的文本：出错时显式标 ``ERROR:``。"""
    message = error_message(result)
    if message is not None:
        return f"ERROR: {message}"
    return result_text(result)


__all__ = ["error_message", "result_json", "result_text", "tool_text"]
