---
name: repo-debugging
description: Reproduce and fix repository bugs, failing tests, regressions and incorrect behavior with evidence rather than broad rewrites.
---

# Repository Debugging
Reproduce the smallest failing path. Inspect its caller and relevant files, form one hypothesis, apply a targeted change and rerun the failing check. Read logs and current state before guessing.
Search names and selectors instead of reading the entire repo repeatedly. Preserve unrelated work. A newer successful test supersedes the older failure. Do not expand architecture before reproducing the issue. Report the actual cause, change and tests, and any unresolved limitation.

