"""One-process FIFO gate for MODAI-owned local inference (not an Ollama server lock)."""
from __future__ import annotations

import re
import inspect
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable

from modai.models.base import ModelRuntime


class InferencePaused(RuntimeError):
    """No new inference may start until resource pressure or cancellation clears."""


@dataclass(frozen=True)
class ResourceSnapshot:
    total_bytes: int | None = None
    free_percent: int | None = None
    source: str = "unavailable"


def mac_resource_snapshot() -> ResourceSnapshot:
    """Best-effort macOS telemetry; no model load or global Ollama changes."""
    if sys.platform != "darwin":
        return ResourceSnapshot()
    total = None
    free = None
    try:
        result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                text=True, timeout=2, check=False)
        if result.returncode == 0:
            total = int(result.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    try:
        result = subprocess.run(["memory_pressure", "-Q"], capture_output=True,
                                text=True, timeout=3, check=False)
        match = re.search(r"System-wide free percentage:\s*(\d+)%", result.stdout)
        if result.returncode == 0 and match:
            free = max(0, min(int(match.group(1)), 100))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ResourceSnapshot(total, free, "macOS memory_pressure" if free is not None else "unavailable")


def effective_context(requested: int, profile: str, snapshot: ResourceSnapshot) -> tuple[int, str | None]:
    """Conservative token-context target, not an estimate of KV-cache bytes."""
    if profile == "fast":
        return min(requested, 8192), None
    if profile == "balanced":
        if requested > 8192 and (snapshot.total_bytes or 0) >= 16 * 1024**3 and (snapshot.free_percent or 0) >= 35:
            return min(requested, 16384), "16K context depends on observed headroom; monitor memory pressure"
        return min(requested, 8192), "Context capped at 8192 without measured headroom" if requested > 8192 else None
    if profile == "extended":
        if (snapshot.total_bytes or 0) >= 24 * 1024**3 and (snapshot.free_percent or 0) >= 35:
            return min(requested, 32768), "Experimental extended context; memory use is model-dependent"
        return min(requested, 8192), "Extended context unavailable without >24 GB and measured headroom"
    raise ValueError("resource profile must be fast, balanced or extended")


class LocalInferenceScheduler:
    """Serialize only MODAI's model generations, preserving streaming callbacks."""

    def __init__(self, runtime: ModelRuntime, *, max_waiters: int = 8,
                 wait_timeout: float = 720.0,
                 probe: Callable[[], ResourceSnapshot] = mac_resource_snapshot,
                 minimum_free_percent: int = 5) -> None:
        self.runtime = runtime
        self.provider = runtime.provider
        self.model = runtime.model
        self.supports_native_tools = runtime.supports_native_tools
        self.max_waiters = max(1, max_waiters)
        self.wait_timeout = max(0.01, wait_timeout)
        self.probe = probe
        self.minimum_free_percent = minimum_free_percent
        self._condition = threading.Condition()
        self._queue: deque[object] = deque()
        self._active = False
        self._owner: int | None = None
        self._cancelled = False
        self.paused_reason: str | None = None
        self.max_observed_concurrency = 0
        try:
            self._reduced_context = "_reduced_context" in inspect.signature(runtime.generate).parameters
        except (TypeError, ValueError):
            self._reduced_context = False

    def cancel(self) -> None:
        with self._condition:
            self._cancelled = True
            self._condition.notify_all()

    def generate(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
                 on_text: Any = None, max_output_tokens: int | None = None,
                 _reduced_context: bool = False):
        owner = threading.get_ident()
        ticket = object()
        deadline = time.monotonic() + self.wait_timeout
        with self._condition:
            if self._owner == owner:
                raise RuntimeError("reentrant local inference is not allowed")
            if self._cancelled:
                raise InferencePaused("local inference was cancelled")
            if len(self._queue) >= self.max_waiters:
                raise InferencePaused("local inference queue is full")
            self._queue.append(ticket)
            try:
                while self._queue[0] is not ticket or self._active:
                    if self._cancelled:
                        raise InferencePaused("local inference was cancelled")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise InferencePaused("local inference queue wait timed out")
                    self._condition.wait(min(remaining, 0.25))
                if self._cancelled:
                    raise InferencePaused("local inference was cancelled")
                self._active = True
                self._owner = owner
                self._queue.popleft()
                self.max_observed_concurrency = max(self.max_observed_concurrency, 1)
            except BaseException:
                if ticket in self._queue:
                    self._queue.remove(ticket)
                self._condition.notify_all()
                raise
        try:
            snapshot = self.probe()
            if snapshot.free_percent is not None and snapshot.free_percent < self.minimum_free_percent:
                self.paused_reason = f"measured free memory {snapshot.free_percent}% below {self.minimum_free_percent}%"
                raise InferencePaused(self.paused_reason)
            kwargs = {"on_text": on_text, "max_output_tokens": max_output_tokens}
            if self._reduced_context:
                kwargs["_reduced_context"] = _reduced_context
            return self.runtime.generate(messages, tools, **kwargs)
        finally:
            with self._condition:
                self._active = False
                self._owner = None
                self._condition.notify_all()
