#!/bin/zsh
set -euo pipefail

cd "${0:A:h}"

echo "==> Checking Ollama..."
if ! command -v ollama >/dev/null 2>&1; then
  echo "HATA: Ollama bulunamadı. https://ollama.com/download adresinden kurun." >&2
  exit 1
fi
ollama --version

if ! ollama list >/dev/null 2>&1; then
  echo "HATA: Ollama servisine bağlanılamadı. Ollama uygulamasını açın veya 'ollama serve' çalıştırın." >&2
  exit 1
fi

echo "==> Checking Python..."
python_bin=""
python_candidates=("${MOD_AGENT_PYTHON:-}" python3.13 python3.12 python3.11 python3.10 python3)
for candidate in "${python_candidates[@]}"; do
  [[ -n "$candidate" ]] || continue
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" -c 'import sys, ensurepip, venv, xml.parsers.expat; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    python_bin="$(command -v "$candidate")"
    break
  fi
done
if [[ -z "$python_bin" ]]; then
  echo "HATA: venv, pip ve pyexpat modülleri çalışan Python 3.10+ bulunamadı." >&2
  echo "İpucu: brew install python@3.13" >&2
  exit 1
fi
echo "    $($python_bin --version) ($python_bin)"

echo "==> Creating Python virtual environment..."
"$python_bin" -m venv --clear .venv

echo "==> Installing Python dependencies..."
source .venv/bin/activate
python -m pip install -r requirements.txt

echo "==> Installing the Playwright Chromium quality-gate browser..."
python -m playwright install chromium

if [[ ! -f config.json ]]; then
  cp config.example.json config.json
fi

echo "==> Analyzing hardware and selecting the local model..."
base_model="${MODAI_BASE_MODEL:-$(python model_advisor.py --model-only)}"
echo "    Recommended/selected base model: $base_model"
echo "    Override example: MODAI_BASE_MODEL=qwen3.5:4b ./setup.sh"
ollama pull "$base_model"
generated_modelfile=".venv/MODAI.Modelfile"
python model_advisor.py --base-model "$base_model" --render "$generated_modelfile"

echo "==> Creating model mod-agent from the selected base..."
ollama create mod-agent -f "$generated_modelfile"

echo "==> Running local tests..."
python -m pytest -q

echo "==> Installing the global 'modai' command..."
./install-command.sh

echo ""
echo "Setup complete."
echo "Run:"
echo "  cd /path/to/your/project && modai"
echo ""
echo "Or one-shot:"
echo "  ./run.sh 'Create a plan for my project'"
