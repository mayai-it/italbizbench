#!/usr/bin/env bash
# Run ufficiale: N agenti di frontiera sull'intera suite (240 task), piu una
# misura di affidabilita pass^k su una famiglia, piu il gauntlet dei modelli
# gratuiti. Produce DUE leaderboard: la classifica principale e quella di
# affidabilita (i report pass^k non sono confrontabili con quelli a trial unico,
# quindi non vanno nella stessa tabella).
#
# Pensato per girare di notte. Ogni run e' ripartibile: rilanciando lo script i
# task gia fatti vengono rigiocati offline (--resume) e si eseguono solo i
# mancanti. La provenienza dei transcript e' ancorata in runs/<agente>/meta.json,
# quindi un --resume con l'agente sbagliato si ferma invece di mislabellare.
#
# Uso:
#   ./examples/run_official.sh                     # lista di default
#   ./examples/run_official.sh anthropic:claude-sonnet-5 openai:gpt-5.6-sol
#   SKIP_GAUNTLET=1 ./examples/run_official.sh      # solo i frontier
#   TRIALS_FAMILY=A-anagrafiche ./examples/run_official.sh   # pass^k piu economico
#   YES=1 ./examples/run_official.sh                # niente conferma interattiva
set -euo pipefail
cd "$(dirname "$0")/.."

# Agenti di frontiera come "vendor:modello". Un agente la cui chiave API non e'
# impostata viene SALTATO con un avviso: un run notturno non deve morire per
# questo. Opzionale: anthropic:claude-opus-5 (piu caro, e il suo prezzo va prima
# aggiunto a costs.yaml, altrimenti l'asse costo resta "non stimabile").
#
# Nota su ${arr[@]+...}: bash <= 4.3 (il 3.2 di serie su macOS) considera un array
# vuoto come "unset", quindi con set -u espanderlo direttamente aborta lo script.
AGENTS=(${@+"$@"})
if [ ${#AGENTS[@]} -eq 0 ]; then
    AGENTS=(
        anthropic:claude-sonnet-5
        anthropic:claude-haiku-4-5
        openai:gpt-5.6-sol
        openai:gpt-5.6-luna
    )
fi
for spec in "${AGENTS[@]}"; do
    case "${spec}" in
        *:*) ;;
        *) echo "*** '${spec}' non e' nella forma vendor:modello"; exit 1 ;;
    esac
done

TRIALS="${TRIALS:-3}"
TRIALS_FAMILY="${TRIALS_FAMILY:-F-orchestrazione}"
TRIALS_AGENT="${TRIALS_AGENT:-${AGENTS[0]}}"

# Modelli locali del gauntlet: dichiarati QUI e passati a run_gauntlet.sh, cosi
# questo script sa esattamente quali cartelle ha prodotto.
LOCAL_MODELS=(qwen3:8b qwen2.5:7b llama3.1:8b llama3.2:3b mistral-nemo
              hermes3:8b granite3.3:8b)

# Cartelle prodotte da QUESTA invocazione: solo queste finiscono in leaderboard.
# runs/ conserva anche run vecchi (iterazioni dell'harness, prove a famiglia
# singola): pescarli con un glob metterebbe in classifica righe non confrontabili
# e numeri superati.
PRODUCED=()

key_var_for() {  # nome della variabile d'ambiente con la chiave API del vendor
    case "$1" in
        anthropic) echo "ANTHROPIC_API_KEY" ;;
        openai)    echo "OPENAI_API_KEY" ;;
        *)         echo "(nessuna)" ;;
    esac
}

# Esce 0 se la chiave del vendor MANCA. Niente espansione indiretta (${!var}):
# questo script deve girare anche con il bash 3.2 di serie su macOS.
api_key_missing() {
    case "$1" in
        anthropic) [ -z "${ANTHROPIC_API_KEY:-}" ] ;;
        openai)    [ -z "${OPENAI_API_KEY:-}" ] ;;
        *)         false ;;
    esac
}

# --- Preflight -------------------------------------------------------------
echo "=== Preflight ==="
echo "-- make check (ruff + mypy --strict + pytest): un ambiente rotto falsa i risultati"
make check >/tmp/italbizbench-check.log 2>&1 || {
    echo "*** make check NON e' verde: vedi /tmp/italbizbench-check.log"; exit 1; }
