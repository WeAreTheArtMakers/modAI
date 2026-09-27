---
name: security-review
description: Review security-sensitive code, authentication, secrets, injection and smart contract changes using project-specific evidence.
---

# Security Review
Identify trust boundaries and actual deployment scope first. A static page does not need a backend, CORS or CSRF machinery. Review concrete inputs, filesystem access, secrets, authentication, dependencies and external calls applicable to the project.
Use read-only evidence and specific file/line findings. Prioritize exploitable defects with reproduction and a focused fix. Never execute destructive probes or transmit private project data. Separate verified findings from hypotheses and avoid generic checklists as blockers.

