"""Isolated verification phase helpers."""
from __future__ import annotations

from typing import Any
import re
import json
import hashlib
import os
import time
from modai.quality.test_plan import discover_commands


class VerificationPhase:
    def _verification_key(self) -> str | None:
        # Only reuse local static gates, never arbitrary tests with environment,
        # network, timing or external-state dependencies. Bounded full-content hash.
        if discover_commands(self.workspace) or not self.contract.static_site:
            return None
        digest = hashlib.sha256()
        used = 0
        count = 0
        excluded = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', '.modai', '.run', '.benchmark_run'}
        try:
            for root, dirs, files in os.walk(self.workspace, followlinks=False):
                from pathlib import Path
                base = Path(root)
                if any((base / d).is_symlink() for d in dirs if d not in excluded):
                    return None
                dirs[:] = sorted(d for d in dirs if d not in excluded
                                 and not (base / d).is_symlink()
                                 and (base / d).resolve() != self.run_dir.resolve())
                for name in sorted(files):
                    path = base / name
                    if path.is_symlink():
                        return None
                    used += path.stat().st_size
                    count += 1
                    if used > 5_000_000 or count > 1000:
                        return None
                    digest.update(str(path.relative_to(self.workspace)).encode())
                    digest.update(b'\0')
                    digest.update(path.read_bytes())
                    digest.update(b'\0')
        except OSError:
            return None
        digest.update(json.dumps(sorted(self.coding_tools.mutated_paths)).encode())
        return digest.hexdigest()

    def _verify(self) -> Any:
        key = self._verification_key()
        cached = getattr(self, '_verification_cache', None)
        if (key and cached and cached[0] == key and cached[2].verdict == 'PASS'
                and time.monotonic() - cached[1] < 30):
            self.events.emit('verification_reused', sequence=cached[2].sequence, reason='unchanged content hash')
            return cached[2]
        report = self.verifier.verify(sorted(self.coding_tools.mutated_paths))
        if (report.verdict == 'PASS' and self.max_write_chars > 4000
                and 'landing-page-design' in self.active_skills):
            from modai.quality.calibration import calibrate
            from modai.quality.project import CheckResult
            try:
                calibration = calibrate(self.workspace, self.run_dir / 'visual-calibration')
                errors = [f"{item['viewport']}: text {failure['text']!r} contrast {failure['contrast']} < {failure['minimum']}. Adjust foreground/background colors."
                          for item in calibration['viewports'] for failure in item['contrast_failures']]
                partial = any(item['unmeasured_texts'] for item in calibration['viewports'])
                report.checks.append(CheckResult('text_contrast', 'FAIL' if errors else 'SKIP' if partial else 'PASS', errors, calibration))
                if errors:
                    report.verdict = 'FAIL'
            except Exception as exc:
                report.checks.append(CheckResult('text_contrast', 'FAIL', [f'Contrast evidence unavailable: {exc}']))
                report.verdict = 'FAIL'
        if report.verdict == 'PASS' and self.visual_review_enabled and 'landing-page-design' in self.active_skills:
            if self._visual_attempts < 2 and self._visual_result.get('verdict') != 'UNAVAILABLE':
                from modai.quality.visual import review
                self.events.emit('visual_review_started', attempt=self._visual_attempts + 1)
                self._visual_result, response = review(self.runtime, self.workspace, self.task)
                self._visual_attempts += 1
                if response:
                    self._model_calls += 1
                    self._record_usage(response)
                self.events.emit('visual_review_finished', **self._visual_result)
            if self._visual_result.get('verdict') == 'FAIL':
                from modai.quality.project import CheckResult
                report.checks.append(CheckResult('visual_design', 'FAIL',
                    [str(x) for x in self._visual_result.get('blocking_changes', [])] or ['Visual review failed; inspect screenshots'],
                    self._visual_result))
                report.verdict = 'FAIL'
        self.session.append({"type": "verification", "report": report.as_dict()})
        self.events.emit("verification_finished", **report.as_dict())
        self._verification_cache = (key, time.monotonic(), report)
        return report


    def _verification_message(self, report: Any, *, proactive: bool = False) -> dict[str, Any]:
        if report.verdict == "PASS":
            content = (
                "CHECKPOINT: current repository passes deterministic quality gates. "
                "Continue implementing any remaining parts of the objective, or return a final summary if done."
            )
        else:
            exact = (
                "\n".join(f"- {item}" for item in report.errors[:30])
                or "- required evidence is missing"
            )
            label = "CHECKPOINT" if proactive else "VALIDATION"
            content = (
                f"{label} FAILED.\n{exact}\n"
                "Repair only these exact current failures. "
                "Do not reread unchanged files unless a targeted line is required."
            )
        return {"role": "user", "content": content}


    @staticmethod
    def _is_structural_failure(report: Any) -> bool:
        """Return True when repair requires creating missing files (needs write).

        Targeted failures (CSS overflow, lint error on existing file) need only edit.
        Structural failures (missing artifact file) need write as well.
        """
        for check in report.checks:
            if check.verdict != "PASS":
                for err in check.errors:
                    low = err.lower()
                    if (
                        "required file is missing" in low
                        or "missing or empty" in low
                        or "not found" in low
                        or "missing asset" in low
                        or "missing script" in low
                    ):
                        return True
        return False


    def _resolve_css_selector(self, selector: str) -> dict[str, Any] | None:
        """Given a DOM selector like 'table.tools-table', find likely CSS source location.

        Search priority:
          1. Exact full selector in .css files
          2. Class name in .css files
          3. ID in .css files
          4. <style> blocks in .html files

        HTML body class attributes are NOT treated as CSS source.
        Returns a snippet of the declaration block if found.
        """
        # Extract class names and ID from selector
        class_names = re.findall(r"\.([\w-]+)", selector)
        id_match = re.search(r"#([\w-]+)", selector)
        tag_match = re.match(r"^([a-z][\w-]*)", selector)

        candidates: list[tuple[int, str, int, int, str]] = []
        # priority bucket: 0=exact-full-selector, 1=class-in-css, 2=id-in-css, 3=style-block

        css_files = sorted(self.workspace.glob("**/*.css"))
        html_files = sorted(self.workspace.glob("**/*.html"))

        def _extract_block(file_lines: list[str], rule_line: int) -> str:
            """Extract the CSS declaration block starting at rule_line (1-based)."""
            result: list[str] = []
            in_block = False
            depth = 0
            for i, line in enumerate(file_lines[max(0, rule_line - 1):rule_line + 40], rule_line):
                result.append(f"  {i}: {line}")
                if "{" in line:
                    depth += line.count("{")
                    in_block = True
                if "}" in line:
                    depth -= line.count("}")
                    if in_block and depth <= 0:
                        break
            return "\n".join(result)

        for source_file in css_files:
            try:
                text = source_file.read_text(encoding="utf-8", errors="replace")
                file_lines = text.splitlines()
            except OSError:
                continue
            rel = str(source_file.relative_to(self.workspace))

            # 1. Exact full selector (e.g. "table.tools-table" or ".tools-table")
            for test_sel in ([selector] + [f".{c}" for c in class_names]):
                pattern = re.compile(
                    re.escape(test_sel) + r"\s*[{,]",
                    re.MULTILINE,
                )
                for m in pattern.finditer(text):
                    line_no = text[: m.start()].count("\n") + 1
                    snippet = _extract_block(file_lines, line_no)
                    priority = 0 if test_sel == selector else 1
                    candidates.append((priority, rel, line_no, line_no + 15, snippet))

            # 2. ID search
            if id_match:
                pattern = re.compile(
                    r"#" + re.escape(id_match.group(1)) + r"\s*[{,]",
                    re.MULTILINE,
                )
                for m in pattern.finditer(text):
                    line_no = text[: m.start()].count("\n") + 1
                    snippet = _extract_block(file_lines, line_no)
                    candidates.append((2, rel, line_no, line_no + 15, snippet))

        # 3. <style> blocks in HTML (lowest priority)
        for source_file in html_files:
            try:
                text = source_file.read_text(encoding="utf-8", errors="replace")
                file_lines = text.splitlines()
            except OSError:
                continue
            rel = str(source_file.relative_to(self.workspace))

            # Only search inside <style>...</style>
            for style_m in re.finditer(r"<style[^>]*>(.*?)</style>", text, re.S | re.I):
                style_content = style_m.group(1)
                style_start_line = text[: style_m.start(1)].count("\n")
                for cls in class_names:
                    pattern = re.compile(r"\." + re.escape(cls) + r"\s*[{,]", re.MULTILINE)
                    for m in pattern.finditer(style_content):
                        line_no = style_start_line + style_content[: m.start()].count("\n") + 1
                        snippet = _extract_block(file_lines, line_no)
                        candidates.append((3, rel, line_no, line_no + 15, snippet))

        if not candidates:
            return None

        candidates.sort(key=lambda c: (c[0], c[2]))  # priority first, then line number
        _, best_file, best_start, best_end, best_snippet = candidates[0]
        return {
            "file": best_file,
            "start_line": best_start,
            "end_line": best_end,
            "snippet": best_snippet,
        }


    def _build_repair_context(self, report: Any) -> str:
        """Build a structured JSON repair context for the model.

        Enriches browser_quality failures with CSS source location so the model
        can make a single targeted edit instead of re-reading the whole codebase.
        """
        ctx: dict[str, Any] = {
            "mode": "REPAIR",
            "failures": [],
        }

        for check in report.checks:
            if check.verdict == "PASS":
                continue

            failure: dict[str, Any] = {"validator": check.name, "errors": []}

            if check.name == "browser_quality":
                for err in check.errors[:5]:
                    entry: dict[str, Any] = {"message": err}

                    # Try to extract overflow diagnostic
                    sel_m = re.search(r"likely offender:\s*([^\s(]+)", err)
                    meas_m = re.search(
                        r"element width\s+(\d+)px.*?overflow\s+(\d+)px", err
                    )
                    vp_m = re.search(r"(\d+)>(\d+)", err)

                    if sel_m:
                        raw_selector = sel_m.group(1)
                        entry["selector"] = raw_selector
                        resolution = self._resolve_css_selector(raw_selector)
                        if resolution:
                            entry["source"] = {
                                "file": resolution["file"],
                                "start_line": resolution["start_line"],
                                "end_line": resolution["end_line"],
                            }
                            entry["current_code"] = resolution["snippet"]
                        if meas_m:
                            entry["measurements"] = {
                                "element_width_px": int(meas_m.group(1)),
                                "overflow_px": int(meas_m.group(2)),
                            }
                            if vp_m:
                                entry["measurements"]["viewport_width_px"] = int(vp_m.group(2))
                        entry["recommended_actions"] = [
                            f"add 'max-width: 100%' and 'overflow-x: auto' to "
                            f"'{raw_selector}' or wrap it in an overflow-x:auto container"
                        ]

                    failure["errors"].append(entry)

            else:
                failure["errors"] = [{"message": e} for e in check.errors[:10]]

            ctx["failures"].append(failure)

        repair_json = json.dumps(ctx, indent=2, ensure_ascii=False)
        return (
            repair_json
            + "\n\nMake the smallest targeted edit that fixes the listed failures.\n"
            "Do not redesign unrelated code. Do not inspect unrelated files."
        )
