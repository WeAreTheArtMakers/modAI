from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CATALOG_UPDATED = "2026-09-14"


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    name: str
    download_gb: float
    minimum_memory_gb: int
    recommended_memory_gb: int
    context_tokens: int
    capabilities: tuple[str, ...]
    source: str


@dataclass(frozen=True, slots=True)
class HardwareProfile:
    system: str
    architecture: str
    chip: str
    memory_gb: float
    logical_cores: int


CANDIDATES = (
    ModelCandidate(
        "qwen3.5:2b", 2.7, 6, 8, 4096, ("tools", "thinking", "vision"),
        "https://ollama.com/library/qwen3.5",
    ),
    ModelCandidate(
        "qwen3.5:4b", 3.4, 8, 12, 8192, ("tools", "thinking", "vision"),
        "https://ollama.com/library/qwen3.5",
    ),
    ModelCandidate(
        "qwen3.5:9b", 6.6, 12, 16, 8192, ("tools", "thinking", "vision"),
        "https://ollama.com/library/qwen3.5",
    ),
    ModelCandidate(
        "qwen3.5:27b", 17.0, 28, 32, 8192, ("tools", "thinking", "vision"),
        "https://ollama.com/library/qwen3.5",
    ),
    ModelCandidate(
        "qwen3.5:35b", 24.0, 40, 48, 16384, ("tools", "thinking", "vision"),
        "https://ollama.com/library/qwen3.5",
    ),
)


def _command_value(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def detect_hardware() -> HardwareProfile:
    system = platform.system() or "Unknown"
    architecture = platform.machine() or "unknown"
    memory_bytes = 0
    chip = ""
    if system == "Darwin":
        raw_memory = _command_value(["sysctl", "-n", "hw.memsize"])
        memory_bytes = int(raw_memory) if raw_memory.isdigit() else 0
        chip = _command_value(["sysctl", "-n", "machdep.cpu.brand_string"])
    elif system == "Linux":
        try:
            match = re.search(r"^MemTotal:\s+(\d+)\s+kB", Path("/proc/meminfo").read_text(), re.M)
            memory_bytes = int(match.group(1)) * 1024 if match else 0
        except OSError:
            pass
        chip = platform.processor()
    if not memory_bytes:
        memory_bytes = 8 * 1024**3
    return HardwareProfile(
        system=system,
        architecture=architecture,
        chip=chip or architecture,
        memory_gb=round(memory_bytes / 1024**3, 1),
        logical_cores=os.cpu_count() or 1,
    )


def recommend_model(hardware: HardwareProfile) -> ModelCandidate:
    eligible = [item for item in CANDIDATES if hardware.memory_gb >= item.recommended_memory_gb]
    if eligible:
        return eligible[-1]
    possible = [item for item in CANDIDATES if hardware.memory_gb >= item.minimum_memory_gb]
    return possible[-1] if possible else CANDIDATES[0]


def installed_models() -> set[str]:
    output = _command_value(["ollama", "list"])
    return {
        line.split()[0] for line in output.splitlines()[1:]
        if line.strip() and len(line.split()) >= 1
    }


def recommendation() -> dict[str, Any]:
    hardware = detect_hardware()
    selected = recommend_model(hardware)
    installed = installed_models()
    if hardware.memory_gb < 24:
        parallel_requests = 1
        reason = "16–GB sınıfında model, bağlam ve macOS için bellek payı bırakılarak görevler sıralı çalıştırılır."
    elif hardware.memory_gb < 48:
        parallel_requests = 2
        reason = "Bağımsız salt-okunur işler iki istekle paralelleştirilebilir; yazıcılar seri kalır."
    else:
        parallel_requests = min(4, max(2, hardware.logical_cores // 4))
        reason = "Yüksek bellekli sistemde bağımsız salt-okunur işler sınırlı paralel; yazıcılar tek birleştirme kuyruğundadır."
    return {
        "catalog_updated": CATALOG_UPDATED,
        "hardware": asdict(hardware),
        "recommended": asdict(selected),
        "installed": selected.name in installed,
        "fallback": "qwen3.5:4b" if selected.name != "qwen3.5:4b" else "qwen3.5:2b",
        "policy": {
            "local_models_loaded": 1,
            "parallel_requests": parallel_requests,
            "writer_policy": "serialized_merge_queue",
            "reason": reason,
        },
    }


def render_modelfile(template: Path, output: Path, base_model: str) -> None:
    content = template.read_text(encoding="utf-8")
    if not re.search(r"(?m)^FROM\s+\S+", content):
        raise ValueError("Modelfile içinde FROM satırı bulunamadı")
    rendered = re.sub(r"(?m)^FROM\s+\S+", f"FROM {base_model}", content, count=1)
    output.write_text(rendered, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MODAI yerel donanım ve Ollama model danışmanı")
    parser.add_argument("--json", action="store_true", help="Öneriyi JSON göster")
    parser.add_argument("--model-only", action="store_true", help="Yalnızca önerilen model adını göster")
    parser.add_argument("--render", type=Path, metavar="OUTPUT", help="Seçilen modelle geçici Modelfile üret")
    parser.add_argument("--template", type=Path, default=Path(__file__).with_name("Modelfile"))
    parser.add_argument("--base-model", help="Otomatik öneriyi geçersiz kıl")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = recommendation()
    model = args.base_model or report["recommended"]["name"]
    if args.render:
        render_modelfile(args.template, args.render, model)
    if args.model_only:
        print(model)
    elif args.json or not args.render:
        report["selected_model"] = model
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
