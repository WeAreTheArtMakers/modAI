#!/usr/bin/env python3
"""
MODAI Landing-Page Benchmark
=============================
Runs a single landing-page task against a clean temporary workspace,
measures the harness trace, and prints a structured report.

Usage:
    python scripts/benchmark_landing_page.py [--workspace PATH] [--label LABEL]

The workspace defaults to a fresh temp directory.  If --workspace is given
the directory must exist (its contents will be the starting project context).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

# Make sure project root is on sys.path when invoked directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_settings
from modai.core.harness import CodingHarness
from modai.models.ollama import OllamaRuntime
from modai.orchestration.router import TaskRouter

try:
    from ollama import Client
except ImportError:
    print("ERROR: ollama package not installed", file=sys.stderr)
    sys.exit(1)

BENCHMARK_PROMPT = """\
Create a polished, publishable responsive landing page for MODAI.

First inspect only the minimum relevant project sources needed to understand
what MODAI actually is.

Use only real product information from the repository.

Do not invent:
- pricing
- testimonials
- user counts
- customers
- benchmarks
- partnerships
- unsupported product claims

The page should communicate that MODAI is a local coding and agent harness
with an optional multi-agent orchestra, built around local-first development
and Ollama.

Preserve MODAI's terminal/music identity, but do not make the page look like
a generic AI SaaS template.

Use lightweight HTML/CSS/JavaScript unless the existing project already
requires another stack.

Requirements:
- strong hero section
- clear explanation of what MODAI does
- concise architecture/workflow section
- meaningful feature presentation based on real capabilities
- strong typography and spacing
- responsive mobile layout
- accessible semantic HTML
- no unnecessary dependencies
- no fake content

Implement the files directly.

