from __future__ import annotations

import os
import select
import shutil
import sys
import termios
import tty
import re
from pathlib import Path
from typing import Callable, Sequence


Option = tuple[str, str]
TEXT = {
    "tr": {
        "subtitle": "YEREL AJAN ORKESTRASYONU",
        "choose_hint": "↑ ↓ ile seç · Enter ile aç · q ile geri",
        "directory": "ÇALIŞMA KLASÖRÜ",
        "use_directory": "✓ Bu klasörü kullan",
        "parent": ".. Üst klasör",
        "directory_hint": "← geri · →/Enter aç",
        "continue": "Devam etmek için Enter",
        "task_title": "GÖREV PROMPTU",
        "task_help": "Promptu yazın; ok tuşlarıyla silmeden düzenleyebilirsiniz",
        "pasted": "Yapıştırılan metin",
        "characters": "karakter",
        "editor_help": "← → imleç · ⌥← ⌥→ kelime · Home/End · Backspace/Delete · Enter gönder · Esc iptal",
    },
    "en": {
        "subtitle": "LOCAL AGENT ORCHESTRATION",
        "choose_hint": "↑ ↓ select · Enter open · q back",
        "directory": "WORKING DIRECTORY",
        "use_directory": "✓ Use this directory",
        "parent": ".. Parent directory",
        "directory_hint": "← back · →/Enter open",
        "continue": "Press Enter to continue",
        "task_title": "TASK PROMPT",
        "task_help": "Type the prompt; use arrow keys to edit without deleting text",
        "pasted": "Pasted text",
        "characters": "characters",
        "editor_help": "← → cursor · ⌥← ⌥→ word · Home/End · Backspace/Delete · Enter submit · Esc cancel",
    },
}


def interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def decode_key(sequence: bytes) -> str:
    if not sequence:
        return "ignore"
    if sequence == b"\x03":
        return "interrupt"
    if sequence in {b"\r", b"\n"}:
        return "enter"
    if sequence == b"\x1b":
        return "escape"
    if sequence.startswith((b"\x1b[", b"\x1bO")):
        final = sequence[-1:]
        return {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}.get(final, "ignore")
    try:
        return sequence.decode("utf-8").lower()
    except UnicodeDecodeError:
        return "ignore"


def read_key() -> str:
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    try:
        # cbreak disables canonical input and echo without disabling terminal
        # output processing. Full raw mode also disables ONLCR on macOS, which
        # can make subsequent lines drift diagonally across the screen.
        tty.setcbreak(descriptor)
        sequence = os.read(descriptor, 1)
        if sequence == b"\x1b":
            # macOS terminals may send arrows as CSI (ESC [ A) or SS3 (ESC O A),
            # and the bytes can arrive separately. Gather the full sequence first.
            while len(sequence) < 16 and select.select([descriptor], [], [], 0.25)[0]:
                sequence += os.read(descriptor, 1)
                if sequence[-1:] in {b"A", b"B", b"C", b"D", b"~"}:
                    break
        key = decode_key(sequence)
        if key == "interrupt":
            raise KeyboardInterrupt
        return key
    finally:
        termios.tcsetattr(descriptor, termios.TCSANOW, previous)


def _utf8_length(first: int) -> int:
    if first < 0x80:
        return 1
    if first & 0xE0 == 0xC0:
        return 2
    if first & 0xF0 == 0xE0:
        return 3
    if first & 0xF8 == 0xF0:
        return 4
    return 1


def _safe_pasted_text(value: bytes) -> str:
    text = value.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))", "", text)
    return "".join(character if character in {"\n", "\t"} or ord(character) >= 32 else "" for character in text)


