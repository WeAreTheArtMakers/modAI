# Curated skill sources

Reviewed 2026-09-27. There is no universal "best skill": utility depends on the model,
tool surface, task and context cost. We selected maintained primary repositories,
specific instructions, inspectable provenance and realistic verification guidance.

| Source | Strength | MODAI integration |
| --- | --- | --- |
| [Anthropic frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md) | Intentional subject-specific design and self-critique | Linked, not copied; original compact calibration reference |
| [Microsoft Playwright CLI](https://github.com/microsoft/playwright-cli/blob/main/skills/playwright-cli/SKILL.md) | Browser snapshots, interaction checks, console evidence | Linked, not installed; MODAI uses its existing local Playwright gates |
| [WCAG contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) | Objective contrast criteria | Solid-background text contrast measurements; unsupported backgrounds explicitly unmeasured |

Microsoft's repository license is Apache-2.0. Anthropic's skill has its own
[LICENSE.txt terms](https://github.com/anthropics/skills/blob/main/skills/frontend-design/LICENSE.txt);
we reviewed the skill-local license and have not redistributed the upstream text.
No third-party skill is silently downloaded, enabled or permitted to broaden tool
capabilities. Links can change: review content and licensing before vendoring any skill.

Our reference uses independently written guidance. Frontend tasks still load at most
two automatic skills. Additional calibration material is loaded on demand, so short
tasks do not pay for a large design manual or a second planning agent.