echo "   ok"

# Stima di spesa dai volumi di token OSSERVATI nel run completo piu recente.
# Serve a evitare la sorpresa a fine notte, non a essere esatta al centesimo.
python3 - "${AGENTS[@]}" <<'PY'
import glob, json, sys, pathlib
import yaml

TOK_IN, TOK_OUT, N = 749_323, 107_816, 240   # baseline: primo run completo sonnet-5
# Il run dal vivo piu ampio disponibile fa da campione dei volumi. Ordine del glob
# fissato e report illeggibili ignorati: una stima approssimativa non deve ne
# variare tra invocazioni identiche ne fare abortire la notte.
best = None
for p in sorted(glob.glob("runs/*/report.json")):
    try:
        s = json.loads(pathlib.Path(p).read_text())["scorecard"]
        assert isinstance(s, dict)
    except Exception:   # noqa: BLE001 — un report illeggibile non deve fermare la notte
        continue
    if s.get("tokens_input_total", 0) > 0 and not s.get("replayed") \
            and not s.get("partial") and isinstance(s.get("n_tasks"), int):
        if best is None or s["n_tasks"] > best[2]:
            best = (s["tokens_input_total"], s["tokens_output_total"], s["n_tasks"])
if best:
    TOK_IN, TOK_OUT, N = best
prices = yaml.safe_load(pathlib.Path("costs.yaml").read_text())["models"]
print(f"-- stima costi su {N} task (volumi osservati: "
      f"{TOK_IN:,} token in / {TOK_OUT:,} out)")
total = 0.0
unknown = []
for spec in sys.argv[1:]:
    vendor, _, model = spec.partition(":")
    p = prices.get(model)
    if not p:
        unknown.append(spec)
        print(f"   {spec:34} costo NON STIMABILE (modello assente da costs.yaml)")
        continue
    eur = TOK_IN / 1e6 * p["input_per_mtok"] + TOK_OUT / 1e6 * p["output_per_mtok"]
    total += eur
    print(f"   {spec:34} ~ EUR {eur:6.2f}")
print(f"   {'TOTALE frontier (suite piena)':34} ~ EUR {total:6.2f}")
if unknown:
    print("   NB: per gli agenti senza prezzo l'asse costo sara' 'non stimabile';")
    print("       aggiungi la voce a costs.yaml prima del run se ti serve.")
PY
echo "-- pass^${TRIALS} su ${TRIALS_FAMILY} con ${TRIALS_AGENT}: costo ~ ${TRIALS}x la"
echo "   quota di quella famiglia (1/6 della suite)"

# Conferma solo se c'e' davvero un terminale: lanciato da cron o con nohup, un
# `read` fallirebbe subito e con set -e la notte finirebbe qui senza spiegazioni.
if [ "${YES:-0}" != "1" ]; then
    if [ -t 0 ]; then
        ans=""
        read -r -p "Procedo? [s/N] " ans || true
        case "${ans}" in
            s|S) ;;
            *) echo "annullato"; exit 1 ;;
        esac
    else
        echo "*** stdin non interattivo e YES!=1: non parto senza conferma."
        echo "    Rilancia con YES=1 per un run non presidiato."
        exit 1
    fi
fi

# --- Frontier: suite piena ------------------------------------------------
for spec in "${AGENTS[@]}"; do
    vendor="${spec%%:*}"; model="${spec#*:}"
    if api_key_missing "${vendor}"; then
        echo "*** ${spec}: $(key_var_for "${vendor}") non impostata — SALTATO"
        continue
    fi
    safe="${spec//[:\/]/-}"
    echo "=== ${spec} -> runs/${safe} (240 task)"
    python3 -m italbizbench.runner tasks \
        --agent "${vendor}" --model "${model}" \
        --save "runs/${safe}" --resume \
        || echo "*** ${spec}: run interrotto, report parziale salvato"
    PRODUCED+=("runs/${safe}")
done

