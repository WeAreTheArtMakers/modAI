# MODAI 5.1 harness audit — 2026-09-27

## Reproduced failures and changes

The recorded run `20260927-195728-764622` emitted a completed 6,634-character HTML write twice. Its 4,000-character model-tool boundary rejected both attempts. The harness unconditionally set `ok=True` for returned dictionaries, so the terminal showed successful writes while the workspace remained unchanged. Production writes now accept up to 16,000 characters, and error dictionaries/non-zero exit codes are unsuccessful. The 4K compatibility mode and atomic-write protections remain tested.

Earlier browser failures were stored under individual viewports while the top-level error list was empty. Viewport-specific errors now reach the repair prompt and terminal. Latest verification evidence controls completion. A technical PASS must still follow a genuine requested mutation for implementation tasks.

Real model testing found another failure: the selected `studiobrn/modHacker:latest` template rejects system messages after the conversation begins. The adapter combines project rules, core policy and skills into one leading system message. `think` remains a top-level Ollama argument; thinking and visible content are tracked separately. Empty visible output cannot establish success.

Compaction previously discarded project rules/skills and could separate calls from results. It now retains permanent guidance and evicts complete tool groups. Cached reads return short reuse confirmations. A short transcript containing one large file is no longer exempt from compaction. Resume retains token totals instead of starting its cost display at zero.

Cloud delegates expose only permitted public web tools, never workspace reads or command logs. Empty/truncated delegated responses fail rather than producing a successful evidence memo. Simple software work remains SOLO; orchestra mode offers bounded independent read-only delegation.

## Baseline

Before this refactor, `.venv/bin/python -m pytest -q` completed with **189 passed in 116.98s**. New tests cover skills routing, trust/overrides, content limits, error truthfulness, system-template normalization, Python interpreter consistency, compaction, cloud data boundaries and nested browser failures.

Final full regression: **205 passed in 92.28s** using `.venv/bin/python -m pytest -q`. Focused domain/runtime/privacy tests: **16 passed in 0.16s** using `.venv/bin/python -m pytest tests/test_skills_reliability.py -q`. Compilation and `git diff --check` passed. Diagnostics additionally found two unrelated global skill folders with missing frontmatter; they were reported and ignored rather than silently loaded or edited.

## Real local model checks

Model: `studiobrn/modHacker:latest`; context: 8,192; think: false; streaming: enabled; cloud: disabled. `modai --model studiobrn/modHacker:latest doctor` in the selected workspace passed Python, virtual environment, Ollama client/server/model, visible `MODAI_OK`, streaming, native echo tool validation, Git, ripgrep and Chromium. No test tool was executed.

| Measurement | New landing page | Existing-page CSS repair |
| --- | ---: | ---: |
| Mode | SOLO | SOLO |
| Active skills | design + frontend | design + frontend |
| Model requests | 4 | 5 |
| Tool calls | 3 | 4 |
| First mutation | 233.12 s | 37.62 s |
| Total wall time | 283.01 s | 61.68 s |
| Input tokens | 18,176 | 17,060 |
| Output tokens | 3,883 | 405 |
| Total local tokens | 22,059 | 17,465 |
| Files changed | index.html | index.html |
| Duplicate reads | 0 | 0 |
| Verification calls | 1 | 1 |
| Repair cycles | 0 | 0 |
| Static / browser | PASS / PASS | PASS / PASS |

These runs used temporary workspaces, no paid services and actual model tools. The landing fixture supplies factual MODAI product content; it generates no backend, invented pricing, testimonials or customer metrics. Desktop/mobile screenshots were manually inspected: usable typography, composition and responsive stacking, with a basic visual style. The generated page still has a non-blocking missing-main-landmark warning. Automatic model vision was disabled for these measurements; do not interpret technical PASS as a premium visual-design score.

The CSS repair used one exact replacement of a 700px fixed-width main container. The model unnecessarily invoked pytest where no tests existed, then inspected the result. Its non-zero pytest exit was correctly reported. The current initial task context now explicitly tells it whether Python tests exist and that static/browser gates are run by the harness.

Reproduce:

```bash
.venv/bin/python tests/benchmark_local.py --model studiobrn/modHacker:latest --no-visual-review
.venv/bin/python tests/benchmark_local.py --model studiobrn/modHacker:latest --no-visual-review --repair-fixture
```

## Remaining work and suggested priorities

1. Split the large harness loop into tested generation, execution and repair phases; preserve the acceptance suite while removing historical policy branches.
2. Calibrate per-model generation profiles using time-to-first-mutation and token throughput. A completed 3,800-token tool response still takes minutes on this local model; accepting it fixes lost work, not raw inference speed.
3. Expose a verification tool and project-derived checks so models avoid irrelevant pytest/command exploration.
4. Strengthen design evaluation with a small reviewed fixture set. The optional local vision gate is capability-based and bounded, but model vision quality remains hardware/build dependent.
5. Expand orchestra acceptance tests for cancellation, dependency ordering and independently scoped work. More personas do not improve a simple task; parallel work should remain independent and writers isolated.