def read_editor_event(descriptor: int) -> tuple[str, str]:
    first = os.read(descriptor, 1)
    if first == b"\x03":
        raise KeyboardInterrupt
    if first in {b"\r", b"\n"}:
        return "enter", ""
    if first in {b"\x7f", b"\x08"}:
        return "backspace", ""
    if first == b"\x01":
        return "home", ""
    if first == b"\x05":
        return "end", ""
    if first == b"\x0b":
        return "kill_end", ""
    if first == b"\x15":
        return "kill_start", ""
    if first == b"\x17":
        return "delete_word", ""
    if first == b"\x1b":
        sequence = first
        while len(sequence) < 16 and select.select([descriptor], [], [], 0.08)[0]:
            sequence += os.read(descriptor, 1)
            if sequence.endswith((b"~", b"A", b"B", b"C", b"D", b"H", b"F", b"b", b"f")):
                break
        if sequence == b"\x1b[200~":
            pasted = b""
            marker = b"\x1b[201~"
            while marker not in pasted and len(pasted) < 1_000_000:
                pasted += os.read(descriptor, 4096)
            return "paste", _safe_pasted_text(pasted.split(marker, 1)[0])
        mappings = {
            b"\x1b[D": "left", b"\x1bOD": "left", b"\x1b[C": "right", b"\x1bOC": "right",
            b"\x1b[A": "history_up", b"\x1bOA": "history_up", b"\x1b[B": "history_down", b"\x1bOB": "history_down",
            b"\x1b[H": "home", b"\x1bOH": "home", b"\x1b[1~": "home", b"\x1b[7~": "home",
            b"\x1b[F": "end", b"\x1bOF": "end", b"\x1b[4~": "end", b"\x1b[8~": "end",
            b"\x1b[3~": "delete", b"\x1bb": "word_left", b"\x1bf": "word_right",
            b"\x1b[1;5D": "word_left", b"\x1b[1;5C": "word_right",
        }
        return mappings.get(sequence, "escape" if sequence == b"\x1b" else "ignore"), ""
    needed = _utf8_length(first[0])
    value = first
    while len(value) < needed and select.select([descriptor], [], [], 0.08)[0]:
        value += os.read(descriptor, needed - len(value))
    return "text", _safe_pasted_text(value)


