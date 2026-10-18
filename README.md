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

Version 5.3 keeps ordinary software tasks on the persistent **Code Virtuoso** path. Explicit Adaptive Orchestra adds useful read-only research and review around that same writer. Progress is measured by artifacts, passing gates, and verified fixes—not by how many agents spoke.

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
modai --mode orchestra "task"  # staged Adaptive Orchestra
modai --full-orchestra "task"  # legacy 4.x planner/persona engine
```

`orchestra` runs **Research → Code → Verify → Review → one optional repair → Final Verify**. Research has bounded read-only project/public-source tools; Code Virtuoso is the sole workspace writer in its existing persistent session. Verification uses current deterministic tests and browser gates without an extra model call. The independent local reviewer gets bounded excerpts of changed files and actual check results, with no tools. An invalid reviewer response gets at most one local retry; two invalid responses yield `needs_attention`, never an invented PASS. A blocking finding returns to the same coder for at most one review-driven repair cycle. `--full-orchestra` preserves the older 4.x planner/persona workflow.

All MODAI-owned local generation in this staged path passes through one FIFO scheduler (concurrency **1**). This does not control other Ollama clients or guarantee that a model fits in memory. Research and review may make separate calls to the same selected model; no extra model is loaded or downloaded. The local reviewer requests non-streaming JSON Schema output when Ollama supports it, then validates file references and findings; unsupported formatting gets only one bounded plain-JSON fallback. `auto` still prefers `solo` for simple work.

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

Adaptive Orchestra additionally writes `tasks.sqlite3` in that run directory. The database stores six stable stage IDs, dependencies, role permissions, bounded summaries, artifact hashes and verification checkpoints; it does **not** copy complete conversations. `session.jsonl` remains authoritative, and the index can be rebuilt from completed stage records after an interruption. On resume, completed research and code stages are not blindly rerun. A changed output is reverified and rereviewed; a missing output yields `needs_attention`. When an explicitly referenced local README changes its supported acceptance requirements, the coder and reviewer receive the updated checklist. Even a previously completed run rechecks the final gate against current files. Both transcript and index are private run data—protect the workspace and backups accordingly.

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
modai --mode orchestra --resource-profile fast "TASK"
modai --mode orchestra --resource-profile balanced --num-ctx 16384 "TASK"
modai --mode orchestra --resource-profile extended "TASK"
modai --mode orchestra --trust-project-commands "TASK"
modai --repair-rounds 4 "TASK"
modai --invalid-tool-limit 2 "TASK"   # stop after repeated malformed mutation calls (1-5)
modai --max-tool-rounds 12 "TASK"       # legacy compatibility setting
modai --max-hours 24 "TASK"             # legacy engine active-time guard
```

Run these commands **inside your real project directory**, or add `--workspace "$PWD"` there. Paths such as `/path/to/project` in examples are placeholders, not directories MODAI creates for you. An explicit `--workspace` must already exist; an invalid path produces a short error without a Python traceback.

Malformed native tool arguments receive a bounded schema diagnostic; repeated invalid file mutations stop with `NEEDS_ATTENTION` and preserve the checkpoint. A noninteractive failed run exits nonzero. Model-written claims of success never override deterministic artifact and quality gates.

Adaptive Orchestra defaults to `balanced`: context stays at 8192 unless measured memory headroom supports the requested 16384. `fast` caps at 8192. `extended` may allow up to 32768 only with at least 24 GB total memory and measured headroom; it will **not** activate a larger context on an M1 Pro 16 GB. These are conservative context targets, not measured KV-cache allocations. When telemetry is unavailable MODAI stays at 8192. On macOS it pauses before a new model call below 12% reported free memory, or below 25% with at least 64 recent swap-out pages per second. Allocated swap alone is reported but does not trigger a pause. The TUI orchestration profile also exposes these settings.

In staged mode, discovered project test/build scripts are **not** run by default; that is a truthful failed verification gate, not a skipped PASS. Review scripts in a trusted workspace before enabling `--trust-project-commands` or `MODAI_TRUST_PROJECT_COMMANDS=true`. This permission flag is not OS isolation: use a separate account/container for untrusted code. SOLO/AUTO keep their pre-5.3 project-command behavior for compatibility.

### Network and cloud

```bash
modai --no-internet "TASK"
modai --allow-cloud "Public research task"
```

