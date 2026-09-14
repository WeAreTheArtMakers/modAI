# Migrating from MODAI 4.x Orchestrator

MODAI 5.0 changes the default engine, not the `modai` habit. Running `modai` in a project, passing a prompt, selecting a model, choosing a workspace, listing runs, and resuming by run ID remain supported.

## What changes by default

| 4.x | 5.x default |
|---|---|
| Planner builds a persona sequence | Deterministic router starts one coder |
| Coder context is recreated by role/task | One conversation persists through repair |
| Debate/reviewer prose precedes artifacts | Deterministic gates run after artifacts |
| Many broad tools | Small coding tool surface |
| SCORE represents persona steps | Progress represents files and current gates |
| Text JSON tool fallback is common | Native tool calls are primary |

Normal coding should use `--mode auto` or `--mode solo`. Use `--mode orchestra` only when bounded independent evidence is useful.

## Preserving a 4.x workflow

```bash
modai --full-orchestra "your task"
```

This activates the legacy planner/debate/reviewer pipeline. Historical runs without `engine: coding-harness` continue through the legacy resume code.

## Tool-call compatibility

Persisted calls named `write_file`, `read_file`, `list_files`, `make_directory`, and `replace_in_file` are translated to the new tool layer. New model schemas expose `write`, `read`, `ls`, and `edit`.

Planning, product, UX, project, operations, growth, and integrator roles are read-only by default. The coder remains write-capable. This can expose old prompts that incorrectly expected a reviewer or product role to edit files; route that work to the coder instead.

## Configuration

Existing configuration keys remain accepted. Recommended additions:

```json
{
  "harness_mode": "auto",
  "harness_max_turns": 80,
  "compaction_reserve_tokens": 2048,
  "repair_rounds": 4
}
```

`max_total_tokens` remains the stored compatibility name for the cloud token budget. It never caps local Ollama tokens. `debate_rounds`, `max_agents`, `max_tool_rounds`, `agent_retries`, `execution_mode`, and `max_parallel_agents` primarily affect `--full-orchestra`.

## Run files

New run directories contain:

```text
state.json        current index/UI projection
session.jsonl     append-only messages and events
logs/             full command outputs
delegate-logs/    bounded delegate command outputs, when enabled
```

Inspect and compact them with:

```bash
modai --session RUN_ID
modai --compact RUN_ID
modai --resume RUN_ID
```

Compaction appends a record; it does not erase the historical transcript.

## Suggested rollout

1. Keep your current `config.json`; add the four harness keys when convenient.
2. Run `.venv/bin/python -m pytest -q` in the MODAI repository.
3. Try one small project in `--mode solo`.
4. Inspect `state.json`, `session.jsonl`, target diffs, and gate artifacts.
5. Use `--full-orchestra` only for a workflow that genuinely requires the older engine.