class Dashboard:
    CYAN = "\033[38;5;45m"
    BLUE = "\033[38;5;39m"
    GREEN = "\033[38;5;84m"
    YELLOW = "\033[38;5;221m"
    WHITE = "\033[38;5;252m"
    DIM = "\033[38;5;245m"
    BOLD = "\033[1m"
    REVERSE = "\033[7m"
    RESET = "\033[0m"

    LOGO = (
        "  ███╗   ███╗ ██████╗ ██████╗   █████╗ ██╗",
        "  ████╗ ████║██╔═══██╗██╔══██╗ ██╔══██╗██║",
        "  ██╔████╔██║██║   ██║██║  ██║ ███████║██║",
        "  ██║╚██╔╝██║██║   ██║██║  ██║ ██╔══██║██║",
        "  ██║ ╚═╝ ██║╚██████╔╝██████╔╝ ██║  ██║██║",
        "  ╚═╝     ╚═╝ ╚═════╝ ╚═════╝  ╚═╝  ╚═╝╚═╝",
    )

    def __init__(self, color: bool = True, key_reader: Callable[[], str] = read_key, language: str = "tr") -> None:
        self.color = color and interactive_terminal() and not os.getenv("NO_COLOR")
        self.key_reader = key_reader
        self.language = language if language in TEXT else "tr"
        self.prompt_history: list[str] = []

    def t(self, key: str) -> str:
        return TEXT[self.language][key]

    def paint(self, text: str, *styles: str) -> str:
        if not self.color:
            return text
        return "".join(getattr(self, style) for style in styles) + text + self.RESET

    @staticmethod
    def clear() -> None:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()

    @staticmethod
    def _draw(lines: Sequence[str]) -> None:
        # Use explicit CRLF so every line starts in column zero even when the
        # parent terminal was left with output post-processing disabled.
        frame = "\033[2J\033[H" + "\r\n".join(lines) + "\r\n"
        sys.stdout.write(frame)
        sys.stdout.flush()

    def choose(
        self,
        title: str,
        options: Sequence[Option],
        subtitle: str | None = None,
        selected: int = 0,
        footer: Sequence[str] = (),
        show_logo: bool = True,
    ) -> int | None:
        if not options:
            return None
        selected = max(0, min(selected, len(options) - 1))
        while True:
            lines: list[str] = []
            if show_logo:
                if shutil.get_terminal_size((100, 30)).columns >= 60:
                    lines.extend(self.paint(line, "CYAN", "BOLD") for line in self.LOGO)
                else:
                    lines.append(self.paint("  MODAI", "CYAN", "BOLD"))
                lines.extend((self.paint("  " + self.t("subtitle"), "DIM"), ""))
            lines.extend((
                self.paint(f"  {title}", "WHITE", "BOLD"),
                self.paint(f"  {subtitle or self.t('choose_hint')}", "DIM"),
                "",
            ))
            for index, (label, description) in enumerate(options):
                prefix = "  ❯ " if index == selected else "    "
                if index == selected:
                    lines.append(self.paint(prefix + label, "GREEN", "BOLD"))
                    if description:
                        lines.append(self.paint("      " + description, "DIM"))
                else:
                    lines.append(self.paint(prefix + label, "WHITE"))
            if footer:
                lines.append("")
                lines.extend(self.paint("  " + line, "DIM") for line in footer)
            self._draw(lines)
            key = self.key_reader()
            if key in {"up", "k"}:
                selected = (selected - 1) % len(options)
            elif key in {"down", "j"}:
                selected = (selected + 1) % len(options)
            elif key in {"enter", "right", "l"}:
                return selected
            elif key in {"q", "escape", "left", "h"}:
                return None

    def select_directory(self, start: str | Path) -> Path | None:
        current = Path(start).expanduser().resolve()
        if not current.is_dir():
            current = Path.home()
        selected = 0
        while True:
            try:
                directories = sorted(
                    (item for item in current.iterdir() if item.is_dir() and not item.name.startswith(".")),
                    key=lambda item: item.name.lower(),
                )
            except PermissionError:
                directories = []
            options: list[Option] = [
                (self.t("use_directory"), str(current)),
                (self.t("parent"), str(current.parent)),
            ]
            options.extend((f"▸ {item.name}", "") for item in directories[:200])
            width = shutil.get_terminal_size((100, 30)).columns
            shown_path = str(current)
            if len(shown_path) > width - 8:
                shown_path = "…" + shown_path[-(width - 9):]
            choice = self.choose(
                self.t("directory"),
                options,
                subtitle=shown_path + "  ·  " + self.t("directory_hint"),
                selected=selected,
                show_logo=False,
            )
            if choice is None:
                return None
            if choice == 0:
                return current
            if choice == 1:
                current = current.parent
                selected = 0
            else:
                current = directories[choice - 2]
                selected = 0

    def message(self, title: str, lines: Sequence[str]) -> None:
        frame = ["", self.paint(f"  {title}", "BOLD", "CYAN"), ""]
        frame.extend("  " + line for line in lines)
        frame.extend(("", self.paint("  " + self.t("continue"), "DIM")))
        self._draw(frame)
        while self.key_reader() != "enter":
            pass

    def edit_task(self, event_reader: Callable[[], tuple[str, str]] | None = None) -> str | None:
        if event_reader is None and not interactive_terminal():
            value = input("task › ").strip()
            return value or None
        value = ""
        cursor = 0
        pasted_count = 0
        history_index = len(self.prompt_history)
        descriptor = sys.stdin.fileno() if event_reader is None else -1
        previous = termios.tcgetattr(descriptor) if descriptor >= 0 else None
        if descriptor >= 0:
            tty.setcbreak(descriptor)
            sys.stdout.write("\033[?2004h")
            sys.stdout.flush()
        try:
            while True:
                self._draw_editor(value, cursor, pasted_count)
                event, text = event_reader() if event_reader is not None else read_editor_event(descriptor)
                if event == "text" and text:
                    value = value[:cursor] + text + value[cursor:]
                    cursor += len(text)
                elif event == "paste" and text:
                    value = value[:cursor] + text + value[cursor:]
                    cursor += len(text)
                    pasted_count = len(text)
                elif event == "left" and cursor:
                    cursor -= 1
                elif event == "right" and cursor < len(value):
                    cursor += 1
                elif event == "home":
                    cursor = 0
                elif event == "end":
                    cursor = len(value)
                elif event == "word_left":
                    cursor = self._word_left(value, cursor)
                elif event == "word_right":
                    match = re.search(r"\s*\S+", value[cursor:])
                    cursor += match.end() if match else len(value) - cursor
                elif event == "backspace" and cursor:
                    value = value[:cursor - 1] + value[cursor:]
                    cursor -= 1
                elif event == "delete" and cursor < len(value):
                    value = value[:cursor] + value[cursor + 1:]
                elif event == "delete_word" and cursor:
                    start = self._word_left(value, cursor)
                    value = value[:start] + value[cursor:]
                    cursor = start
                elif event == "kill_start":
                    value, cursor = value[cursor:], 0
                elif event == "kill_end":
                    value = value[:cursor]
                elif event == "history_up" and self.prompt_history:
                    history_index = max(0, history_index - 1)
                    value = self.prompt_history[history_index]
                    cursor = len(value)
                elif event == "history_down" and self.prompt_history:
                    history_index = min(len(self.prompt_history), history_index + 1)
                    value = self.prompt_history[history_index] if history_index < len(self.prompt_history) else ""
                    cursor = len(value)
                elif event == "enter":
                    result = value.strip()
                    if result:
                        self.prompt_history.append(result)
                        return result
                elif event == "escape":
                    return None
        finally:
            if descriptor >= 0:
                sys.stdout.write("\033[?2004l")
                sys.stdout.flush()
                termios.tcsetattr(descriptor, termios.TCSANOW, previous)

    @staticmethod
    def _word_left(value: str, cursor: int) -> int:
        while cursor > 0 and value[cursor - 1].isspace():
            cursor -= 1
        while cursor > 0 and not value[cursor - 1].isspace():
            cursor -= 1
        return cursor

    def _draw_editor(self, value: str, cursor: int, pasted_count: int) -> None:
        width = max(30, shutil.get_terminal_size((100, 30)).columns)
        display_before = value[:cursor].replace("\n", " ↵ ").replace("\t", "    ")
        display_after = value[cursor:].replace("\n", " ↵ ").replace("\t", "    ")
        available = max(10, width - 10)
        left = display_before[-max(1, available // 2):]
        remaining = available - len(left)
        shown = left + display_after[:remaining]
        if len(display_before) > len(left):
            shown = "…" + shown[1:]
        if len(display_after) > remaining and shown:
            shown = shown[:-1] + "…"
        prefix = "  task › " if self.language == "en" else "  görev › "
        status = (
            f"  {self.t('pasted')} · {pasted_count} {self.t('characters')}"
            if pasted_count else f"  {len(value)} {self.t('characters')}"
        )
        lines = [
            "", self.paint("  " + self.t("task_title"), "CYAN", "BOLD"),
            self.paint("  " + self.t("task_help"), "DIM"), "",
            self.paint(prefix, "GREEN", "BOLD") + shown, "",
            self.paint(status, "DIM"), self.paint("  " + self.t("editor_help"), "DIM"),
        ]
        self._draw(lines)
        prompt_row_from_bottom = 4
        cursor_column = min(len(prefix) + len(left), width - 1)
        sys.stdout.write(f"\033[{prompt_row_from_bottom}A\r\033[{cursor_column}C")
        sys.stdout.flush()
