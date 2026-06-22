# italbizbench 🇮🇹

> Versione ridotta. Documentazione completa: [README.md](README.md) (inglese).

**Il benchmark che misura quanto bene un agente AI svolge davvero il lavoro fiscale e
amministrativo di una PMI italiana.**

Tutti dicono che gli agenti AI "automatizzano la PMI". Nessuno misura se è vero.
ItalBizBench mette un agente davanti a fatture, scarti SDI, reverse charge e split payment —
con gli stessi strumenti di un addetto amministrativo — e gli dà un punteggio onesto:
**porta a termine il task correttamente? E quando non è sicuro, si ferma o tira a indovinare?**

Fa parte di [MayAI](https://mayai.it).

## Perché esiste

Esistono benchmark generici per agenti, ma niente di verticale sul contesto italiano: IVA,
reverse charge, split payment, codice destinatario, scarti SDI, scadenze. ItalBizBench
riempie quel vuoto e si pone come **metro neutrale**, non come l'ennesimo agente di automazione.

## Cosa lo rende diverso

La leaderboard non riporta una media e basta, ma **4 assi** (correttezza, efficienza,
sicurezza, calibrazione) e **intervalli di confidenza bootstrap**: due agenti a 0.81 e 0.79
sono "diversi" solo se gli IC non si sovrappongono.

## Regola d'oro

Il benchmark **non tocca mai API live**. Tutto gira in sandbox/mock. In produzione la sandbox
viene sostituita da `fatture-cli` puntato all'ambiente di **test** di Fatture in Cloud, mai a
quello reale. Anagrafiche **sintetiche** (P.IVA fittizie): mai dati di clienti reali.

## Avvio rapido

```bash
pip install -e .
python -m italbizbench.runner tasks
```

Con un agente LLM reale:

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-...
python -m italbizbench.runner tasks --agent llm --model claude-sonnet-4-6
```

## Famiglie di task (v0.1)

- **A — Anagrafiche**: validazione P.IVA (check digit), codice destinatario. *7 task.*
- **B — Emissione fattura**: ordinario, reverse charge, split payment PA, esente art.10,
  bollo, scarti SDI. *13 task.*

In roadmap: C (scarti SDI), D (PEC/ciclo passivo), E (riconciliazione), F (orchestrazione).

> ⚠️ Le regole fiscali nella sandbox sono una prima approssimazione, da far validare a un
> commercialista prima di annunciare numeri (roadmap v0.2).

## Licenza

MIT — vedi [LICENSE](LICENSE).
