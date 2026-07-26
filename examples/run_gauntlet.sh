#!/usr/bin/env bash
# Gauntlet di agenti gratuiti: fa girare in sequenza N modelli locali (Ollama)
# sull'intera suite e genera la leaderboard unica. Pensato per girare di notte.
#
# Prerequisiti: `brew install ollama` e `ollama serve` attivo.
# Uso:
#   ./examples/run_gauntlet.sh                  # tutti i modelli di default
#   ./examples/run_gauntlet.sh qwen3:8b         # solo alcuni
#
# I modelli piccoli andranno male: e' il punto — lo spread in leaderboard
# dimostra che il benchmark discrimina. Ogni run e' ripartibile con --resume.
set -euo pipefail
cd "$(dirname "$0")/.."

MODELS=("$@")
if [ ${#MODELS[@]} -eq 0 ]; then
    MODELS=(qwen3:8b qwen2.5:7b llama3.1:8b llama3.2:3b mistral-nemo hermes3:8b granite3.3:8b)
fi

for model in "${MODELS[@]}"; do
    safe_name="${model//[:\/]/-}"
    echo "=== ${model} -> runs/${safe_name}"
    ollama pull "${model}"
    python3 -m italbizbench.runner tasks \
        --agent local --model "${model}" \
        --save "runs/${safe_name}" --resume \
        || echo "*** ${model}: run interrotto, report parziale salvato"
done

# Leaderboard unica con tutti i report disponibili (anche di run precedenti).
reports=(runs/*/report.json)
python3 -m italbizbench.leaderboard "${reports[@]}" -o leaderboard.html
echo "Leaderboard scritta in leaderboard.html (${#reports[@]} agenti)"
