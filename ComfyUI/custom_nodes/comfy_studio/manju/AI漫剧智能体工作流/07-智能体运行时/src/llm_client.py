# -*- coding: utf-8 -*-
"""LLM 客户端（**可选**）—— 用大模型做语义解析与视觉补全。

分两层，**有 Key 用 LLM，没 Key 用规则**：

    解析层  nl_parser（规则）  ←→  llm_client（语义）   → 同一个 ParsedInput
    补全层  character_agent 的映射表  ←→  llm_client   → 同一个 AssetCard

用标准库 urllib（不依赖 requests），兼容任何 `POST {base_url}/chat/completions` 的服务：
OpenAI / DeepSeek / 智谱 GLM / 通义 / Moonshot / Ollama / vLLM …
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class LLMClient:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg or {}
        self.api_key = (cfg.get("api_key") or os.getenv("MODEL_API_KEY")
                        or os.getenv("OPENAI_API_KEY") or "")
        self.base_url = (cfg.get("base_url") or os.getenv("MODEL_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.model = cfg.get("model") or os.getenv("MODEL_NAME") or "gpt-4o-mini"
        self.timeout = cfg.get("timeout", 120)
        self.temperature = cfg.get("temperature", 0.4)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def status(self) -> str:
        return (f"✅ {self.base_url} · {self.model}" if self.available
                else "❌ 未配置 MODEL_API_KEY（将使用规则解析）")

    def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        if not self.available:
            raise RuntimeError("LLM 未配置：设置 MODEL_API_KEY 后可用")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"LLM HTTP {e.code}：{e.read().decode('utf-8', 'ignore')[:300]}") from e
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败：{e}") from e
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"LLM 响应结构异常：{json.dumps(data)[:300]}") from e

    def complete_json(self, system: str, user: str) -> dict:
        return extract_json(self.chat(system, user, json_mode=True))


def extract_json(text: str) -> dict:
    """从可能含 ```json 代码块/前后缀的文本里抽出第一个 JSON 对象。"""
    if not text:
        raise RuntimeError("LLM 返回空内容")
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        return json.loads(t[i:j + 1])
    raise RuntimeError(f"无法从返回中解析 JSON：{text[:200]}")
