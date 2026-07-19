# Test set privato (held-out)

Questa cartella ospita i task **privati** del benchmark: stesso formato YAML dei task
pubblici in `tasks/`, ma **mai committati** (il `.gitignore` esclude tutto tranne questo
README). Servono da controllo anti-gaming: se un agente va molto meglio sui task
pubblici che su quelli privati, sta overfittando il benchmark (vedi blueprint, §3.5).

Regole:

- **Non committare i task privati.** Restano su macchine locali / storage privato del
  maintainer. Qualunque PR che aggiunge YAML qui dentro va rifiutata.
- **Stesso formato e stesse regole dei task pubblici**: oracolo deterministico, dati
  sintetici (P.IVA generate con `italbizbench.piva`), regole fiscali tracciate in
  `docs/FISCAL-RULES.md`.
- **ID univoci** con prefisso dedicato (consiglio: `AP-`/`BP-` invece di `A-`/`B-`):
  il runner rifiuta ID duplicati tra sorgenti.
- I risultati pubblicati devono dichiarare se includono il set privato.

Esecuzione (aggiunge i privati ai pubblici):

```bash
python -m italbizbench.runner tasks --private-dir tasks-private --json --save runs/x
```
