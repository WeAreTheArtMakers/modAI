# Skills: expertise for the same Code Virtuoso session

Skills contain reusable domain guidance. They are not agents and do not create a planner, debate or review chain. The coding harness permanently enforces workspace permissions, tool execution, verification, preservation of user work and truthful mutation reporting.

## Discovery and precedence

MODAI discovers direct subdirectories containing `SKILL.md` in:

1. `<workspace>/.modai/skills/` when explicitly trusted;
2. `~/.modai/skills/`;
3. installation `resources/skills/`.

Project overrides global; global overrides built-in. Every override emits a diagnostic. Discovery parses only YAML frontmatter. The model sees a compact name/description catalog; only selected complete skill files enter its context. A model request is never spent selecting skills for obvious tasks.

Project skills require `--trust-project-skills` or `trust_project_skills: true`. This permission applies only to the selected workspace. Symlinks escaping discovery roots and relative references escaping the skill folder are rejected. Skills never expand write, network, cloud or command capabilities. They cannot authorize destructive commands or transmit project files to cloud delegates.

## Routing and commands

The bilingual deterministic router automatically loads up to two skills; the configurable hard maximum is three. Ordinary README heading changes need no domain skill.

| Task | Skills |
| --- | --- |
| Landing page | landing-page-design, frontend-engineering |
| Python traceback | repo-debugging, python-engineering |
| Current Ethereum L2 fees | web3-engineering, web-research |
| BTC funding and open interest | finance-research, web-research |

```text
modai --skills
modai --skill repo-debugging "Fix this bug"
modai --trust-project-skills "Build this product"
/skills
/skills doctor
/skills active
/skill:landing-page-design
/skill:repo-debugging Fix this error
/skill python-engineering
```

Explicit selection persists for the current command-screen session. Available skill files are rediscovered each new task, and `load_skill` revalidates edited resources without restarting the app. `♫ SKILL` events announce activation. Names and content hashes are recorded in the append-only task session; unchanged versions are not duplicated. The context detail reports estimated total, skill, schema and chat tokens. Estimates are not the provider's exact tokenization.

## Author a skill

```markdown
---
name: company-frontend
description: Apply the company design system to its frontend components and responsive pages.
---

# Company Frontend
Use the existing components and design tokens. For typography problems,
read [Typography](references/typography.md).
```

The name must match its directory, use lowercase letters/digits/hyphens and stay under 64 characters. A non-empty description of at most 1,024 characters defines activation. YAML is parsed with `safe_load`. Keep the body preferably below 2,500 tokens; domain references belong in focused relative files. A resource over 16 KB is rejected, and active skill content may not consume more than one-third of the configured window.

Model tool examples:

```json
{"name":"landing-page-design"}
{"name":"landing-page-design","reference":"references/typography.md"}
```

`load_skill` inserts the instructions once and returns a short confirmation. Supporting references are never injected automatically. Assets are output resources, not instructions; scripts still require permitted tools and project authority to run. `MODAI.md` and `AGENTS.md` remain separate persistent project rules.

## Design review

When enabled for a landing page and the local model advertises vision, MODAI uses mobile and desktop screenshots for structured visual findings. This stays within the same local session. A functional PASS does not establish subjective design quality. Visual review is bounded to an initial review and one confirmation after a repair; unavailable vision is reported, never represented as PASS. Use `--no-visual-review` to omit model vision while keeping browser checks.

## Tests and reference architecture

```bash
.venv/bin/python -m pytest tests/test_skills_reliability.py -q
modai doctor
.venv/bin/python tests/benchmark_local.py --model MODEL --no-visual-review
.venv/bin/python tests/benchmark_local.py --model MODEL --no-visual-review --repair-fixture
```

The discovery/progressive-disclosure design follows the open [Agent Skills specification](https://agentskills.io/specification) and architectural lessons from [Pi skills](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md), [packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md) and [SDK boundaries](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sdk.md). MODAI implements the mechanism independently in Python.
