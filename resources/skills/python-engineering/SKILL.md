---
name: python-engineering
description: Implement Python features and repair Python tracebacks with focused tests and the project's existing environment.
---

# Python Engineering
Use the project's interpreter and dependency conventions. Internal Python subprocesses use sys.executable. Reproduce the traceback, inspect the failing function and test, then make a small change. Keep API compatibility unless migration is requested.
Handle errors at the boundary with specific types and useful diagnostics. Avoid swallowing exceptions or treating an error dictionary as success. Use context managers for resources. Test the failing behavior and nearby regressions; run available pytest checks before completion.

