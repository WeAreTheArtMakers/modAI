from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Capabilities:
    read: bool = True
    write: bool = False
    test: bool = True
    network: bool = False
    delegate: bool = False


DESTRUCTIVE = {"rm", "rmdir", "mkfs", "shutdown", "reboot", "dd"}
MUTATING_GIT = {"commit", "push", "reset", "checkout", "switch", "merge", "rebase", "clean", "restore"}
SAFE_COMMANDS = {
    "python", "python3", "pytest", "node", "npm", "npx", "pnpm", "yarn", "bun",
    "go", "cargo", "swift", "make", "cmake", "rg", "grep", "find", "ls", "pwd",
    "cat", "head", "tail", "wc", "git",
}


class ToolPolicy:
    def __init__(self, capabilities: Capabilities) -> None:
        self.capabilities = capabilities

    def allows(self, tool: str) -> bool:
        if tool in {"edit", "write"}:
            return self.capabilities.write
        if tool == "delegate":
            return self.capabilities.delegate
        if tool in {"web_search", "fetch_url"}:
            return self.capabilities.network
        return self.capabilities.read

    def validate_command(self, argv: list[str]) -> None:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise PermissionError("bash requires a non-empty argument array")
        if argv[0] not in SAFE_COMMANDS or argv[0] in DESTRUCTIVE:
            raise PermissionError(f"command is not allowlisted: {argv[0]}")
        if any(token in {";", "&&", "||", "|", ">", ">>", "<", "`"} for token in argv):
            raise PermissionError("shell operators are not accepted; pass an argument array")
        if argv[0] == "git" and len(argv) > 1 and argv[1] in MUTATING_GIT:
            raise PermissionError(f"mutating git command is disabled: {argv[1]}")
        if argv[0] in {"npm", "pnpm", "yarn", "bun"} and len(argv) > 1 and argv[1] in {
            "install", "add", "remove", "uninstall", "publish", "link", "unlink",
        }:
            raise PermissionError("package mutation requires a separately approved workflow")
        if argv[0] in {"python", "python3", "node"} and any(item in argv[1:] for item in {"-c", "-e", "--eval"}):
            raise PermissionError("inline executable code is disabled; run a project file or module")
        if argv[0] in {"python", "python3"} and len(argv) > 3 and argv[1:3] == ["-m", "pip"] and argv[3] in {"install", "uninstall"}:
            raise PermissionError("package mutation requires a separately approved workflow")
        if not self.capabilities.test and argv[0] not in {"rg", "grep", "find", "ls", "pwd", "cat", "head", "tail", "wc", "git"}:
            raise PermissionError("test/build commands are disabled for this role")
