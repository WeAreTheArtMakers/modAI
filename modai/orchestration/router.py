from __future__ import annotations

from dataclasses import dataclass


MODES = {"solo", "auto", "orchestra"}


@dataclass(frozen=True, slots=True)
class Route:
    mode: str
    reason: str
    delegate: bool = False


class TaskRouter:
    """Deterministic router. Normal software work strongly favors one coder."""

    def route(self, task: str, requested: str = "auto") -> Route:
        if requested not in MODES:
            raise ValueError("mode must be solo, auto, or orchestra")
        if requested == "solo":
            return Route("solo", "explicit solo mode")
        if requested == "orchestra":
            return Route("orchestra", "explicit orchestra mode", True)
        folded = task.casefold()
        software = any(item in folded for item in (
            "code", "kod", "bug", "fix", "düzelt", "html", "css", "javascript", "python",
            "test", "build", "landing", "website", "uygulama", "refactor", "implement",
        ))
        broad = any(item in folded for item in (
            "deep research", "derin araştır", "market research", "pazar araştır",
            "independent review", "bağımsız inceleme", "compare 10", "karşılaştır ve araştır",
        ))
        if software and not broad:
            return Route("solo", "software task: persistent coder is the lowest-overhead path")
        if broad:
            return Route("orchestra", "bounded independent research/review is useful", True)
        return Route("solo", "auto defaults to the persistent coder")
