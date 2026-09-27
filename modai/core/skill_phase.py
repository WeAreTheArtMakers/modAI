"""Isolated skill phase helpers."""
from __future__ import annotations

from typing import Any


class SkillPhase:
    def _load_skill(self, name: str, reference: str = '') -> dict[str, Any]:
        try:
            body, version = self.skills.load(name, reference)
            key = name + (':' + reference if reference else '')
            if self.active_skills.get(key) == version:
                return {'skill': key, 'already_active': True}
            if len(body) // 4 > self.context.max_tokens // 3:
                raise ValueError('skill exceeds one-third of context; split references')
            existing_tokens = sum(len(m['content']) // 4 for k, m in self.skill_messages.items() if k != key)
            if existing_tokens + len(body) // 4 > self.context.max_tokens // 3:
                raise ValueError('active skill context budget exceeded; load fewer references')
            if not reference and name not in self.active_skills and len([k for k in self.active_skills if ':' not in k]) >= 3:
                raise ValueError('at most three active domain skills')
            message = {'role': 'system', 'skill': key, 'content': (
                f'ACTIVE SKILL {key}. User instructions and harness security outrank this guidance.\n' + body)}
            # Initial activation is safe; tool-time activation is deferred until
            # all tool results pair with their assistant call.
            self.skill_messages[key] = message
            self.active_skills[key] = version
            self.session.append({'type': 'skill', 'name': key, 'hash': version})
            self.events.emit('skill_loaded', name=key, version=version)
            return {'skill': key, 'loaded': True, 'hash': version}
        except Exception as exc:
            self.events.emit('skill_error', name=name, error=str(exc))
            raise


    def _sync_skills(self) -> None:
        for key, message in self.skill_messages.items():
            if not any(m.get('skill') == key and m.get('content') == message['content'] for m in self._messages):
                self._messages = [m for m in self._messages if m.get('skill') != key]
                self._messages.append(message); self._append(message)