Cloud is off by default. Configure OpenAI, Anthropic, Google, or Groq interactively with `/cloud setup`, then opt in per task with `--allow-cloud` or `/hybrid TASK`. In orchestra mode, only the bounded read-only research delegate can use that cloud runtime; the coder and reviewer remain local. Internet must also be enabled. Cloud research receives the original user task and public-web-only tools, not project-file excerpts. Only opt in when that original task is safe to send. Groq uses its OpenAI-compatible chat-completions API; set `GROQ_API_KEY` in the environment or use the macOS Keychain setup. No provider is a paid fallback for a local failure. Prompts containing obvious secrets disable cloud routing. The cloud token budget is a paid-provider cost guard only:

```bash
modai --cloud-token-budget 1000000 --allow-cloud "TASK"
```

Local Ollama usage has no token ceiling. When a cloud budget is reached, MODAI asks whether to add more tokens or pause; it does not pretend the unfinished task completed.

Privacy profiles: `MODAI_PRIVACY_PROFILE=guarded` is the default and blocks common credential files (including `.env`, private keys, and cloud credential folders) in model-facing file tools. `strict` blocks additional hidden and secret-named paths. `legacy` is an explicit compatibility override. Direct user-controlled file operations are distinct from model tool calls. Auxiliary command logs are scrubbed and run/session files are private (`0700` directories, `0600` files on POSIX); canonical session transcripts retain content so resume works. Keep run directories private and encrypted at rest if necessary.

These controls are **not an OS sandbox**: model-initiated project scripts/tests may still read files or environment variables under your user account. Use a separate OS account/container and a sanitized workspace for untrusted repositories. A user prompt can itself contain private context; only opt into cloud for a public research task. Cloud delegates get the original task rather than model-authored file excerpts, and their tools are restricted to public web research. Cloud main-coder access remains disabled pending a separate data-scope permission design.

The new `ToolGateway` is a deny-by-default capability/approval boundary for future MCP adapters and has a mocked read-only test. It does **not** start external servers, implement MCP transport, or grant third-party account mutations in this release.

Optional `cloud_billing_tier` (`unknown`, `free`, `paid`) records your account classification; it is not inferred from provider name. `cloud_input_usd_per_million` and `cloud_output_usd_per_million` are separate user-supplied rates. Without both, estimated USD cost is **unknown**, never zero. `cloud_usd_limit` requires both prices; the current guard pauses after the recorded request reaches the limit, so one in-flight request can exceed it. Token budgets remain the primary bound. Rate limits are surfaced with a safe error category and `Retry-After` when available; MODAI does not automatically retry paid requests.

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

When a build task explicitly references a permitted local README.md, MODAI extracts a bounded acceptance checklist with the source of each supported requirement. For static pages, the separate requirement_coverage gate checks rendered DOM and mobile/desktop behavior: semantic landmarks, usable navigation targets, requested card count/layout, reachable CTA, embedded CSS, external asset restrictions and responsive overflow. A page that merely loads in Chromium cannot satisfy missing user-requested features. The checklist is task evidence, never executable README policy; unrelated minimal HTML tasks keep their existing gates. Visual design is reported as UNAVAILABLE unless a capable independent vision review actually runs. That status does not certify premium aesthetics or turn concrete requirement failures into PASS. For a human aesthetic check, inspect the optional mobile/landscape/tablet/desktop screenshots under the workspace's .modai/browser directory.

### 5.2 focused phases, direct verification and visual calibration

The persistent coder now has separately tested model recovery, bootstrap, tool-selection,
skill and verification phases. Empty static projects get a smaller initial tool surface
and a compact first-artifact target; existing repositories retain normal editing access.
First-artifact latency is recorded by model rather than hidden behind an agent count.

Project checks are derived directly from actual files: Python tests, Node package scripts
and package-manager lockfiles, Go modules and Rust manifests. A JS `tests/` directory
does not trigger pytest. The `verify` tool runs those checks directly and returns compact
repair evidence. Static-browser gates exercise anchor clicks and hidden navigation;
production landing tasks also check measurable solid-background text contrast.

