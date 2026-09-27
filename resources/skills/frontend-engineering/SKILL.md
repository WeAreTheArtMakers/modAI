---
name: frontend-engineering
description: Build and repair semantic HTML, CSS, JavaScript and responsive frontend interactions in the existing project stack.
---

# Frontend Engineering
Keep every navigation destination reachable on mobile; hiding desktop links without an alternative is not responsive navigation. Ensure every #target exists. Repair a missing target without renaming another target still referenced elsewhere. Do not attach querySelector to the bare '#' placeholder. Use text colors with sufficient contrast on CTA backgrounds. Project-configured tests and browser gates are available through verify; do not guess shell test commands.
Follow the existing stack and file conventions. Simple static HTML needs no framework or npm dependencies. Use semantic main/nav/section landmarks and real links. Use buttons for actions with accessible names, keyboard support, focus indication and correct aria-expanded.
For mobile navigation, ensure the JS selector, CSS open state and HTML IDs agree. Test open/close, keyboard and resize behavior. Prefer progressive enhancement: primary content remains visible without JS. Avoid animation hiding content forever; respect prefers-reduced-motion.
Use flexible grids, min-width:0, fluid type and reasonable max-width. Validate local assets and all referenced files. Check JS syntax, console errors, mobile, landscape, tablet and desktop overflow. Repair concrete failures with precise edits instead of rewriting a passing page.
