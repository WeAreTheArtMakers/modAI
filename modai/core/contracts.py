from __future__ import annotations

import re
import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from modai.security import redact


FILE = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:html?|css|m?js|cjs|jsx|tsx|py|json|md|svg|png|jpe?g|webp|ico|toml|ya?ml))(?![\w.-])", re.I)


@dataclass(slots=True)
class ArtifactContract:
    files: list[str] = field(default_factory=list)
    static_site: bool = False
    browser_quality: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"files": self.files, "static_site": self.static_site,
                "browser_quality": self.browser_quality}


@dataclass(slots=True)
class AcceptanceRequirement:
    id: str
    source: str
    statement: str
    count: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {"id": self.id, "source": self.source, "statement": self.statement,
                "count": self.count}


@dataclass(slots=True)
class AcceptanceContract:
    requirements: list[AcceptanceRequirement] = field(default_factory=list)
    source_hash: str = ""

    def as_dict(self) -> dict[str, object]:
        return {"requirements": [item.as_dict() for item in self.requirements],
                "source_hash": self.source_hash}


_BUILD = re.compile(r"\b(?:build|create|implement|make|fix|repair|develop|write|oluştur|yap|uygula|düzelt|geliştir|yaz)\w*\b", re.I)
_README = re.compile(r"(?<![\w/])README\.md\b", re.I)
_SPECS: tuple[tuple[str, str], ...] = (
    ("semantic_html", r"semantic\s+html|semantik\s+html"),
    ("navigation", r"\bnavigat(?:ion|e)\b|\bnav\b|gezinme|menü"),
    ("hero", r"\bhero\b|kahraman\s+bölüm"),
    ("feature_cards", r"feature\s+cards?|özellik\s+kartlar[ıi]?"),
    ("cta", r"\bCTA\b|call.to.action|eylem\s+çağrıs[ıi]"),
    ("internal_css", r"internal\s+CSS|inline\s+CSS|dahili\s+CSS|iç\s+CSS"),
    ("no_external_assets", r"no\s+external\s+assets?|without\s+external\s+assets?|harici\s+(?:varlık|asset|kaynak)\s+(?:yok|kullanma)"),
    ("responsive", r"responsive|duyarlı\s+tasarım|mobil\s+uyumlu"),
    ("index_html", r"\bindex\.html\b"),
)


def acceptance_contract(task: str, workspace: Path | None = None) -> AcceptanceContract:
    """Extract only supported, testable requirements from an explicit task/source.

    README is untrusted task data, never policy. No arbitrary instructions or
    executable test commands are imported from it.
    """
    sources = [("task", task[:6000])]
    if workspace is not None and _README.search(task) and _BUILD.search(task):
        candidate = workspace / "README.md"
        try:
            if not candidate.is_symlink():
                descriptor = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                try:
                    metadata = os.fstat(descriptor)
                    if stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 65536:
                        sources.append(("README.md", os.read(descriptor, 16000).decode("utf-8", errors="replace")))
                finally:
                    os.close(descriptor)
        except (OSError, UnicodeError):
            pass
    found: dict[str, AcceptanceRequirement] = {}
    for source, content in sources:
        for line in content.splitlines()[:100]:
            statement = line.strip().lstrip("-*># ")[:240]
            if not statement:
                continue
            for identifier, expression in _SPECS:
                match_requirement = re.search(expression, statement, re.I)
                if identifier in found or match_requirement is None:
                    continue
                if identifier != "no_external_assets":
                    before = statement[max(0, match_requirement.start() - 45):match_requirement.start()]
                    after = statement[match_requirement.end():match_requirement.end() + 28]
                    if (re.search(r"(?:do not|don't|avoid|without|no|ekleme|kullanma)\s+(?:\w+\s+){0,3}$", before, re.I)
                            or re.search(r"\b(?:is not required|optional|gerekli değil)\b", after, re.I)):
                        continue
                count = None
                if identifier == "feature_cards":
                    match = re.search(r"\b(\d{1,2}|one|two|three|four|bir|iki|üç|dört)\s+(?:\w+\s+){0,2}(?:feature\s+cards?|özellik\s+kartlar[ıi]?)", statement, re.I)
                    if match:
                        count = {"one": 1, "two": 2, "three": 3, "four": 4,
                                 "bir": 1, "iki": 2, "üç": 3, "dört": 4}.get(match.group(1).casefold())
                        if count is None and match.group(1).isdigit():
                            count = int(match.group(1))
                found[identifier] = AcceptanceRequirement(identifier, source, redact(statement), count)
    # A generic mention of README is not an instruction to implement its entire content.
    if not _BUILD.search(task):
        found = {key: value for key, value in found.items() if value.source == "task"}
    requirements = list(found.values())
    digest = hashlib.sha256(json.dumps(
        [(item.id, item.source, item.statement, item.count) for item in requirements],
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return AcceptanceContract(requirements, digest)


def infer_contract(task: str, workspace: Path | None = None) -> ArtifactContract:
    folded = task.casefold()
    files = sorted({match.group(1).lstrip("./") for match in FILE.finditer(task)})
    static = any(marker in folded for marker in (
        "landing page", "landpage", "website", "web sitesi", "web sayfas", "static site",
        "statik site", "responsive", "index.html",
    ))
    if static and not any(path.endswith((".html", ".htm")) for path in files):
        files.insert(0, "index.html")
    if workspace is not None:
        acceptance = acceptance_contract(task, workspace)
        if any(item.id in {"index_html", "semantic_html", "navigation", "hero", "feature_cards", "cta", "internal_css", "responsive"}
               and item.source == "README.md" for item in acceptance.requirements):
            static = True
            if "index.html" not in files:
                files.insert(0, "index.html")
    return ArtifactContract(files, static, static)