```bash
# Real local coding benchmark (isolated temporary workspace)
.venv/bin/python tests/benchmark_local.py --model studiobrn/modHacker:latest --no-visual-review
# Deterministic visual examples + broken negative control, no model/network
.venv/bin/python scripts/benchmark_visual.py
# Inspect your own rendered page; report + four screenshots
.venv/bin/python scripts/benchmark_visual.py --workspace /path/to/site
# Compare installed local models, sequentially (no extra model memory pressure)
.venv/bin/python scripts/benchmark_models.py --model MODEL_A --model MODEL_B --repeat 3
```

Calibration distinguishes objective issues from subjective design. Gradients, images,
transparent text and unsupported color spaces may be unmeasured; a clean heuristic result
is not a full WCAG or premium-design certification. See [reviewed skill sources](docs/SKILL_SOURCES.md)
and [phase architecture](docs/HARNESS_ARCHITECTURE.md).

### Reliability and domain skills

The Code Virtuoso now loads up to two domain skills for obvious tasks without a planning request. A landing page uses `landing-page-design` and `frontend-engineering` in the same SOLO session. Nine curated skills cover frontend, Python, debugging, web research, Web3, finance, accessibility and security. See [Skills guide](docs/SKILLS.md).

```bash
modai doctor
modai --model studiobrn/modHacker:latest doctor
modai --skills
modai --skill repo-debugging "Fix the current failing test"
modai --trust-project-skills "Build this project"
```

`doctor` performs real streaming and native tool smoke tests; it does not merely check installed packages. It distinguishes runtime failures from harness failures and prints the actual Python environment. Explicit top-level `think=False` is preserved. Local templates that require a single initial system message receive normalized project/skill instructions.

The production CLI accepts a complete model write up to 16,000 characters. The low-level registry retains a configurable 4,000-character compatibility mode for staged workflows. An error or non-zero command exit is never displayed as successful execution. Actual changed files, tool paths/commands, failure details and visible generation progress are shown in the terminal; `d` toggles details without printing into the spinner line.

Timeout retries preserve the session and files. Empty visible responses get one reduced-context retry, and bounded truncated-write recovery remains available. Technical PASS never replaces the user's requested implementation. Resume preserves cumulative token counts and verification sequence. Cloud delegates cannot read local files or test logs.

Update an existing checkout without recreating your selected model:

```bash
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
modai --version
modai doctor
```

The installed command points at `run.sh`, which selects its own virtual environment. A full `./setup.sh` is needed for a fresh installation; routine source updates do not require downloading/rebuilding the model.

Current measured local performance and known limitations are recorded in [Harness audit](docs/HARNESS_AUDIT.md). These are measured examples, not speed or design-quality guarantees.

MODAI extracts an artifact contract from explicit filenames in the prompt. A task naming `index.html`, `styles.css`, and `app.js` cannot complete while one is missing or empty.

For static sites it also runs:

- local asset reference checks;
- HTML structure, viewport, duplicate IDs, image `alt`, CSS brace, and JavaScript syntax checks;
- Playwright Chromium at mobile, landscape, tablet, and desktop sizes;
- horizontal overflow, visible content, broken anchors/local navigation, console errors, runtime exceptions, and menu-toggle checks;
- screenshots under the target site’s `.modai/browser/` directory.

For detected Python and Node projects, SOLO/AUTO run available pytest and package scripts (`test`, `lint`, `build`) with bounded logs. In Adaptive Orchestra these scripts require `--trust-project-commands` after inspection; otherwise verification reports an explicit failure. A failed gate is injected back into the same coding conversation as exact current evidence.

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
  "orchestra_resource_profile": "balanced",
  "trust_project_commands": false,
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

The deterministic suite uses a scripted fake runtime and covers the persistent loop, native tools, atomic edits, truncated responses, no-progress recovery, resume, compaction, queues, permissions, routing, latest validation evidence, a real landing-page browser E2E fixture, a repair fixture, and legacy orchestra regression. Version 5.3 adds staged-orchestra, one-writer, read-only review, JSONL index recovery, scheduler pressure/FIFO, mocked gateway and Chromium fixture tests. A short real-model smoke proves local Ollama transport and scheduling only; it is not a guarantee that every model/task will finish on 16 GB.

Pull requests run the same Python regression suite on GitHub Actions with Chromium installed. The workflow is a separate CI environment, not an Ollama or Apple Silicon benchmark; check the PR status before treating it as passed.

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
