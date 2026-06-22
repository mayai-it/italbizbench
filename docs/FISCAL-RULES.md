# Regole fiscali del benchmark — fonti e stato di validazione

> **Perché questo documento.** Un benchmark vale quanto i suoi oracoli. Qui ogni regola
> applicata dalla sandbox è tracciata con la sua fonte e uno **stato**. In assenza di
> asseverazione da parte di un commercialista, lo stato massimo è `verificato su fonti`:
> i numeri pubblicati vanno etichettati di conseguenza.

Stati possibili:

- ✅ `verificato su fonti` — coerente con normativa / prassi citata.
- ⚠️ `approssimazione` — semplificazione consapevole, accettabile per il benchmark ma non
  fiscalmente completa.
- ❓ `aperto` — caso dubbio o contestato, non ancora modellato; non usato come oracolo.

---

## 1. Validazione P.IVA (famiglia A)

**Regola.** P.IVA italiana = 11 cifre; l'11ª è un check digit calcolato con algoritmo di
Luhn (somma cifre posizioni dispari + cifre posizioni pari raddoppiate con riporto, check =
`(10 − somma mod 10) mod 10`). Le P.IVA con prefisso non numerico (es. `DE…`) non seguono
questo algoritmo → non validabili con questo metodo.

**Stato:** ✅ `verificato su fonti` — algoritmo standard documentato (Agenzia delle Entrate,
art. di calcolo del codice di controllo della partita IVA).

## 2. Aliquote IVA (famiglia B)

**Regola.** Ordinaria 22%, ridotte 10% / 5% / 4%. La sandbox calcola l'IVA per riga
sull'aliquota indicata. Niente arrotondamenti esotici: `round(imponibile × aliquota/100, 2)`.

**Stato:** ✅ `verificato su fonti` — aliquote vigenti (DPR 633/1972).

## 3. Reverse charge / inversione contabile — NIENTE bollo

**Regola.** Sulle operazioni in reverse charge l'IVA non è esposta in fattura ma l'operazione
**resta soggetta a IVA** (assolta dal committente). Per il **principio di alternatività
IVA/imposta di bollo**, il bollo da €2 **non è dovuto**, nemmeno sopra €77,47.

**Stato:** ✅ `verificato su fonti`
[Fiscomania](https://fiscomania.com/fattura-in-reverse-charge/),
[RegimeMinimi](https://www.regimeminimi.com/fattura-reverse-charge-esempio-e-regole-sul-bollo/).
*(Corretto in v0.1: la versione iniziale applicava erroneamente il bollo — vedi CHANGELOG.)*

## 4. Imposta di bollo su operazioni esenti art.10 — €2 sopra €77,47

**Regola.** Le fatture per operazioni esenti IVA ex art.10 DPR 633/1972 (prestazioni
sanitarie, educative, ecc.) scontano l'imposta di bollo di €2 se l'importo supera €77,47.
Sotto soglia, niente bollo. Il bollo è a carico di chi emette la fattura.

**Stato:** ✅ `verificato su fonti`
[Agenzia delle Entrate](https://www.agenziaentrate.gov.it/portale/integrazione-del-bollo-sulle-fatture-elettroniche).

## 5. Split payment (scissione dei pagamenti) verso PA

**Regola.** Nelle fatture in split payment alla PA l'IVA è esposta ma versata all'Erario dal
committente pubblico: il cliente paga al fornitore il solo imponibile. La sandbox imposta
quindi `totale a carico cliente = imponibile (+ bollo se dovuto)`, pur registrando l'IVA.

**Stato:** ⚠️ `approssimazione` — corretta nella sostanza (art. 17-ter DPR 633/1972), ma la
modellazione di chi versa cosa è semplificata. Da rivedere se si aggiungono task sui
versamenti.

## 6. Esiti SDI simulati (codici di scarto)

La sandbox simula un sottoinsieme **didattico** dei controlli SDI.

| Codice | Significato (fonte) | Uso nel benchmark | Stato |
|---|---|---|---|
| `accettata` | trasmissione ok | esito atteso dei casi validi | ✅ |
| `00312` | codice destinatario non valido / non attivo su IPA | codice destinatario di lunghezza errata (privato ≠ 7, PA ≠ 6 char) | ✅ verificato su fonti |
| `00200` | file non conforme / dato obbligatorio non conforme o mancante | destinatario non in anagrafica (dato obbligatorio mancante) | ⚠️ approssimazione |

Fonte: [FAQ errori frequenti fatturapa.gov.it](https://www.fatturapa.gov.it/it/faq/FAQ-Errori-frequenti/),
[elenco codici errore SdI (AE)](https://assistenza.agenziaentrate.gov.it/KnowledgeBases2/FattElettr/attach/InviaFattura/Elenco_Codici_errore_SdI.pdf).

> Nota: il codice `00400` (calcolo IVA non valido) **non** è più usato per "PA senza split
> payment": era un uso improprio, rimosso in v0.1. Lo split payment è materia di contenuto
> fattura, non un controllo di scarto SDI.

## 7. Lunghezza codice destinatario

**Regola.** Privati: 7 caratteri alfanumerici. PA: 6 caratteri (codice univoco ufficio,
IPA). Estero: codice convenzionale `XXXXXXX` (7 X).

**Stato:** ✅ `verificato su fonti` — specifiche FatturaPA.

---

## Questioni aperte (❓ — non modellate, non usate come oracolo)

- **Territorialità intra-UE (art. 7-ter).** Le prestazioni B2B intra-UE sono "fuori campo IVA"
  in Italia: il trattamento ai fini del bollo è più sfumato del semplice "reverse charge".
  Il task B-009 è modellato come reverse charge puro (niente bollo); la sfumatura territoriale
  è volutamente non coperta.
- **Operazioni non imponibili (art. 8, 8-bis, 9 — export/cessioni intra).** Anch'esse nel
  perimetro del bollo €2 > €77,47, ma non ancora presenti come famiglia di task.
- **Note di credito, autofattura, regime forfettario.** In roadmap (famiglia C e oltre).

---

*Ultimo aggiornamento: v0.1. Le regole vanno riviste a ogni cambiamento normativo
(versionamento `v2026.x` previsto da v1.0) e idealmente asseverate da un commercialista
prima di pubblicare una leaderboard ufficiale.*
