# MODAI 5.2 — Focused coding phases and real quality evidence

## Upgrade

From your existing MODAI installation checkout:

```bash
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
modai --version
```

Expected version: `orchestrator.py 5.2.0`. Restart any old MODAI process. The installed
command points to the checkout, so another setup is not required when that link still
works. New installations should run `./setup.sh`. Run `modai doctor` when no other local
model task is running; concurrent probes compete with generation on a single-slot server.

## Changes

- Five phase helpers split bootstrap, model recovery, skills, verification and pure tool decisions from the coordinator.
- A soft first-artifact target and smaller initial schemas reduce generation overhead for empty static sites. Existing-project edits keep the normal tool surface.
- Model-specific first-artifact telemetry supports repeated installed-model comparisons using `scripts/benchmark_models.py`.
- Shared project test discovery supports real Python tests, package scripts and lockfiles, Go and Rust. JS-only test directories no longer falsely select pytest.
- `verify` runs current gates directly. Models receive concise findings; full evidence remains in session logs.
- Hash-identical static PASS can be reused for 30 seconds; changed content invalidates it. Arbitrary command tests never use this cache.
- Browser gates actually click visible anchor navigation and detect unreachable hidden navigation, not just existing IDs.
- Landing tasks check measured solid-background contrast. Unsupported/partly unmeasured text returns SKIP rather than a false complete contrast PASS.
- Two curated local design examples and a deliberately defective control provide four-viewport screenshots and measurable visual regression evidence.
- Reviewed primary skill Markdown sources are linked in `SKILL_SOURCES.md`. Original compact guidance is used rather than silently downloading third-party instructions or tools.

## Evidence and limitations

An intermediate local `studiobrn/modHacker:latest` run reduced first artifact latency
from the 5.1 observation of 233.1 seconds to 120.9 seconds; completion took 224.9 seconds
versus 283.0 seconds. It used 45,948 tokens versus 22,059 previously: faster first output
did not automatically mean fewer tokens. Extra repairs expose exactly why latency and
verified completion must both be measured. These are individual observations, not a
controlled statistical model ranking.

Stricter click/navigation/contrast gates were added after that intermediate run, because
functional PASS did not prove a polished interaction. Subsequent results must not be
compared as though the gate set stayed identical.

The stricter run completed with all gates PASS: first artifact **108.1 seconds**, total
**408.8 seconds**, **36,105 local tokens**, zero cloud tokens, 7 model calls and 6 tool
calls. An overlapping edit was correctly rejected atomically; the model then chose a
full rewrite, which cost extra generation time. A concurrent doctor probe also competed
with this run and timed out during its native-tool smoke check. This total is not a
controlled performance estimate. The generated page retained a non-blocking missing-main
landmark warning: it is not certified as perfect or fully accessible.

Validation: final full suite **232 passed in 116.82 seconds**; focused phase and behavior
suite **36 passed in 45.40 seconds**. Compilation and diff whitespace checks passed.
Re-running doctor after the coding run (without competing model requests) passed every
check, including native tool calling. The earlier concurrent timeout was recorded,
not hidden or treated as a successful diagnostic.

The model-matrix script was also executed end-to-end on the existing-page mobile-overflow
fixture, sequentially with the selected local model. It completed in **58.07 seconds**,
first precise edit at **35.53 seconds**, **14,606 local tokens**, zero cloud, four model
calls and four tools. All gates passed, no warnings, and the hash-identical final PASS
reused the same verification sequence instead of launching a second browser/test round.
The previous 5.1 repair observation was 61.68 seconds and 17,465 tokens; again these are
individual measurements, not a statistically reliable speedup claim.

The visual examples pass the supported heuristics, while the negative control triggers
overflow, missing navigation, weak hierarchy and low contrast. No heuristic score proves
premium design; image/gradient contrast, full keyboard accessibility and aesthetic review
still need broader evidence. No automatic model download or cloud token use was performed.

## Recommended next evaluations

Use at least three repeated runs per installed model, identical task/gates/context,
and no competing Ollama requests. Select by completed-task median and pass rate, not
first artifact alone. Expand fixtures for interactive menus, forms and multi-file sites.
Keep write ownership in one session on M1 Pro; only genuinely independent read-only
research benefits from extra agents.
