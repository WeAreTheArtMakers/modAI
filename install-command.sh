#!/bin/zsh
set -euo pipefail

app_dir="${0:A:h}"
bin_dir="${MODAI_BIN_DIR:-${HOME}/.local/bin}"
launcher="$bin_dir/modai"

mkdir -p "$bin_dir"
ln -sfn "$app_dir/run.sh" "$launcher"

echo "MODAI komutu kuruldu: $launcher"
if (( ! ${path[(Ie)$bin_dir]} )); then
  echo "UYARI: $bin_dir PATH içinde değil. ~/.zprofile dosyanıza şunu ekleyin:"
  echo "  export PATH=\"$bin_dir:\$PATH\""
fi
echo "Herhangi bir proje klasöründe çalıştırabilirsiniz:"
echo "  cd /proje/klasoru"
echo "  modai"