When you believe the page is complete, stop calling tools and return a
concise final summary so the harness can run deterministic verification.\
"""


def resolve_trace_dir(workspace: Path) -> Path:
    """Benchmark instrumentation lives OUTSIDE the evaluated workspace.

    The model-facing project tree must never contain session files, logs,
    or benchmark results (raw bash can see through tool-level hiding).
    """
    return workspace.parent / f"{workspace.name}_trace"


def run_benchmark(workspace: Path, label: str, trace_dir: Path | None = None) -> dict:
    settings = load_settings()

    route = TaskRouter().route(BENCHMARK_PROMPT, settings.harness_mode)

    client = Client(
        host=settings.host,
        trust_env=False,
        timeout=settings.model_timeout_seconds,
    )
    runtime = OllamaRuntime(
        client, settings.model,
        options={
            "num_ctx": settings.context_size,
            "temperature": settings.temperature,
            "top_p": 0.9,
            "top_k": 20,
            "num_predict": settings.model_max_output_tokens,
            "think": settings.think,
        },
        keep_alive=settings.keep_alive,
        stream=settings.stream_output,
    )

    run_dir = trace_dir or resolve_trace_dir(workspace)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    events: list = []
    harness = CodingHarness(
        runtime=runtime,
        workspace=workspace,
        run_dir=run_dir,
        task=BENCHMARK_PROMPT,
        write_allowed=True,
        context_size=settings.context_size,
        compaction_reserve_tokens=settings.compaction_reserve_tokens,
        repair_rounds=settings.repair_rounds,
        max_turns=settings.harness_max_turns,
        model_retries=settings.model_retries,
        delegate_enabled=(route.mode == "orchestra"),
        network_enabled=settings.internet_enabled,
        event=events.append,
    )

    print(f"\n{'='*60}")
    print(f"  MODAI Landing-Page Benchmark  [{label}]")
    print(f"  mode={route.mode}  model={settings.model}")
    print(f"  workspace={workspace}")
    print(f"  trace_dir={run_dir}")
    print(f"{'='*60}\n")

    wall_start = time.monotonic()
    result = harness.run()
    wall_total = time.monotonic() - wall_start

    # ── Trace analysis ─────────────────────────────────────────────────────
    tool_calls_by_name: Counter = Counter()
    reads_by_path: Counter = Counter()
    duplicate_reads = 0
    files_changed: list[str] = []
    verify_count = 0
    repair_rounds = 0
    empty_responses = 0
    no_progress_guards = 0
    transport_retries = 0
    failed_tool_calls = 0
    path_not_found_events = 0
    implementation_phase_reason: str | None = None
    first_mutation_turn: int | None = result.metrics.get("first_mutation_turn")

    for ev in events:
        k = ev.kind
        d = ev.data if hasattr(ev, "data") else {}
        if k == "tool_started":
            name = d.get("name", "")
            tool_calls_by_name[name] += 1
            if name == "read":
                path = d.get("arguments", {}).get("path", "?")
                if reads_by_path[path] > 0:
                    duplicate_reads += 1
                reads_by_path[path] += 1
        elif k == "tool_finished":
            r = d.get("result", {})
            if not d.get("ok", True):
                failed_tool_calls += 1
            if isinstance(r, dict) and r.get("changed"):
                p = r.get("path", "?")
                if p not in files_changed:
                    files_changed.append(p)
            if isinstance(r, dict) and r.get("error_code") == "PATH_NOT_FOUND":
                path_not_found_events += 1
        elif k == "verification_finished":
            verify_count += 1
        elif k == "empty_model_response":
            empty_responses += 1
        elif k == "no_progress":
            no_progress_guards += 1
        elif k == "model_retry":
            transport_retries += 1
        elif k == "implementation_phase_entered":
            implementation_phase_reason = d.get("reason", "?")

    # repair rounds ≈ turns where model returned no tools AND verify failed
    # (approximate: result.metrics doesn't track this directly)
    repair_rounds = max(0, verify_count - 1)  # first verify is the completion check

    total_tool_calls = sum(tool_calls_by_name.values())
    files_read = list(reads_by_path.keys())

    # ── Report ─────────────────────────────────────────────────────────────
    sep = "─" * 60
    verdict = result.verification.get("verdict", "MISSING")
    verdict_color = "\033[32m" if verdict == "PASS" else "\033[31m"
    reset = "\033[0m"

    print(sep)
    print(f"  STATUS              {result.status.upper()}")
    print(f"  MODE                {route.mode}")
    print(f"  MODEL               {settings.model}")
    print(sep)
    print(f"  MODEL CALLS         {result.metrics['model_calls']}")
    print(f"  TOOL CALLS          {total_tool_calls}")
    if tool_calls_by_name:
        for name, count in sorted(tool_calls_by_name.items(), key=lambda x: -x[1]):
            print(f"    {name:<18} {count}")
    print(f"  FIRST MUTATION TURN {first_mutation_turn}")
    print(sep)
    print(f"  FILES READ          {len(files_read)}")
    for p in files_read:
        dup = f"  ×{reads_by_path[p]}" if reads_by_path[p] > 1 else ""
        print(f"    {p}{dup}")
    print(f"  FILES CHANGED       {len(files_changed)}")
    for p in files_changed:
        sz = ""
        try:
            sz = f"  ({(workspace / p).stat().st_size:,} B)"
        except OSError:
            pass
        print(f"    {p}{sz}")
    print(f"  DUPLICATE READS     {duplicate_reads}")
    print(f"  FAILED TOOL CALLS   {failed_tool_calls}")
    print(f"  PATH_NOT_FOUND      {path_not_found_events}")
    print(sep)
    print(f"  PRE-MUTATION TOOLS  {result.metrics.get('pre_mutation_tool_calls', '?')}")
    print(f"  DISCOVERY SUCCESSES {result.metrics.get('discovery_successes', '?')}")
    print(f"  IMPL PHASE          {implementation_phase_reason or 'not entered'}")
    print(f"  TRANSPORT RETRIES   {transport_retries}")
    print(sep)
    print(f"  VERIFICATION CALLS  {verify_count}")
    print(f"  REPAIR ROUNDS       {repair_rounds}")
    print(f"  EMPTY RESPONSES     {empty_responses}")
    print(f"  NO-PROGRESS GUARDS  {no_progress_guards}")
    print(sep)
    local_tok = result.usage.get("local_tokens", result.usage.get("total_tokens", 0))
    cloud_tok = result.usage.get("cloud_tokens", 0)
    print(f"  LOCAL TOKENS        {local_tok:,}")
    print(f"  CLOUD TOKENS        {cloud_tok:,}")
    print(f"  TOTAL TOKENS        {result.usage.get('total_tokens', 0):,}")
    print(f"  WALL SECONDS        {wall_total:.1f}s")
    print(sep)
    print(f"  FINAL VERDICT       {verdict_color}{verdict}{reset}")
    for c in result.verification.get("checks", []):
        icon = "✓" if c["verdict"] == "PASS" else "✗"
        print(f"    {icon} {c['name']}: {c['verdict']}")
        for e in c.get("errors", [])[:3]:
            print(f"        {e}")
    print(sep)

    # Optimization targets (informational, not hard failures)
    print("\n  OPTIMIZATION TARGETS")
    targets = [
        ("model_calls < 10",      result.metrics["model_calls"] < 10),
        ("verify_calls <= 2",     verify_count <= 2),
        ("duplicate_reads == 0",  duplicate_reads == 0),
        ("tokens < 30K",          local_tok < 30_000),
        ("no delegates",          route.mode == "solo"),
    ]
    for label_t, ok in targets:
        icon = "✓" if ok else "✗"
        color = "\033[32m" if ok else "\033[33m"
        print(f"    {color}{icon} {label_t}{reset}")
    print()

    # Machine-readable JSON summary (for CI / script consumption)
    summary = {
        "label": label,
        "status": result.status,
        "mode": route.mode,
        "model": settings.model,
        "model_calls": result.metrics["model_calls"],
        "tool_calls": total_tool_calls,
        "tool_calls_by_name": dict(tool_calls_by_name),
        "first_mutation_turn": first_mutation_turn,
        "files_read": files_read,
        "duplicate_reads": duplicate_reads,
        "failed_tool_calls": failed_tool_calls,
        "path_not_found_count": result.metrics.get(
            "path_not_found_count", path_not_found_events),
        "files_changed": files_changed,
        "pre_mutation_tool_calls": result.metrics.get("pre_mutation_tool_calls"),
        "discovery_successes": result.metrics.get("discovery_successes"),
        "implementation_phase_entered": result.metrics.get(
            "implementation_phase_entered",
            implementation_phase_reason is not None),
        "implementation_phase_reason": result.metrics.get(
            "implementation_phase_reason", implementation_phase_reason),
        "transport_retries": transport_retries,
        "verification_calls": verify_count,
        "repair_rounds": repair_rounds,
        "empty_responses": empty_responses,
        "no_progress_guards": no_progress_guards,
        "local_tokens": local_tok,
        "cloud_tokens": cloud_tok,
        "total_tokens": result.usage.get("total_tokens", 0),
        "wall_seconds": round(wall_total, 1),
        "verdict": verdict,
        "checks": result.verification.get("checks", []),
        "final": result.final[:500],
    }

    json_path = run_dir / "benchmark_result.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"  JSON summary: {json_path}\n")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="MODAI Landing-Page Benchmark")
    parser.add_argument("--workspace", default=None,
                        help="Directory to use as workspace (default: persistent /tmp dir)")
    parser.add_argument("--trace-dir", default=None,
                        help="Directory for session/logs/result (default: <workspace>_trace)")
    parser.add_argument("--label", default="no-skills",
                        help="Label for this run (e.g. 'no-skills', 'with-skills')")
    args = parser.parse_args()

    if args.workspace:
        ws = Path(args.workspace).expanduser().resolve()
        ws.mkdir(parents=True, exist_ok=True)
    else:
        # Persistent (never auto-deleted): the trace must survive for postmortem.
        ws = Path(tempfile.mkdtemp(prefix="modai_bench_"))
        # Copy README and a few key source files into the workspace
        # so the model can read real MODAI context
        repo_root = Path(__file__).resolve().parent.parent
        for name in ("README.md", "THIRD_PARTY_NOTICES.md"):
            src = repo_root / name
            if src.exists():
                (ws / name).write_bytes(src.read_bytes())
    trace_dir = (Path(args.trace_dir).expanduser().resolve()
                 if args.trace_dir else resolve_trace_dir(ws))
    trace_dir.mkdir(parents=True, exist_ok=True)

    summary = run_benchmark(ws, label=args.label, trace_dir=trace_dir)

    session_path = trace_dir / "session.jsonl"
    result_path = trace_dir / "benchmark_result.json"
    print("WORKSPACE:")
    print(f"  {ws}")
    print("TRACE DIRECTORY:")
    print(f"  {trace_dir}")
    print("SESSION:")
    print(f"  {session_path}  (exists={session_path.is_file()})")
    print("RESULT:")
    print(f"  {result_path}  (exists={result_path.is_file()})")
    print(f"  status={summary.get('status')} verdict={summary.get('verdict')}")


if __name__ == "__main__":
    main()
