# MODAI 5.0 Harness Architecture

MODAI 5.0 uses a persistent coding harness as the default execution engine. It keeps the proven Python CLI, Ollama local runtime, bilingual interface, legacy runs, and deterministic web gates while removing planning/debate overhead from ordinary software work.

## Boundaries

```text
CLI / TUI
  └─ deterministic TaskRouter (auto | solo | orchestra)
       └─ CodingHarness
            ├─ ModelRuntime (Ollama, scripted fake, future providers)
            ├─ SessionStore (append-only JSONL + control queues)
            ├─ ContextManager (budgeting + pair-safe compaction)
            ├─ ToolRegistry
            │    ├─ CodingTools
            │    ├─ shared evidence cache
            │    └─ ToolPolicy / Capabilities
            ├─ optional ReadOnlyDelegate
            └─ ProjectVerifier
                 ├─ artifact contract
                 ├─ Python / Node commands
                 ├─ static-site checks
                 └─ Playwright browser quality
```

The 4.x engine remains in `orchestrator.py` behind `--full-orchestra` and for legacy test doubles without a model `chat` capability. New sessions are marked `engine: coding-harness`.

## Model runtime

`ModelRuntime` is a protocol, not a concrete-client type check. A runtime exposes provider/model metadata, native-tool capability, and `generate(messages, tools)`. `OllamaRuntime` normalizes mapping-style and object-style responses, streamed and non-streamed content, tool calls, stop reasons, and token usage.

Native tool calls are primary. If a server explicitly rejects tool/function schemas, the adapter performs one compatibility request that asks for strict `{tool,args}` JSON. The harness decodes only that narrow shape and subjects it to the same policy and argument validation.

A response stopped for length with tool calls is unsafe: the complete batch is rejected and the model is asked for one smaller complete call.

## Persistent loop

One Code Virtuoso owns the write-capable session:

1. Load project instructions and a bounded tree.
2. Ask the model for the next native tool call or a final answer.
3. Execute calls through the capability policy and append results.
4. Track mutation evidence and repeated no-progress batches.
5. On a final answer, run deterministic verification outside the model.
6. If verification fails, append the exact latest failure and continue in the same session.
7. Complete only after current gates pass.

The loop has a high operational turn ceiling to catch broken models, but local tokens do not have a budget. A run that cannot pass gates becomes `needs_attention` and remains resumable.

## Sessions and events

`SessionStore` writes newline-delimited JSON records. Message, event, verification, and compaction records can be read after interruption. Every append is flushed. `state.json` is the compact UI/index projection, not the source transcript.

The event bus emits harness/model/tool/usage/verification/compaction lifecycle events. The existing TUI adapter renders compact product progress and persists important state transitions.

Control queues are thread-safe:

- `steer(text)` is drained before a new model turn;
- `follow_up(text)` is consumed after a verified completion boundary;
- `abort()` is observed before the next model turn.

No queue can interrupt an atomic file replacement.

## Context and compaction

Context size is estimated deterministically. Compaction preserves:

- the original system contract;
- the original user objective;
- an explicit continuation summary;
- recent conversation evidence;
- only complete assistant tool-call/tool-result pairs.

Orphaned tool results and half-complete tool calls are dropped. `/compact` appends a new authoritative compaction record, so the old transcript is auditable rather than overwritten.

## Tool policy

Capabilities are independent flags for read, write, test/build, network, and delegation. Read-only mode removes mutation schemas rather than relying on prompt wording.

Paths are resolved below the workspace. Writes use a temporary sibling, `fsync`, and `os.replace`. `edit` validates all exact matches and overlap constraints against the original file before changing anything; it retains UTF-8 BOM and line-ending style.

`bash` never invokes a shell. It accepts an argument array, rejects shell operators, uses an allowlist, blocks destructive programs and mutating Git actions, and saves complete output to a run log while returning a bounded summary.

Read evidence is cached by file-content hash, line-range arguments, and URL/query identity. The main coder and delegates share the same cache; editing a file naturally produces a new hash and therefore cannot return stale contents. Public web tools retain the existing network toggle and SSRF protections.

## Routing and delegation

`auto` is deterministic and strongly favors solo for code, fixes, tests, refactors, and web work. Broad research or explicit orchestra mode enables a `delegate` tool. A delegate has a small turn budget and a read-only registry; it returns an evidence memo to the persistent coder. The main writer remains the sole integration point.

When cloud access is configured and explicitly authorized for the task, only that bounded delegate is assigned the cloud runtime; the persistent writer remains local. Obvious secrets suppress cloud routing. Local and cloud usage are accounted separately, and only cloud usage is subject to the extend-or-pause cost boundary.

`--full-orchestra` is intentionally separate. It preserves historical planner, debate, and persona workflows but is no longer the default coding path.

## Verification and completion semantics

The artifact contract extracts explicit file paths from the task and adds `index.html` for static-site work. Required files must exist and be non-empty. Project detection adds available Node scripts and pytest. Static sites run deterministic parsing/asset checks plus four real Chromium viewports.

Each verification has a sequence number. Completion is based only on the latest sequence, preventing an earlier PASS from masking a later regression. The same persistent coder receives current errors and performs repair.

## Architectural reference

The design was informed by the MIT-licensed `earendil-works/pi` agent and coding-agent packages: stable inner/outer loops, safe steering boundaries, complete tool pairs, append-only sessions, atomic edits, and bounded tool output. MODAI is an independent Python implementation; no Pi source file was copied into this project.
