"""Small, rebuildable task index. JSONL remains the authoritative transcript."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modai.security import redact, sensitive_path


STAGES = (
    ("research", "Researcher", "read-only", ()),
    ("code", "Code Virtuoso", "writer", ("research",)),
    ("verify", "Verification Worker", "read-only", ("code",)),
    ("review", "Reviewer", "read-only", ("verify",)),
    ("repair", "Code Virtuoso", "writer", ("review",)),
    ("final_verify", "Verification Worker", "read-only", ("review",)),
)


class RunIndex:
    def __init__(self, run_dir: Path, workspace: Path) -> None:
        self.run_dir = run_dir
        self.workspace = workspace.resolve()
        run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            run_dir.chmod(0o700)
        path = run_dir / "tasks.sqlite3"
        if path.is_symlink():
            raise PermissionError("task index must not be a symbolic link")
        if not path.exists():
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        elif os.name == "posix":
            path.chmod(0o600)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY, agent TEXT NOT NULL, permission TEXT NOT NULL,
                dependencies TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                summary TEXT NOT NULL DEFAULT '', evidence_hash TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS artifacts(
                path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, task_id TEXT NOT NULL,
                updated_at TEXT NOT NULL, FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
            CREATE TABLE IF NOT EXISTS checkpoints(
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                verdict TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(id)
            );
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('schema_version','1')")
            for stage, agent, permission, deps in STAGES:
                self.db.execute("INSERT OR IGNORE INTO tasks(id,agent,permission,dependencies) VALUES(?,?,?,?)",
                                (stage, agent, permission, json.dumps(deps)))

    def close(self) -> None:
        self.db.close()

    def state(self, stage: str) -> str:
        row = self.db.execute("SELECT state FROM tasks WHERE id=?", (stage,)).fetchone()
        if row is None:
            raise KeyError(stage)
        return str(row[0])

    def summary(self, stage: str) -> str:
        row = self.db.execute("SELECT summary FROM tasks WHERE id=?", (stage,)).fetchone()
        if row is None:
            raise KeyError(stage)
        return str(row[0])

    def start(self, stage: str) -> None:
        if self.state(stage) == "completed":
            return
        with self.db:
            self.db.execute("UPDATE tasks SET state='running', attempts=attempts+1, updated_at=? WHERE id=?",
                            (_now(), stage))

    def finish(self, stage: str, state: str, summary: str = "", evidence: str = "") -> None:
        if state not in {"completed", "needs_attention", "paused", "skipped"}:
            raise ValueError("invalid task state")
        short = redact(summary)[:1200]
        digest = (evidence if len(evidence) == 64 and all(c in "0123456789abcdef" for c in evidence)
                  else hashlib.sha256(evidence.encode("utf-8")).hexdigest() if evidence else None)
        with self.db:
            self.db.execute("UPDATE tasks SET state=?, summary=?, evidence_hash=?, updated_at=? WHERE id=?",
                            (state, short, digest, _now(), stage))

    def checkpoint(self, stage: str, verdict: str, summary: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO checkpoints(task_id,verdict,summary,created_at) VALUES(?,?,?,?)",
                            (stage, verdict, redact(summary)[:1200], _now()))

    def record_artifacts(self, paths: list[str], stage: str = "code") -> dict[str, str]:
        hashes: dict[str, str] = {}
        with self.db:
            for name in paths:
                path = (self.workspace / name).resolve()
                if sensitive_path(path, self.workspace) or not path.is_file() or path.stat().st_size > 5_000_000:
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                relative = str(path.relative_to(self.workspace))
                hashes[relative] = digest
                self.db.execute("INSERT INTO artifacts(path,sha256,task_id,updated_at) VALUES(?,?,?,?) "
                                "ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256, "
                                "task_id=excluded.task_id,updated_at=excluded.updated_at",
                                (relative, digest, stage, _now()))
        return hashes

    def recover(self, records: list[dict[str, Any]]) -> None:
        """Rebuild the disposable index from authoritative JSONL stage records."""
        with self.db:
            self.db.execute("DELETE FROM artifacts")
            self.db.execute("DELETE FROM checkpoints")
            self.db.execute("UPDATE tasks SET state='pending', summary='', evidence_hash=NULL")
        for record in records:
            if record.get("type") == "orchestra_stage" and record.get("stage") in {s[0] for s in STAGES}:
                state = record.get("state")
                if state in {"completed", "needs_attention", "paused", "skipped"}:
                    self.finish(str(record["stage"]), str(state), str(record.get("summary", "")),
                                str(record.get("evidence_hash", "")))
                    artifact = record.get("artifact")
                    if not isinstance(artifact, dict):
                        continue
                    if state == "completed" and record["stage"] in {"code", "repair"}:
                        hashes = artifact.get("hashes", {})
                        if isinstance(hashes, dict):
                            with self.db:
                                for name, digest in hashes.items():
                                    if (isinstance(name, str) and isinstance(digest, str) and len(digest) == 64
                                            and all(c in "0123456789abcdef" for c in digest)
                                            and not sensitive_path(self.workspace / name, self.workspace)):
                                        self.db.execute(
                                            "INSERT INTO artifacts(path,sha256,task_id,updated_at) VALUES(?,?,?,?) "
                                            "ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,"
                                            "task_id=excluded.task_id,updated_at=excluded.updated_at",
                                            (name, digest, record["stage"], _now()))
                    if record["stage"] in {"verify", "final_verify"} and artifact.get("verdict"):
                        self.checkpoint(str(record["stage"]), str(artifact["verdict"]),
                                        str(record.get("summary", "")))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
