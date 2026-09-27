# Visual calibration, not template copying
Compare the result with the task-specific fixtures under tests/fixtures/visual.
The editorial fixture demonstrates type hierarchy and readable measure; the technical
fixture demonstrates clear install actions and truthful product facts. Do not copy
their visual identities into unrelated briefs.
The broken fixture is a negative control: faint text, fixed mobile width, missing
navigation destination, weak headline hierarchy. These are defects, not stylistic preferences.
Use verify for functional gates. Local visual calibration adds contrast and type
heuristics; neither a score nor browser PASS proves that a design is beautiful.
Respect the user's direction over any reference. Prefer real content and one memorable
visual idea over decorative repetition. Do not add extra planning/model turns for this reference.

Reviewed primary sources (2026-09-27):
- https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md
- https://github.com/microsoft/playwright-cli/blob/main/skills/playwright-cli/SKILL.md
- https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html

This is original MODAI guidance, not a redistributed upstream skill. The Playwright
CLI document describes tools not automatically available in MODAI; use MODAI's verify
tool instead of guessing CLI commands or installing software without permission.
