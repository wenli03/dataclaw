"""LLM Provider 抽象 + OpenAI 兼容实现。

运行时有两条决策路径：
1. 配置了 `LLM_API_KEY` → OpenAI 兼容 function-calling（本文件）。
2. 没有 Key → `planner.OfflinePlanner`（离线确定性，演示默认）。
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..core.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT


class LLMProvider:
    """最小 LLM Provider 接口（V2 可换 Azure/Bedrock/本地 vLLM）。"""

    name = "base"
    available = False

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        raise NotImplementedError

    async def close(self) -> None:
        return None


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or LLM_BASE_URL).rstrip("/")
        self.api_key = api_key or LLM_API_KEY
        self.model = model or LLM_MODEL
        self.available = bool(self.api_key)

    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        if not self.available:
            raise RuntimeError("未配置 LLM_API_KEY")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        last_exc: Exception | None = None
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    choices = data.get("choices") or []
                    if not choices:
                        raise RuntimeError(f"LLM 返回为空: {data}")
                    choice = choices[0]
                    message = choice.get("message") or {}
                    return {
                        "content": message.get("content") or "",
                        "tool_calls": message.get("tool_calls") or [],
                        "usage": data.get("usage") or {},
                        "finish_reason": choice.get("finish_reason") or "",
                    }
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise RuntimeError(f"LLM 调用失败：{last_exc}")


def get_provider() -> LLMProvider | None:
    """有 Key 返回 Provider，否则 None（调用方退化到离线 Planner）。"""
    if not LLM_API_KEY:
        return None
    provider = OpenAICompatibleProvider()
    return provider if provider.available else None


def tool_call_to_step(call: dict) -> dict:
    """把 OpenAI tool_call 归一为内部 {name, params, id}。"""
    fn = (call or {}).get("function") or {}
    raw_args = fn.get("arguments") or "{}"
    if isinstance(raw_args, str):
        try:
            params = json.loads(raw_args)
        except Exception:
            params = {}
    else:
        params = raw_args if isinstance(raw_args, dict) else {}
    return {"name": fn.get("name") or "", "params": params, "callId": call.get("id") or ""}
