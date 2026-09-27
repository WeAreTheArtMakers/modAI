"""Pure tool-surface and result decisions, independently regression tested."""
from typing import Any


def successful_result(result: Any) -> bool:
    return not (isinstance(result, dict) and
                (result.get('error') or result.get('error_code') or result.get('exit_code', 0) != 0))


def select_tools(*, repair: bool, structural: bool, force_write: bool,
                 mutated: bool, bash_disabled: bool, available: set[str],
                 fast_bootstrap: bool = False) -> set[str] | None:
    if repair:
        names = {'read', 'grep', 'edit'} | ({'write'} if structural else set())
    elif force_write and not mutated:
        names = {'write'}
    elif fast_bootstrap and not mutated:
        names = {'read', 'ls', 'write', 'load_skill'}
    else:
        names = None
    if bash_disabled:
        names = (available if names is None else names) - {'bash'}
    return names
