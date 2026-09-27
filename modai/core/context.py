from __future__ import annotations

import json
from typing import Any


def estimated_tokens(messages: list[dict[str, Any]]) -> int:
    return max(1, len(json.dumps(messages, ensure_ascii=False)) // 4)


class ContextManager:
    def __init__(self, max_tokens: int, reserve_tokens: int = 2048) -> None:
        self.max_tokens = max_tokens
        self.reserve_tokens = min(reserve_tokens, max_tokens // 2)

    def needs_compaction(self, messages: list[dict[str, Any]]) -> bool:
        return estimated_tokens(messages) > self.max_tokens - self.reserve_tokens

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deterministically retain objective, latest summary, and complete tool pairs."""
        system = [item for item in messages if item.get("role") == "system"
                  and not str(item.get('content', '')).startswith('Earlier transcript was compacted.')]
        objective = [item for item in messages if item.get("role") == "user"][:1]
        tail = messages[-12:]
        # Never retain an orphan tool result or an assistant tool call without its result.
        call_ids = {str(call.get("id")) for item in tail for call in item.get("tool_calls", [])
                    if isinstance(call, dict)}
        result_ids = {str(item.get("tool_call_id")) for item in tail if item.get("role") == "tool"}
        paired = call_ids & result_ids
        clean: list[dict[str, Any]] = []
        for item in tail:
            if item.get("role") == "tool" and str(item.get("tool_call_id")) not in paired:
                continue
            if item.get("tool_calls"):
                kept = [call for call in item["tool_calls"] if str(call.get("id")) in paired]
                if not kept and not item.get("content"):
                    continue
                item = {**item, "tool_calls": kept}
            clean.append(item)
        summary = {"role": "system", "content": (
            "Earlier transcript was compacted. Preserve the original objective and acceptance criteria. "
            "Continue from the current repository state; inspect files before editing and resolve the latest validation evidence."
        )}
        # Keep system policy, project context and skill bodies. Evict a tool
        # call and ALL of its results together, never individual messages.
        clean = [m for m in clean if m not in system and m not in objective]
        groups: list[list[dict[str, Any]]] = []
        for item in clean:
            if item.get('role') == 'tool' and groups and groups[-1][0].get('tool_calls'):
                groups[-1].append(item)
            else:
                groups.append([item])
        fixed = system + objective + [summary]
        while groups and estimated_tokens(fixed + [m for g in groups for m in g]) > self.max_tokens - self.reserve_tokens:
            if len(groups) == 1 and groups[0][0].get('role') == 'user':
                groups[0][0] = {**groups[0][0], 'content': str(groups[0][0].get('content', ''))[:2400]}
                break
            groups.pop(0)
        compacted = fixed + [m for g in groups for m in g]
        return compacted
