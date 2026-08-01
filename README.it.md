# italbizbench 🇮🇹

> Versione ridotta. Documentazione completa: [README.md](README.md) (inglese).

**Il benchmark che misura quanto bene un agente AI svolge davvero il lavoro fiscale e
amministrativo di una PMI italiana.**

Tutti dicono che gli agenti AI "automatizzano la PMI". Nessuno misura se è vero.
ItalBizBench mette un agente davanti a fatture, scarti SDI, reverse charge e split
payment — con gli stessi strumenti di un addetto amministrativo — e gli dà un punteggio
onesto: **porta a termine il task correttamente? E quando non è sicuro, si ferma o tira
a indovinare?**

Fa parte di [MayAI](https://mayai.it).

## In sintesi

**240 task** su 6 famiglie da 40 ciascuna (A anagrafiche, B emissione fattura,
C gestione scarti SDI, D ciclo passivo/PEC, E riconciliazione incassi,
F orchestrazione multi-step), ciascuno con **oracolo deterministico** (niente LLM-giudice) e tre
livelli di difficoltà: `base`, `tricky` (eccezione fiscale), `adversarial` (dato
sporco/ambiguo: l'agente *deve* fermarsi e chiedere).

Il punteggio è un profilo su **4 assi**:

1. **Correttezza** — l'oracolo passa? (importi, regime, esito SDI…)
2. **Efficienza** — tool-call, token consumati e **costo in euro** (tabella prezzi
   configurabile in `costs.yaml`).
3. **Sicurezza** — azioni irreversibili sbagliate penalizzate; sui task adversarial
   l'unica risposta sicura è chiedere conferma.
4. **Calibrazione** — Brier score, ECE e reliability curve sulle sole predizioni; le
   astensioni sono misurate a parte (`abstention_accuracy`), così "non fare mai nulla"
   non risulta perfettamente calibrato.

Il pass-rate esce con **due intervalli di confidenza al 95%** (bootstrap e Wilson),
e con `--trials k` anche come **pass^k** su trial ripetuti (un task "passa" solo se
passano tutti i k tentativi: misura l'affidabilità, non la fortuna del singolo run).
Governance in `BENCHMARK-CARD.md`: protocollo di astensione, policy anti-gaming e
canary anti-contaminazione in ogni file di task.
Con 240 task si distinguono agenti con gap ≳ 0.10; per ~10 punti servono ~300 task —
è scritto nel README perché nessuno legga 2 punti di differenza come un segnale.

## Regola d'oro

Il benchmark **non tocca mai API live**: tutto gira in una sandbox in-memory con
simulatore SDI. Anagrafiche **sintetiche** (P.IVA fittizie con check digit valido,
generate da `italbizbench/piva.py`): mai dati di clienti reali.

## Avvio rapido

```bash
pip install -e .
python -m italbizbench.runner tasks                     # agente reference rule-based

# Con un agente LLM reale
pip install anthropic && export ANTHROPIC_API_KEY=sk-...
python -m italbizbench.runner tasks --agent anthropic --model claude-sonnet-5

# Report JSON + leaderboard HTML statica (pronta per GitHub Pages)
python -m italbizbench.runner tasks --json --save runs/reference > /dev/null
python -m italbizbench.leaderboard runs/reference/report.json -o leaderboard.html

# Run ufficiale completo: N agenti di frontiera + pass^k + gauntlet dei modelli
# locali, con preflight e stima della spesa
./examples/run_official.sh
```

Ogni run con `--save` registra in `meta.json` **chi** ha prodotto i transcript: se poi
si rigioca la cartella (`--resume`/`--replay-only`) dichiarando un agente diverso, il
runner si ferma invece di attribuire a uno i risultati di un altro. I task rigiocati
sono contati nella scorecard (`replayed`) e la leaderboard marca quelle righe, perché
un report a zero token non passi per un run reale gratuito.

## Regole fiscali

Ogni regola applicata dalla sandbox (aliquote, reverse charge senza bollo, soglia
bollo €77,47, split payment, codici di scarto SDI, ritrasmissione, note di credito
TD04) è tracciata in [docs/FISCAL-RULES.md](docs/FISCAL-RULES.md) con fonte e stato
(✅ verificata su fonti / ⚠️ approssimazione / ❓ aperta, mai usata come oracolo).

> ⚠️ Regole verificate su fonti, non ancora asseverate da un commercialista: i numeri
> pubblicati vanno etichettati di conseguenza.

## Roadmap

Fatto (v0.2): tutte e sei le famiglie A–F a 40 task, i 4 assi con intervalli di
confidenza, pass^k, leaderboard statica, benchmark card e canary anti-contaminazione.

In corso, in ordine di priorità: **run ufficiale pulito** di 3–4 agenti di frontiera più
il gauntlet dei modelli gratuiti (nessun numero pubblicato viene ancora da un run
completo su ambiente corretto); utente simulato deterministico (`ask_user`) per i task
*chiedi-poi-agisci*; asseverazione delle regole da parte di un commercialista con
baseline umana; set privato held-out popolato. Dettaglio nel
[README in inglese](README.md#roadmap).

## Licenza

MIT — vedi [LICENSE](LICENSE).
