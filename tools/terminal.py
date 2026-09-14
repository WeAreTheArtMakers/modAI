from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Sequence

from runtime_context import get_workspace


ALLOWED_PROGRAMS = {
    "python", "python3", "pytest", "git", "ls", "find", "pwd", "cat", "head", "tail",
    "node", "npm", "pnpm", "yarn", "ruff", "mypy", "cargo", "go",
}
READ_ONLY_GIT_COMMANDS = {"status", "diff", "log", "show", "branch", "rev-parse"}
PACKAGE_COMMANDS = {
    "npm": {"test", "run"},
    "pnpm": {"test", "run", "build", "lint", "typecheck"},
    "yarn": {"test", "run", "build", "lint"},
    "cargo": {"test", "check", "build", "clippy", "fmt"},
    "go": {"test", "vet", "build"},
}
SHELL_TOKENS = {";", "&&", "||", "|", ">", ">>", "<", "`", "$("}
FILE_PROGRAMS = {"ls", "find", "cat", "head", "tail"}


def _arguments(command: Sequence[str] | str) -> list[str]:
    if isinstance(command, str):
        command = shlex.split(command)
    args = [str(part) for part in command]
    if not args:
        raise ValueError("Komut boş olamaz")
    if any(any(token in part for token in SHELL_TOKENS) for part in args):
        raise PermissionError("Shell operatörlerine izin verilmiyor")
    return args


def _inside_workspace(value: str) -> bool:
    workspace = get_workspace()
    candidate = (workspace / value).resolve()
    return candidate == workspace or workspace in candidate.parents


def _validate(args: list[str]) -> None:
    program = Path(args[0]).name
    if program not in ALLOWED_PROGRAMS:
        raise PermissionError(f"Komut güvenlik politikası tarafından engellendi: {program}")
    if program == "git":
        if len(args) < 2 or args[1] not in READ_ONLY_GIT_COMMANDS:
            raise PermissionError("Yalnızca salt-okunur Git komutlarına izin veriliyor")
        if any(not _inside_workspace(part) for part in args[2:] if not part.startswith("-")):
            raise PermissionError("Git argümanları workspace dışına çıkamaz")
    if program in PACKAGE_COMMANDS:
        if len(args) < 2 or args[1] not in PACKAGE_COMMANDS[program]:
            raise PermissionError(f"İzin verilmeyen {program} alt komutu")
    if program in FILE_PROGRAMS:
        for part in args[1:]:
            if part.startswith("-") or part.isdigit():
                continue
            if not _inside_workspace(part):
                raise PermissionError("Komut argümanları workspace dışına çıkamaz")
    if program in {"python", "python3", "node"}:
        if len(args) < 2 or args[1].startswith("-") or not _inside_workspace(args[1]):
            raise PermissionError(f"{program} yalnızca workspace içindeki bir betiği çalıştırabilir")


def run(command: Sequence[str] | str, timeout: int = 120) -> str:
    args = _arguments(command)
    _validate(args)
    timeout = max(1, min(int(timeout), 900))
    try:
        process = subprocess.run(
            args, shell=False, cwd=get_workspace(), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return f"timeout={timeout}s\n{(exc.stdout or '')}{(exc.stderr or '')}"[:30000]
    output = (process.stdout + "\n" + process.stderr).strip()
    return f"exit_code={process.returncode}\n{output[:30000]}"
