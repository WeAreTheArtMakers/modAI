from __future__ import annotations

import re
from dataclasses import dataclass, field


FILE = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:html?|css|m?js|cjs|jsx|tsx|py|json|md|svg|png|jpe?g|webp|ico|toml|ya?ml))(?![\w.-])", re.I)


@dataclass(slots=True)
class ArtifactContract:
    files: list[str] = field(default_factory=list)
    static_site: bool = False
    browser_quality: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"files": self.files, "static_site": self.static_site,
                "browser_quality": self.browser_quality}


def infer_contract(task: str) -> ArtifactContract:
    folded = task.casefold()
    files = sorted({match.group(1).lstrip("./") for match in FILE.finditer(task)})
    static = any(marker in folded for marker in (
        "landing page", "landpage", "website", "web sitesi", "web sayfas", "static site",
        "statik site", "responsive", "index.html",
    ))
    if static and not any(path.endswith((".html", ".htm")) for path in files):
        files.insert(0, "index.html")
    return ArtifactContract(files, static, static)
