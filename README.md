# MODAI — Local Coding & Agent Harness

```text
███╗   ███╗ ██████╗ ██████╗  █████╗ ██╗
████╗ ████║██╔═══██╗██╔══██╗██╔══██╗██║
██╔████╔██║██║   ██║██║  ██║███████║██║
██║╚██╔╝██║██║   ██║██║  ██║██╔══██║██║
██║ ╚═╝ ██║╚██████╔╝██████╔╝██║  ██║██║
╚═╝     ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝
              LOCAL CODING & AGENT HARNESS
```

**One prompt. One persistent coder. An orchestra only when the work earns it.**

MODAI turns a local Ollama model into a practical coding harness that inspects the real project, edits files atomically, runs deterministic quality gates, repairs current failures in the same session, and resumes from an append-only transcript. It is designed for Apple Silicon laptops, stays local by default, and keeps the older multi-agent orchestra behind an explicit compatibility mode.

Version 5.0 replaces persona-heavy planning for ordinary software tasks with a persistent **Code Virtuoso** session. The useful musical metaphor remains in the interface; progress is now measured by artifacts, passing gates, and verified fixes—not by how many agents spoke.

[Product site](https://wearetheartmakers.github.io/modAI/) · [We Are The Art Makers](https://wearetheartmakers.com) · [Architecture](docs/HARNESS_ARCHITECTURE.md) · [4.x migration](docs/MIGRATION_FROM_ORCHESTRATOR.md)

## Why MODAI

- Local-first: project files and model prompts go to the local Ollama endpoint by default.
- Persistent: one coding conversation survives read → edit → test → repair cycles.
- Productive: `auto` routes normal code, bug, test, and website work directly to one coder.
- Exact: a first-class atomic `edit` tool rejects missing, ambiguous, or overlapping replacements before touching disk.
- Verifiable: project-aware tests and a real Playwright browser gate run outside the model.
- Resumable: messages, tool calls, usage, events, and verification reports are appended to `session.jsonl`.
- Controllable: steering, follow-up, abort, manual compaction, read-only mode, and explicit orchestra mode.
- Cost-safe: local tokens are metered for visibility but never limited. A budget applies only to an explicitly enabled paid cloud provider.

## Quick start on macOS

Requirements: macOS on Apple Silicon or Intel, Python 3.11+, [Ollama](https://ollama.com), and about 8 GB of free disk for the recommended M1 Pro model.

```bash
git clone https://github.com/WeAreTheArtMakers/modAI.git
cd modAI
./setup.sh
```

The installer creates the virtual environment, installs Chromium for visual tests, prepares the local model, and installs the `modai` command. Open any project directory and run:

```bash
cd /path/to/your/project
modai
```

Or start immediately with one prompt:

```bash
modai "Fix the failing tests, implement the smallest correct change, and verify it"
```

The current directory is the workspace unless `--workspace` is supplied. MODAI never needs to copy the project into its own repository.

## The default working loop

```text
prompt → deterministic route → persistent Code Virtuoso
       → inspect → precise edit/write → focused test
       → project verification → exact repair feedback
       → PASS or resumable needs_attention
```

There is no planner call or debate round on the normal software path. If a model rereads without changing evidence, the no-progress guard asks for a concrete smallest edit. If a response is truncated while it contains tool calls, none of those calls are executed.

## Modes

```bash
modai --mode auto "task"       # default; strongly favors the solo coder
modai --mode solo "task"       # always one persistent coding session
modai --mode orchestra "task"  # enables bounded read-only delegation
modai --full-orchestra "task"  # legacy 4.x planner/persona engine
```

`orchestra` does not give every specialist write access. The main Code Virtuoso is the mutator. Delegates are bounded and read-only. `--full-orchestra` exists for saved workflows that deliberately depend on the older plan/debate/reviewer sequence.

## Coding tools

The 5.x model-facing surface is intentionally small:

| Tool | Purpose | Safety |
|---|---|---|
| `read` | Read a targeted, numbered line range | Bounded output |
| `grep` | Search project text with ripgrep | Bounded matches |
| `find` | Find paths by glob | Workspace confined |
| `ls` | Show a shallow project tree | Ignores generated/vendor trees |
| `edit` | Apply exact replacements | Unique, non-overlapping, atomic |
| `write` | Create or replace a text file | Atomic replacement |
| `bash` | Run test/build/read commands | Argument array; no shell interpolation |
| `git` | Inspect status/diff/history | Mutating subcommands rejected |
| `web_search` | Search public evidence | Network toggle and bounded results |
| `fetch_url` | Read one public source | HTTP(S), SSRF protection, bounded text |
| `delegate` | Gather independent evidence | Explicit orchestra mode; read-only and bounded |

Full command output is written under the run’s `logs/` directory. The model sees a compact result so a verbose build cannot consume the whole context window.

## Sessions and control

Every 5.x run has a `state.json` summary and an append-only `session.jsonl` transcript under `memory/runs/<RUN_ID>/`.

```bash
modai --list-runs
modai --session RUN_ID
modai --resume RUN_ID
modai --compact RUN_ID
modai --inspect-run RUN_ID
```

Inside the command screen:

```text
/new TASK                start a new persistent coding session
/session [RUN_ID]        show status, usage, files, and latest gates
/resume [RUN_ID]         continue the same conversation and repository state
/compact [RUN_ID]        preserve objective/recent tool pairs in a smaller context
/runs                    list recent sessions
```

The internal session API also supports FIFO `steer(...)`, FIFO `follow_up(...)`, and `abort()` controls. They are consumed only at safe model-turn boundaries—never halfway through a filesystem mutation.

## Command reference

### Task and workspace

```bash
modai "TASK"
modai --workspace /absolute/project/path "TASK"
modai --read-only "Review this repository and report defects"
modai --allow-write --resume RUN_ID
```

### Model and context

```bash
modai --list-models
modai --recommend-model
modai --model qwen3.5:9b "TASK"
modai --num-ctx 8192 "TASK"
modai --num-ctx 16384 "TASK"
```

For an M1 Pro with 16 GB unified memory, begin with the project’s recommended 9B-class Qwen coding model at `num_ctx=8192`. Use `16384` only when a repository truly needs the larger live context; it reduces generation speed and available memory. MODAI’s compaction and targeted reads are designed to make 8192 useful.

### Harness and repair

```bash
modai --mode auto "TASK"
modai --mode solo "TASK"
modai --mode orchestra "TASK"
modai --repair-rounds 4 "TASK"
modai --max-tool-rounds 12 "TASK"       # legacy compatibility setting
modai --max-hours 24 "TASK"             # legacy engine active-time guard
```

### Network and cloud

```bash
modai --no-internet "TASK"
modai --allow-cloud "Public research task"
```

Cloud is off by default. Configure it interactively with `/cloud setup`, then opt in per task with `--allow-cloud` or `/hybrid TASK`. In orchestra mode, only the bounded delegate can use that cloud runtime; the persistent writer remains local. Prompts containing obvious secrets disable cloud routing. The cloud token budget is a paid-provider cost guard only:

```bash
modai --cloud-token-budget 1000000 --allow-cloud "TASK"
```

Local Ollama usage has no token ceiling. When a cloud budget is reached, MODAI asks whether to add more tokens or pause; it does not pretend the unfinished task completed.

### Interface and diagnostics

```bash
modai --language tr
modai --language en
modai --verbose "TASK"
modai --no-color
modai --version
```

## Command-screen reference

```text
/help                    command help
/menu                    return to the arrow-key home screen
/model MODEL             select the local model
/workspace PATH          select the project directory
/internet on|off         toggle research network tools
/profile fast|balanced|deep|marathon
/set num_ctx 16384
/set temperature 0.2
/set repair_rounds 4
/set cloud_token_budget 1000000
/cloud setup|off
/hybrid TASK
/language tr|en
/agents                  show the legacy specialist catalog
/clear
/exit
```

Profiles mainly affect the legacy orchestra. The 5.x harness deliberately avoids manufacturing more work for a simple task.

## Quality gates

MODAI extracts an artifact contract from explicit filenames in the prompt. A task naming `index.html`, `styles.css`, and `app.js` cannot complete while one is missing or empty.

For static sites it also runs:

- local asset reference checks;
- HTML structure, viewport, duplicate IDs, image `alt`, CSS brace, and JavaScript syntax checks;
- Playwright Chromium at mobile, landscape, tablet, and desktop sizes;
- horizontal overflow, visible content, broken anchors/local navigation, console errors, runtime exceptions, and menu-toggle checks;
- screenshots under the target site’s `.modai/browser/` directory.

For detected Python and Node projects it runs available pytest and package scripts (`test`, `lint`, `build`) with bounded logs. A failed gate is injected back into the same coding conversation as exact current evidence.

## Privacy and permissions

- The default endpoint is `127.0.0.1`; remote Ollama hosts are rejected by configuration validation.
- Paths are resolved inside the selected workspace.
- Shell strings are not evaluated. `bash` receives an argument array.
- Destructive commands and mutating Git operations are denied.
- Read-only sessions do not advertise `write` or `edit` schemas.
- Product, UX, project, operations, growth, and integrator roles are read-only in legacy mode; the coder is the default mutator.
- Paid cloud access requires provider setup and explicit per-task consent.

Review changes before committing them. MODAI intentionally does not commit or push the target project for the model.

## Configuration

`config.example.json` documents all supported values. Harness-focused defaults:

```json
{
  "model": "mod-agent:latest",
  "workspace": ".",
  "context_size": 8192,
  "temperature": 0.25,
  "harness_mode": "auto",
  "harness_max_turns": 80,
  "compaction_reserve_tokens": 2048,
  "repair_rounds": 4,
  "cloud_enabled": false,
  "max_total_tokens": 500000
}
```

Older keys remain readable. `max_total_tokens` is retained as the storage/CLI compatibility name for the **cloud-only** budget. See [Migration from Orchestrator](docs/MIGRATION_FROM_ORCHESTRATOR.md).

## Development and verification

```bash
./setup.sh
.venv/bin/python -m pytest -q
```

The deterministic suite uses a scripted fake runtime and covers the persistent loop, native tools, atomic edits, truncated responses, no-progress recovery, resume, compaction, queues, permissions, routing, latest validation evidence, a real landing-page browser E2E fixture, a repair fixture, and legacy orchestra regression.

Run the optional local-model benchmark:

```bash
.venv/bin/python tests/benchmark_local.py \
  --task "Create a responsive static landing page and verify it"
```

Useful measurements are wall-clock time, model calls before first mutation, total calls, files changed, gate sequence, input/output tokens, and verified artifacts per 10k tokens.

## Architecture reference

The persistent loop and session boundaries were designed after studying the MIT-licensed [`earendil-works/pi`](https://github.com/earendil-works/pi) agent and coding-agent packages. MODAI is an independent Python/Ollama implementation, not a port. It adopts the architectural lessons—stable loop, safe steering boundaries, complete tool pairs, append-only sessions, bounded outputs—and preserves MODAI’s local-first, bilingual, terminal-native product identity.

## License

See [LICENSE](LICENSE). Built by [We Are The Art Makers](https://wearetheartmakers.com).
