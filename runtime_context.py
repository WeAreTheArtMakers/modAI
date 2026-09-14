from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path


_default_workspace = (Path(__file__).resolve().parent / "workspace").resolve()
_workspace_context: ContextVar[Path] = ContextVar("modai_workspace", default=_default_workspace)
_internet_context: ContextVar[bool] = ContextVar("modai_internet", default=True)


def set_workspace(path: str | Path, create: bool = False) -> Path:
    target = Path(path).expanduser().resolve()
    if create:
        target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        raise ValueError(f"Çalışma klasörü bulunamadı: {target}")
    _workspace_context.set(target)
    return target


def get_workspace() -> Path:
    return _workspace_context.get()


def set_internet_enabled(enabled: bool) -> None:
    _internet_context.set(bool(enabled))


def internet_enabled() -> bool:
    return _internet_context.get()
