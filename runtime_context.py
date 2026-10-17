from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path


_default_workspace = (Path(__file__).resolve().parent / "workspace").resolve()
_workspace_context: ContextVar[Path] = ContextVar("modai_workspace", default=_default_workspace)
_internet_context: ContextVar[bool] = ContextVar("modai_internet", default=True)
_privacy_context: ContextVar[str] = ContextVar("modai_privacy", default="guarded")
_model_action_context: ContextVar[bool] = ContextVar("modai_model_action", default=False)


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


def set_privacy_profile(profile: str) -> None:
    _privacy_context.set(profile)


def privacy_profile() -> str:
    return _privacy_context.get()


def model_action_token():
    return _model_action_context.set(True)


def reset_model_action(token) -> None:
    _model_action_context.reset(token)


def is_model_action() -> bool:
    return _model_action_context.get()
