from __future__ import annotations

from collections import OrderedDict
from threading import RLock
from typing import Any


class SharedEvidenceCache:
    """Small process-local cache shared by the main coder and delegates."""

    def __init__(self, max_entries: int = 128) -> None:
        self.max_entries = max_entries
        self._items: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
                return dict(value)
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = dict(value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_entries:
                self._items.popitem(last=False)
