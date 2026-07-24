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

**120 task** su 3 famiglie (A anagrafiche: 40, B emissione fattura: 40, C gestione
scarti SDI: 40), ciascuno con **oracolo deterministico** (niente LLM-giudice) e tre
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

Il pass-rate esce con **due intervalli di confidenza al 95%** (bootstrap e Wilson).
Con 120 task si distinguono agenti con gap ≳ 0.14; per ~10 punti servono ~300 task —
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
```

## Regole fiscali

Ogni regola applicata dalla sandbox (aliquote, reverse charge senza bollo, soglia
bollo €77,47, split payment, codici di scarto SDI, ritrasmissione, note di credito
TD04) è tracciata in [docs/FISCAL-RULES.md](docs/FISCAL-RULES.md) con fonte e stato
(✅ verificata su fonti / ⚠️ approssimazione / ❓ aperta, mai usata come oracolo).

> ⚠️ Regole verificate su fonti, non ancora asseverate da un commercialista: i numeri
> pubblicati vanno etichettati di conseguenza.

## Roadmap

In corso (v0.2): espansione famiglia C, primo run pubblicato di 3–4 agenti LLM reali,
revisione delle regole da parte di un commercialista. Poi: D (PEC/ciclo passivo),
E (riconciliazione), F (orchestrazione multi-step).

## Licenza

MIT — vedi [LICENSE](LICENSE).
