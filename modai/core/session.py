from __future__ import annotations

import json
import threading
from collections import deque
from pathlib import Path
from typing import Any

from .events import HarnessEvent


class SessionStore:
    """Append-only JSONL session with safe-boundary control queues."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.path = run_dir / "session.jsonl"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._steer: deque[str] = deque()
        self._follow_up: deque[str] = deque()
        self._abort = threading.Event()

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()

    def append_event(self, event: HarnessEvent) -> None:
        self.append({"type": "event", **event.as_dict()})

    def append_message(self, message: dict[str, Any]) -> None:
        self.append({"type": "message", "message": message})

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in self.records():
            if item.get("type") == "compaction" and isinstance(item.get("messages"), list):
                messages = [message for message in item["messages"] if isinstance(message, dict)]
            elif item.get("type") == "message" and isinstance(item.get("message"), dict):
                messages.append(item["message"])
        return messages

    def steer(self, text: str) -> None:
        with self._lock:
            self._steer.append(text)

    def follow_up(self, text: str) -> None:
        with self._lock:
            self._follow_up.append(text)

    def take_steering(self) -> list[str]:
        with self._lock:
            items = list(self._steer)
            self._steer.clear()
            return items

    def take_follow_up(self) -> str | None:
        with self._lock:
            return self._follow_up.popleft() if self._follow_up else None

    def abort(self) -> None:
        self._abort.set()

    @property
    def aborted(self) -> bool:
        return self._abort.is_set()