# --- Affidabilita: pass^k su una famiglia ---------------------------------
# --trials e' incompatibile con --resume (ogni trial deve essere indipendente),
# quindi questo run non e' ripartibile: cartella separata, mai mescolata con
# la classifica principale.
vendor="${TRIALS_AGENT%%:*}"; model="${TRIALS_AGENT#*:}"
if [ "${TRIALS}" -lt 2 ]; then
    # Con k=1 non c'e' nessun pass^k da misurare, e il report finirebbe nella
    # classifica principale come run di una sola famiglia accanto a run da 240.
    echo "=== pass^k saltato: TRIALS=${TRIALS} (serve k >= 2)"
elif ! api_key_missing "${vendor}"; then
    safe="${TRIALS_AGENT//[:\/]/-}"
    out="runs/trials${TRIALS}-${safe}-${TRIALS_FAMILY}"
    echo "=== ${TRIALS_AGENT} -> ${out} (pass^${TRIALS} su ${TRIALS_FAMILY})"
    python3 -m italbizbench.runner "tasks/${TRIALS_FAMILY}" \
        --agent "${vendor}" --model "${model}" \
        --trials "${TRIALS}" --save "${out}" \
        || echo "*** ${TRIALS_AGENT}: run pass^k interrotto, report parziale salvato"
    PRODUCED+=("${out}")
else
    echo "*** pass^k saltato: $(key_var_for "${vendor}") non impostata"
fi

# --- Gauntlet dei modelli gratuiti ---------------------------------------
if [ "${SKIP_GAUNTLET:-0}" = "1" ]; then
    echo "=== gauntlet saltato (SKIP_GAUNTLET=1)"
elif ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "*** gauntlet saltato: Ollama non risponde su :11434 (avvia 'ollama serve')"
else
    # Anche se il gauntlet esce non-zero il run e' finito: le leaderboard vanno
    # scritte comunque, non buttate via a notte conclusa.
    ./examples/run_gauntlet.sh "${LOCAL_MODELS[@]}" \
        || echo "*** gauntlet uscito con errore: uso i report che ha prodotto"
    for m in "${LOCAL_MODELS[@]}"; do PRODUCED+=("runs/${m//[:\/]/-}"); done
fi

# --- Leaderboard ----------------------------------------------------------
# Due tabelle distinte: pass-rate a trial unico e pass^k. Mescolarle darebbe
# righe non confrontabili nella stessa classifica.
main_reports=()
trial_reports=()
for dir in ${PRODUCED[@]+"${PRODUCED[@]}"}; do
    rep="${dir}/report.json"
    [ -e "${rep}" ] || continue
    # Un report illeggibile (run ucciso durante la scrittura) viene scartato con
    # un avviso: farebbe fallire il generatore e perderemmo tutte le classifiche.
    # Il percorso passa da argv, non interpolato nel sorgente Python.
    kind="$(python3 -c "
import json, sys
try:
    s = json.load(open(sys.argv[1]))['scorecard']
    print('trial' if 'pass_hat_k' in s else 'main')
except Exception:
    print('rotto')" "${rep}")"
    case "${kind}" in
        trial) trial_reports+=("${rep}") ;;
        main)  main_reports+=("${rep}") ;;
        *)     echo "*** ${rep} illeggibile: escluso dalla leaderboard" ;;
    esac
done

if [ ${#main_reports[@]} -gt 0 ]; then
    python3 -m italbizbench.leaderboard "${main_reports[@]}" -o leaderboard.html
    echo "Leaderboard principale: leaderboard.html (${#main_reports[@]} agenti)"
fi
if [ ${#trial_reports[@]} -gt 0 ]; then
    python3 -m italbizbench.leaderboard "${trial_reports[@]}" \
        -o leaderboard-affidabilita.html \
        --title "ItalBizBench — Affidabilita (pass^k)"
    echo "Leaderboard affidabilita: leaderboard-affidabilita.html (${#trial_reports[@]} run)"
fi
echo
echo "Ricordati: le righe marcate 'parziale' o 'replay' NON sono run completi e"
echo "puliti — non pubblicarle come risultato ufficiale. In particolare un run"
echo "ripreso con --resume ha il costo 'non stimabile' e i token come soglia"
echo "minima (i task rigiocati non ricontano nulla): per pubblicare gli assi di"
echo "efficienza e costo serve un run andato a termine in una sola volta."
