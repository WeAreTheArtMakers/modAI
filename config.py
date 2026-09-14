from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"


@dataclass(slots=True)
class Settings:
    model: str = "mod-agent:latest"
    host: str = "http://127.0.0.1:11434"
    context_size: int = 8192
    temperature: float = 0.25
    workspace: str = "./workspace"
    max_agents: int = 24
    max_tool_rounds: int = 8
    debate_rounds: int = 2
    repair_rounds: int = 2
    max_hours: float = 12.0
    # This is a cloud-cost guard only. Local Ollama usage is deliberately
    # unlimited because it does not create a per-token provider charge.
    # The legacy name is kept so existing config.json files and commands keep
    # working; the UI exposes it as cloud_token_budget.
    max_total_tokens: int = 500000
    agent_retries: int = 1
    internet_enabled: bool = True
    keep_alive: str = "5m"
    think: bool = False
    language: str = "tr"
    cloud_enabled: bool = False
    cloud_provider: str = "openai"
    cloud_model: str = ""
    cloud_roles: str = "market_researcher,competitor_analyst,growth_marketer"
    execution_mode: str = "adaptive"
    max_parallel_agents: int = 0
    evidence_cache_entries: int = 128
    browser_quality_gate: bool = True
    full_orchestra: bool = False
    stream_output: bool = True
    visual_review: bool = True
    harness_mode: str = "auto"
    harness_max_turns: int = 80
    compaction_reserve_tokens: int = 2048

    def validate(self) -> None:
        if not self.model.strip():
            raise ValueError("model boş olamaz")
        if not self.host.startswith(("http://", "https://")):
            raise ValueError("host http:// veya https:// ile başlamalı")
        if (urlparse(self.host).hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Gizlilik için Ollama host yalnızca localhost olabilir")
        if not 2048 <= self.context_size <= 131072:
            raise ValueError("context_size 2048 ile 131072 arasında olmalı")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature 0 ile 2 arasında olmalı")
        if not 1 <= self.max_agents <= 256:
            raise ValueError("max_agents 1 ile 256 arasında olmalı")
        if not 1 <= self.max_tool_rounds <= 50:
            raise ValueError("max_tool_rounds 1 ile 50 arasında olmalı")
        if not 0 <= self.debate_rounds <= 20:
            raise ValueError("debate_rounds 0 ile 20 arasında olmalı")
        if not 0 <= self.repair_rounds <= 20:
            raise ValueError("repair_rounds 0 ile 20 arasında olmalı")
        if not 0.1 <= self.max_hours <= 168:
            raise ValueError("max_hours 0.1 ile 168 arasında olmalı")
        if not 1000 <= self.max_total_tokens <= 1000000000:
            raise ValueError("cloud_token_budget 1000 ile 1000000000 arasında olmalı")
        if not 0 <= self.agent_retries <= 10:
            raise ValueError("agent_retries 0 ile 10 arasında olmalı")
        if self.language not in {"tr", "en"}:
            raise ValueError("language yalnızca tr veya en olabilir")
        if self.cloud_provider not in {"openai", "anthropic", "google"}:
            raise ValueError("cloud_provider openai, anthropic veya google olmalı")
        if self.cloud_enabled and not self.cloud_model.strip():
            raise ValueError("cloud_enabled açıkken cloud_model belirtilmeli")
        if self.execution_mode not in {"sequential", "adaptive", "parallel"}:
            raise ValueError("execution_mode sequential, adaptive veya parallel olmalı")
        if not 0 <= self.max_parallel_agents <= 8:
            raise ValueError("max_parallel_agents 0 ile 8 arasında olmalı")
        if not 16 <= self.evidence_cache_entries <= 1024:
            raise ValueError("evidence_cache_entries 16 ile 1024 arasında olmalı")
        if self.harness_mode not in {"solo", "auto", "orchestra"}:
            raise ValueError("harness_mode solo, auto veya orchestra olmalı")
        if not 8 <= self.harness_max_turns <= 500:
            raise ValueError("harness_max_turns 8 ile 500 arasında olmalı")
        if not 512 <= self.compaction_reserve_tokens <= 16384:
            raise ValueError("compaction_reserve_tokens 512 ile 16384 arasında olmalı")

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cloud_token_budget"] = data.pop("max_total_tokens")
        data["local_token_limit"] = None
        return data

    @property
    def cloud_token_budget(self) -> int:
        """Human-facing alias for the legacy max_total_tokens config key."""
        return self.max_total_tokens

    @cloud_token_budget.setter
    def cloud_token_budget(self, value: int) -> None:
        self.max_total_tokens = value


def load_settings(path: Path = DEFAULT_CONFIG) -> Settings:
    data: dict[str, Any] = {}
    if path.exists():
        parsed = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError(f"{path.name} bir JSON nesnesi olmalı")
        data.update(parsed)

    # Safe aliases emitted by older UI/export versions. Canonical values win
    # when both are present; local_token_limit was informational and is ignored.
    for old, new in (("cloud_token_budget", "max_total_tokens"),
                     ("num_ctx", "context_size"), ("mode", "harness_mode")):
        if old in data and new not in data:
            data[new] = data[old]
        data.pop(old, None)
    data.pop("local_token_limit", None)

    known = {item.name for item in fields(Settings)}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"Bilinmeyen ayar(lar): {', '.join(unknown)}")

    def to_bool(value: str) -> bool:
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Geçersiz boolean değer: {value}")

    env_map: dict[str, tuple[str, Any]] = {
        "MOD_AGENT_MODEL": ("model", str),
        "MOD_AGENT_HOST": ("host", str),
        "MOD_AGENT_CONTEXT_SIZE": ("context_size", int),
        "MOD_AGENT_TEMPERATURE": ("temperature", float),
        "MOD_AGENT_WORKSPACE": ("workspace", str),
        "MOD_AGENT_MAX_AGENTS": ("max_agents", int),
        "MOD_AGENT_MAX_TOOL_ROUNDS": ("max_tool_rounds", int),
        "MOD_AGENT_DEBATE_ROUNDS": ("debate_rounds", int),
        "MOD_AGENT_REPAIR_ROUNDS": ("repair_rounds", int),
        "MOD_AGENT_MAX_HOURS": ("max_hours", float),
        "MODAI_MAX_TOTAL_TOKENS": ("max_total_tokens", int),
        "MODAI_CLOUD_TOKEN_BUDGET": ("max_total_tokens", int),
        "MOD_AGENT_AGENT_RETRIES": ("agent_retries", int),
        "MOD_AGENT_INTERNET": ("internet_enabled", to_bool),
        "MOD_AGENT_KEEP_ALIVE": ("keep_alive", str),
        "MOD_AGENT_THINK": ("think", to_bool),
        "MOD_AGENT_LANGUAGE": ("language", str),
        "MODAI_CLOUD_ENABLED": ("cloud_enabled", to_bool),
        "MODAI_CLOUD_PROVIDER": ("cloud_provider", str),
        "MODAI_CLOUD_MODEL": ("cloud_model", str),
        "MODAI_CLOUD_ROLES": ("cloud_roles", str),
        "MODAI_EXECUTION_MODE": ("execution_mode", str),
        "MODAI_MAX_PARALLEL_AGENTS": ("max_parallel_agents", int),
        "MODAI_EVIDENCE_CACHE_ENTRIES": ("evidence_cache_entries", int),
        "MODAI_BROWSER_QUALITY_GATE": ("browser_quality_gate", to_bool),
        "MODAI_MODE": ("harness_mode", str),
        "MODAI_HARNESS_MAX_TURNS": ("harness_max_turns", int),
        "MODAI_COMPACTION_RESERVE_TOKENS": ("compaction_reserve_tokens", int),
    }
    for env_name, (setting_name, convert) in env_map.items():
        value = os.getenv(env_name)
        if value is not None:
            data[setting_name] = convert(value)

    settings = Settings(**data)
    settings.validate()
    return settings
