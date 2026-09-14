from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}
PROVIDER_KEYCHAIN_SERVICES = {
    "openai": "MODAI OpenAI API Key",
    "anthropic": "MODAI Anthropic API Key",
    "google": "MODAI Google API Key",
}


def api_key_for(provider: str) -> str:
    environment_name = PROVIDER_ENV_KEYS[provider]
    value = os.getenv(environment_name, "").strip()
    if value:
        return value
    if os.uname().sysname == "Darwin":
        result = subprocess.run(
            ["security", "find-generic-password", "-s", PROVIDER_KEYCHAIN_SERVICES[provider], "-w"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    raise RuntimeError(
        f"{provider} API anahtarı bulunamadı. {environment_name} ayarlayın veya /cloud setup kullanın."
    )


def save_api_key(provider: str, value: str) -> None:
    if not value.strip():
        raise ValueError("API anahtarı boş olamaz")
    if os.uname().sysname != "Darwin":
        raise RuntimeError(f"Bu platformda {PROVIDER_ENV_KEYS[provider]} ortam değişkenini kullanın")
    subprocess.run(
        [
            "security", "add-generic-password", "-U", "-a", os.getenv("USER", "modai"),
            "-s", PROVIDER_KEYCHAIN_SERVICES[provider], "-w", value.strip(),
        ],
        capture_output=True, text=True, timeout=15, check=True,
    )


def contains_obvious_secret(text: str) -> bool:
    patterns = (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b",
        r"\bAIza[0-9A-Za-z_-]{20,}\b",
        r"(?i:\b(?:password|passwd|secret|api[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+)",
    )
    return any(re.search(pattern, text) for pattern in patterns)


class CloudClient:
    def __init__(self, provider: str, model: str, timeout: float = 600.0) -> None:
        if provider not in PROVIDER_ENV_KEYS:
            raise ValueError("Bulut sağlayıcısı openai, anthropic veya google olmalı")
        if not model.strip():
            raise ValueError("Bulut modeli boş olamaz")
        self.provider = provider
        self.model = model
        self.timeout = timeout

    def chat(self, **kwargs: Any) -> dict[str, Any]:
        messages = kwargs.get("messages", [])
        temperature = float(kwargs.get("options", {}).get("temperature", 0.25))
        num_predict = int(kwargs.get("options", {}).get("num_predict", 2048))
        if self.provider == "openai":
            return self._openai(messages, temperature, num_predict)
        if self.provider == "anthropic":
            return self._anthropic(messages, temperature, num_predict)
        return self._google(messages, temperature, num_predict)

    def _request(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        request = Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **headers}, method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:1000]
            raise RuntimeError(f"{self.provider} HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{self.provider} isteği başarısız: {exc}") from exc

    def _openai(self, messages: list[dict[str, Any]], temperature: float, limit: int) -> dict[str, Any]:
        instructions = "\n\n".join(str(item.get("content", "")) for item in messages if item.get("role") == "system")
        conversation = [item for item in messages if item.get("role") in {"user", "assistant"}]
        data = self._request(
            "https://api.openai.com/v1/responses",
            {"model": self.model, "instructions": instructions, "input": conversation, "max_output_tokens": limit,
             "tools": [{"type": "web_search"}]},
            {"Authorization": f"Bearer {api_key_for('openai')}"},
        )
        content = str(data.get("output_text", ""))
        if not content:
            content = "\n".join(
                str(part.get("text", ""))
                for item in data.get("output", []) if isinstance(item, dict)
                for part in item.get("content", []) if isinstance(part, dict) and part.get("type") == "output_text"
            )
        usage = data.get("usage", {})
        return self._normalized(content, usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    def _anthropic(self, messages: list[dict[str, Any]], temperature: float, limit: int) -> dict[str, Any]:
        system = "\n\n".join(str(item.get("content", "")) for item in messages if item.get("role") == "system")
        conversation = [item for item in messages if item.get("role") in {"user", "assistant"}]
        data = self._request(
            "https://api.anthropic.com/v1/messages",
            {"model": self.model, "system": system, "messages": conversation, "temperature": temperature, "max_tokens": limit},
            {"x-api-key": api_key_for("anthropic"), "anthropic-version": "2023-06-01"},
        )
        content = "\n".join(str(item.get("text", "")) for item in data.get("content", []) if item.get("type") == "text")
        usage = data.get("usage", {})
        return self._normalized(content, usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    def _google(self, messages: list[dict[str, Any]], temperature: float, limit: int) -> dict[str, Any]:
        system = "\n\n".join(str(item.get("content", "")) for item in messages if item.get("role") == "system")
        contents = [
            {"role": "model" if item.get("role") == "assistant" else "user", "parts": [{"text": str(item.get("content", ""))}]}
            for item in messages if item.get("role") in {"user", "assistant"}
        ]
        data = self._request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model, safe='')}:generateContent",
            {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
             "generationConfig": {"temperature": temperature, "maxOutputTokens": limit}},
            {"x-goog-api-key": api_key_for("google")},
        )
        candidates = data.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        content = "\n".join(str(item.get("text", "")) for item in parts)
        usage = data.get("usageMetadata", {})
        return self._normalized(content, usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0))

    @staticmethod
    def _normalized(content: str, input_tokens: Any, output_tokens: Any) -> dict[str, Any]:
        return {
            "message": {"content": content.strip(), "tool_calls": []},
            "prompt_eval_count": int(input_tokens or 0), "eval_count": int(output_tokens or 0),
        }
