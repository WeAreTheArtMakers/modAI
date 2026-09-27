from __future__ import annotations

import re
from .registry import SkillRegistry


class SkillRouter:
    """Cheap bilingual first pass; no model call and no skill body reads."""
    def select(self, task: str, registry: SkillRegistry, limit: int = 2) -> list[str]:
        text = task.casefold()
        selected: list[str] = []
        def add(*names: str) -> None:
            selected.extend(n for n in names if n not in selected and n in registry.skills)
        research = bool(re.search(r'research|araştır|current|güncel|fees|funding|\boi\b', text))
        web3 = bool(re.search(r'ethereum|\bl2\b|web3|smart contract|solidity|wallet|akıllı sözleşme', text))
        finance = bool(re.search(r'\bbtc\b|funding|\boi\b|finance|financial|finans|market data', text))
        frontend = bool(re.search(r'landing|landpage|homepage|hero|responsive|frontend|web sitesi|web sayfa', text))
        debugging = bool(re.search(r'traceback|debug|\bbug\b|\bfix\b|düzelt|hata', text))
        if finance and research:
            add('finance-research', 'web-research')
        elif web3:
            add('web3-engineering', 'web-research' if research else 'frontend-engineering' if frontend else 'security-review')
        elif frontend:
            add('landing-page-design', 'frontend-engineering')
        elif debugging:
            add('repo-debugging')
            if 'python' in text or 'traceback' in text:
                add('python-engineering')
        elif research:
            add('web-research')
        elif re.search(r'accessibility|erişilebilir|wcag', text):
            add('accessibility')
        elif re.search(r'security review|güvenlik incele|security audit', text):
            add('security-review')
        elif 'python' in text:
            add('python-engineering')
        return selected[:max(0, min(3, limit))]
