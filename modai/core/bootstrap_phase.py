"""Isolated bootstrap phase helpers."""
from __future__ import annotations

from typing import Any
import json
import time
from modai.tools.coding import MODEL_WRITE_MAX_CHARS, BOOTSTRAP_WRITE_TARGET_CHARS, RESCUE_EVIDENCE_MAX_CHARS

_INTERNAL_PATHS = frozenset({'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', '.modai', '.benchmark_run', '.run', 'dist', 'build', 'coverage'})


class BootstrapPhase:
    @staticmethod
    def _is_useful_discovery(name: str, ok: bool, result: Any) -> bool:
        """v4.1: only successful discovery carrying real content consumes budget.

        Failed reads (FileNotFoundError, empty results) are not evidence.
        """
        if not ok or name not in {"read", "grep", "find", "ls"}:
            return False
        if not isinstance(result, dict) or "error" in result or "error_code" in result:
            return False
        if name == "read":
            return bool(str(result.get("content", "")).strip())
        if name == "grep":
            return bool(str(result.get("matches", "")).strip())
        return bool(result.get("entries") or result.get("matches"))


    def _top_level_paths(self, limit: int = 20) -> list[str]:
        """Real top-level entries for PATH_NOT_FOUND guidance (internals hidden)."""
        try:
            entries = sorted(
                entry.name + ("/" if entry.is_dir() else "")
                for entry in self.workspace.iterdir()
                if entry.name not in _INTERNAL_PATHS
            )
        except OSError:
            return []
        return entries[:limit]


    def _rescue_evidence(self, limit: int = RESCUE_EVIDENCE_MAX_CHARS) -> str:
        """Deterministic bounded evidence for the bootstrap-rescue context.

        Clipped contents of successful read results already in the session;
        falls back to the top-level tree. No summarization, no extra model call.
        """
        chunks: list[str] = []
        used = 0
        for msg in self._messages:
            if msg.get("role") != "tool" or msg.get("name") != "read":
                continue
            body = str(msg.get("content", ""))
            try:
                payload = json.loads(body)
                if isinstance(payload, dict) and payload.get("content"):
                    body = str(payload["content"])
            except (ValueError, TypeError):
                pass
            if not body.strip():
                continue
            chunks.append(body)
            used += len(body)
            if used >= limit:
                break
        text = "\n---\n".join(chunks)[:limit]
        if text.strip():
            return text
        return "Top-level workspace paths:\n" + "\n".join(self._top_level_paths())


    def _capped_write_schema(self, description: str) -> dict[str, Any] | None:
        """Write-only schema copy advertising the real hard maximum.

        Deep-copied per call; the global SCHEMAS table is never mutated.
        """
        base = next(
            (s for s in self.registry.schemas(allowed_names={"write"})), None
        )
        if base is None:
            return None
        schema = json.loads(json.dumps(base))
        try:
            content_prop = schema["function"]["parameters"]["properties"]["content"]
        except (KeyError, TypeError):
            return None
        content_prop["maxLength"] = MODEL_WRITE_MAX_CHARS
        content_prop["description"] = description
        return schema


    def _bootstrap_rescue(self, turns: int) -> dict[str, Any] | None:
        """Fresh micro-context bootstrap after length truncation, plus ONE
        size-correction pass for a completed-but-oversized write.

        Returns the executed write result when it reports changed=True, else
        None (fail-fast; the caller ends the run). Success merges the
        assistant tool call + tool result into the main session transcript.
        Only CONTENT_TOO_LARGE triggers the correction, and only once:
        transport errors, repair mode, and non-write calls never enter it.
        """
        schema = self._capped_write_schema(
            "Create a small first artifact. Aim for roughly "
            f"{BOOTSTRAP_WRITE_TARGET_CHARS} characters. Hard maximum: "
            f"{MODEL_WRITE_MAX_CHARS} characters. Larger files must be "
            "continued in later write/append/edit calls."
        )
        if schema is None:
            self.events.emit("bootstrap_rescue", outcome="skipped",
                             reason="write tool unavailable")
            return None

        def attempt(messages: list[dict[str, Any]], label: str) -> tuple[Any | None, Any | None, Any | None]:
            """One generate + single-write execute + transcript merge.

            Returns (response, call, result); result is None unless a single
            write call executed. Merges nothing unless a write executed.
            """
            self._model_calls += 1
            self._pre_mutation_stats["bootstrap_rescue_attempts"] += 1
            self.events.emit("model_started", turn=turns, attempt=label)
            try:
                response = self.runtime.generate(
                    messages, [schema],
                    on_text=lambda text: self.events.emit("text_delta", text=text),
                )
            except Exception as exc:
                self.events.emit("bootstrap_rescue", outcome="failed",
                                 reason=f"{type(exc).__name__}: {exc}")
                return None, None, None
            self._record_usage(response)
            calls = response.tool_calls or []
            if len(calls) != 1 or calls[0].name != "write":
                self.events.emit("bootstrap_rescue", outcome="failed",
                                 reason="no single write call",
                                 content_length=len(response.content),
                                 truncated=response.truncated)
                return response, None, None
            call = calls[0]
            self._tool_calls += 1
            self.events.emit("tool_started", name=call.name, arguments=call.arguments,
                             rescue=True)
            try:
                result = self.registry.execute(call.name, call.arguments)
            except Exception as exc:
                result = {"error": f"{type(exc).__name__}: {exc}"}
            assistant = self._assistant_message(response)
            self._messages.append(assistant)
            self._append(assistant)
            tool_message = {
                "role": "tool", "tool_call_id": call.id, "name": call.name,
                "content": self.registry.model_result(result),
            }
            self._messages.append(tool_message)
            self._append(tool_message)
            self.events.emit("tool_finished", name=call.name,
                             ok="error" not in result, result=result, rescue=True)
            return response, call, result

        rescue_messages = [
            {"role": "system", "content": (
                "You are MODAI Code Virtuoso. Execute exactly one bounded "
                "bootstrap mutation. Use the provided write tool. Do not "
                "complete the whole task in this turn."
            )},
            {"role": "user", "content": "OBJECTIVE\n" + self.task},
            {"role": "user", "content": (
                "KNOWN PRODUCT FACTS (clipped evidence, authoritative for names only):\n"
                + self._rescue_evidence()
            )},
            {"role": "user", "content": (
                "CURRENT SUBTASK\n"
                "Create only the first small artifact.\n"
                "Aim for roughly 2500 characters.\n"
                "Hard maximum: 4000 characters.\n"
                "Do not complete the full application in this turn.\n"
                "Use later write/append/edit calls for additional content.\n"
                "For a web page:\n"
                "- create index.html\n"
                "- valid HTML scaffold only\n"
                "- link styles.css\n"
                "- no inline CSS\n"
                "- do not complete styling\n"
                "- call write exactly once"
            )},
        ]
        self.events.emit("bootstrap_rescue", outcome="attempted", turn=turns)
        _, _, result = attempt(rescue_messages, "rescue")
        if isinstance(result, dict) and result.get("changed"):
            self.events.emit("bootstrap_rescue", outcome="succeeded",
                             path=result.get("path"))
            return result
        # v4.1.5: exactly ONE size-correction pass for a completed write that
        # overshot the hard limit. The rejected content is NOT fed back —
        # only its size — so the retry cannot re-derive the same overshoot.
        if not (isinstance(result, dict)
                and result.get("error_code") == "CONTENT_TOO_LARGE"
                and self._pre_mutation_stats["bootstrap_size_corrections"] == 0):
            self.events.emit("bootstrap_rescue", outcome="failed",
                             reason="write reported no change")
            return None
        actual = int(result.get("actual_chars", 0) or 0)
        self._pre_mutation_stats["bootstrap_size_corrections"] = 1
        self._pre_mutation_stats["bootstrap_oversize_chars"] = actual
        self.events.emit("bootstrap_size_correction", outcome="attempted",
                         actual_chars=actual, hard_max=MODEL_WRITE_MAX_CHARS, turn=turns)
        correction_messages = [
            {"role": "system", "content": (
                "You are MODAI Code Virtuoso. Execute exactly one bounded "
                "bootstrap mutation. Use the provided write tool."
            )},
            {"role": "user", "content": "OBJECTIVE\n" + self.task},
            {"role": "user", "content": (
                "BOOTSTRAP SIZE CORRECTION\n\n"
                f"Your previous write call was {actual} characters.\n"
                f"The hard maximum is {MODEL_WRITE_MAX_CHARS} characters.\n\n"
                "Create the same FIRST ARTIFACT again, but only as a minimal "
                "valid scaffold.\n\n"
                "Requirements:\n"
                "- aim for 2000 characters or less\n"
                f"- hard maximum {MODEL_WRITE_MAX_CHARS}\n"
                "- omit optional sections, detailed copy, comments, decoration "
                "and secondary content\n"
                "- preserve only the minimum structure needed to continue the task\n"
                "- do not complete the application\n"
                "- call write exactly once"
            )},
        ]
        _, _, corrected = attempt(correction_messages, "size-correction")
        if isinstance(corrected, dict) and corrected.get("changed"):
            self.events.emit("bootstrap_size_correction", outcome="succeeded",
                             path=corrected.get("path"))
            self.events.emit("bootstrap_rescue", outcome="succeeded",
                             path=corrected.get("path"), via="size-correction")
            return corrected
        self.events.emit("bootstrap_size_correction", outcome="failed")
        self.events.emit("bootstrap_rescue", outcome="failed",
                         reason="size correction produced no change")
        return None
