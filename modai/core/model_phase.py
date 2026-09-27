"""Model transport/recovery phase, independent of tool execution and routing."""
from __future__ import annotations
import time
from typing import Any


class ModelPhase:
    def _request_model(self, schemas: list[dict[str, Any]], turns: int,
                       report: Any, completion_candidate: bool) -> tuple[Any, Any, Any]:
        retry = 0
        while True:
            self._model_calls += 1
            self.events.emit("model_started", turn=turns, attempt=retry + 1)
            try:
                gen_kw: dict[str, Any] = {
                    "on_text": lambda text: self.events.emit("text_delta", text=text),
                }
                if self._reduced_context_retry and self._runtime_reduced_ctx:
                    gen_kw["_reduced_context"] = True
                response = self.runtime.generate(
                    self._messages,
                    schemas,
                    **gen_kw,
                )
                self._reduced_context_retry = False
                return response, report, None
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                self.events.emit(
                    "model_failed", error=detail, transient=self._transient_model_error(exc)
                )
                if self.coding_tools.mutated_paths:
                    report = self._verify()
                if not self._transient_model_error(exc) or retry >= self.model_retries:
                    return None, report, self._timeout_result(
                        exc, report, turns, completion_candidate=completion_candidate
                    )
                retry += 1
                before_compact = len(self._messages)
                self.compact()
                after_compact = len(self._messages)
                recovery: dict[str, Any] = {
                    "role": "user",
                    "content": (
                        f"LOCAL MODEL REQUEST RECOVERY {retry}/{self.model_retries}. "
                        "The prior request ended before a complete response and no tool call "
                        "from it was executed. Continue from the saved repository. "
                        "Use one small complete tool call; do not repeat completed reads."
                    ),
                }
                if report is not None and report.verdict != "PASS":
                    recovery["content"] += "\n" + self._verification_message(report).get(
                        "content", ""
                    )
                self._messages.append(recovery)
                self._append(recovery)
                self.events.emit(
                    "model_retry",
                    attempt=retry,
                    maximum=self.model_retries,
                    error=detail,
                    delay=self.retry_backoff_seconds * retry,
                    context_before=before_compact,
                    context_after=after_compact,
                )
                self._reduced_context_retry = True
                if self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds * retry)
