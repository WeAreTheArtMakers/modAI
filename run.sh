#!/bin/zsh
set -euo pipefail

# A value of 0 still enables Apple's launch-time logging hook and produces
# misleading warnings in every Python/Chromium child. Leave it truly unset.
unset MallocStackLogging MallocStackLoggingNoCompact

invocation_dir="$PWD"
launcher_name="${0:t}"
app_dir="${0:A:h}"
cd "$app_dir"

if [[ ! -x .venv/bin/python ]]; then
  echo "HATA: Sanal ortam bulunamadı. Önce ./setup.sh çalıştırın." >&2
  exit 1
fi

if [[ "$launcher_name" == "modai" ]]; then
  has_workspace=false
  for argument in "$@"; do
    if [[ "$argument" == "--workspace" || "$argument" == --workspace=* ]]; then
      has_workspace=true
      break
    fi
  done
  if [[ "$has_workspace" == false ]]; then
    exec .venv/bin/python -u orchestrator.py --workspace "$invocation_dir" "$@"
  fi
fi

exec .venv/bin/python -u orchestrator.py "$@"
