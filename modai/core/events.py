from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(slots=True)
class HarnessEvent:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[HarnessEvent], None]] = []

    def subscribe(self, callback: Callable[[HarnessEvent], None]) -> None:
        self._subscribers.append(callback)

    def emit(self, kind: str, **data: Any) -> HarnessEvent:
        event = HarnessEvent(kind, data)
        for callback in tuple(self._subscribers):
            callback(event)
        return event
