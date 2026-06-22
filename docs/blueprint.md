# ItalBizBench — Blueprint di progetto

> Il primo benchmark open-source che misura quanto bene un agente AI svolge davvero
> il lavoro fiscale-amministrativo di una PMI italiana.
>
> *Working title.* Alternative: `PMI-Bench`, `ItalAgentBench`, `FiscoBench`, `AziendaBench`.

---

## 1. In una frase

Tutti dicono che gli agenti AI "automatizzano la PMI". Nessuno misura se è vero.
ItalBizBench dà un numero: un agente messo davanti a fatture, PEC, scarti SDI e
riconciliazioni — usando gli stessi strumenti che userebbe un addetto amministrativo —
**porta a termine il lavoro correttamente? E quanto è affidabile quando non è sicuro?**

## 2. Perché questo progetto (e perché tu)

**Il gap.** Esistono benchmark generici per agenti (MCP Atlas, Tool-Decathlon, VoiceBench)
ma niente di verticale sul contesto italiano: regole IVA, reverse charge, split payment,
codice destinatario, scarti SDI, scadenze F24/LIPE, validazione P.IVA/CF. È terra di nessuno.

**Perché è difendibile (non l'ennesimo agente).** Costruire un agente di automazione lo
fanno in mille e si commoditizza in fretta. Costruire *il metro* con cui si giudicano quegli
agenti ti mette al livello sopra: diventi l'autorità neutrale. Narrativa forte per MayAI —
"quelli che misurano se un agente sa fare il lavoro di un'azienda italiana".

**Perché tu in particolare.** Il tuo background (modelli predittivi, calibrazione,
cost-aware thresholding, segmentazione) è esattamente ciò che manca alla maggior parte dei
benchmark, che si fermano a un punteggio medio senza intervalli di confidenza né analisi di
calibrazione. Qui la tua firma statistica è il fossato competitivo, non un dettaglio.

**Perché riusa ciò che hai già.** I tuoi CLI (`fatture-cli`, `pec-cli`) diventano
l'*ambiente* di test. Non parti da zero: parti dai mattoni che hai costruito.

## 3. Critica onesta / rischi da non sottovalutare

Tu mi hai chiesto di dirti quando qualcosa non ha senso. Ecco i punti dove questo progetto
può fallire, e come li gestiamo:

1. **Side effect distruttivi.** Emettere una fattura o spedire una PEC sono azioni *reali e
   irreversibili*. Il benchmark NON deve mai toccare sistemi di produzione. → Tutto gira in
   **sandbox/mock**: Fatture in Cloud ha un ambiente di test; la PEC va mockata con un server
   IMAP/SMTP finto. Regola d'oro: nessun task tocca API live.
2. **Ground truth.** Un benchmark vale quanto la sua verità di riferimento. Task con risposta
   soggettiva sono inutili. → Si ammettono solo task con **verifica deterministica**
   (la fattura prodotta ha imponibile X, aliquota Y, codice destinatario Z, esito SDI atteso).
3. **Manutenzione normativa.** Le regole fiscali cambiano: un benchmark fermo invecchia.
   Questo è un progetto *continuativo* per natura — va versionato (`v2026.1`) e aggiornato.
   È un costo, ma è anche ciò che lo tiene vivo e rilevante.
4. **Privacy.** Mai dati reali di clienti. → Solo **aziende sintetiche** generate ad hoc
   (P.IVA valide ma fittizie, anagrafiche inventate).
5. **Gaming del benchmark.** Se diventa noto, qualcuno ottimizzerà per il punteggio. → Tenere
   un **test set privato** oltre a quello pubblico (come fanno i benchmark seri).

Se uno di questi non ti convince, è il momento di dirlo prima di scrivere codice.

## 4. Tassonomia dei task (il cuore del progetto)

Sei famiglie, da semplice a complesso. Ogni task = scenario + stato iniziale sandbox +
verifica deterministica dell'esito.

| # | Famiglia | Esempi di task | Verifica |
|---|----------|----------------|----------|
| A | **Anagrafiche & validazione** | Validare P.IVA/CF, ricavare codice destinatario, normalizzare un'anagrafica cliente | Match esatto su campi |
| B | **Emissione fattura** | Emettere fattura da un ordine con reverse charge / split payment / bollo / esenzione art.10 | Imponibile, IVA, regime, totale corretti |
| C | **Gestione SDI** | Reagire a uno scarto SDI (codice errore X) correggendo e rinviando; emettere nota di credito | Esito SDI atteso, correzione giusta |
| D | **Ciclo passivo / PEC** | Leggere PEC, estrarre la fattura allegata, classificarla, registrarla nel gestionale | Documento corretto registrato |
| E | **Riconciliazione & scadenze** | Match incassi↔fatture, calcolo IVA periodo, individuare scadenze F24/LIPE | Set di match corretto, importi giusti |
| F | **Orchestrazione multi-step** | "Chiudi il mese": leggi PEC → registra passive → riconcilia → segnala insoluti | Stato finale completo e coerente |

Ogni task ha **3 livelli di difficoltà**: `base` (caso pulito), `tricky` (eccezione fiscale),
`adversarial` (dato sporco/ambiguo, dove l'agente *dovrebbe* fermarsi e chiedere conferma).

## 5. Metodologia di scoring (la tua firma)

Non un solo numero. Un **profilo** su 4 assi, perché un agente che fa il lavoro velocemente ma
emette una fattura sbagliata è peggio di uno lento e corretto.

1. **Correttezza** (deterministica): il task è andato a buon fine? Esito = atteso?
2. **Efficienza**: numero di tool-call e costo (token/€) per completare. Penalizza i giri a vuoto.
3. **Sicurezza**: ha evitato azioni irreversibili sbagliate? Sui task `adversarial`, si è fermato
   a chiedere conferma invece di tirare a indovinare? (metrica anti-allucinazione operativa)
4. **Calibrazione**: l'agente *sa* quando non sa? Confronto tra confidenza dichiarata ed
   esito reale (Brier score / curva di calibrazione — il tuo terreno).

**Statistica fatta bene** (qui ti differenzi): la leaderboard NON riporta solo punti medi ma
**intervalli di confidenza bootstrap**. Due agenti a 0.81 e 0.79 sono diversi solo se gli IC non
si sovrappongono. È esattamente la critica che i benchmark seri si fanno nel 2026: il numero medio
da solo inganna.

## 6. Architettura tecnica

```
┌─────────────────────────────────────────────────────────┐
│  ITALBIZBENCH HARNESS (Python)                            │
│                                                           │
│  tasks/*.yaml ──▶ Runner ──▶ Agent Adapter ──▶ Verifier   │
│   (scenari)                      │                │       │
│                                  ▼                ▼       │
│                           Ambiente sandbox    Scorecard    │
│                        (fatture-cli mock,    (4 assi + IC) │
│                         pec-cli mock, SDI sim)            │
└─────────────────────────────────────────────────────────┘
```

- **Task spec** in YAML/JSON: stato iniziale, prompt all'agente, oracolo di verifica.
- **Agent Adapter**: interfaccia agnostica. Funziona con qualsiasi agente MCP-capable
  (Claude, GPT, modelli locali). Tu esponi i tuoi CLI via MCP → l'agente li chiama → l'harness
  registra ogni tool-call.
- **Sandbox**: `fatture-cli` puntato all'ambiente di test di Fatture in Cloud; `pec-cli` contro
  un server IMAP/SMTP fittizio dockerizzato; un piccolo **SDI-simulator** che applica le regole
  di scarto più comuni.
- **Verifier**: funzioni Python deterministiche per task.
- **Report**: scorecard + leaderboard statica (HTML) pubblicabile su GitHub Pages.

Stack: Python 3.12, `pydantic` per gli spec, `pytest`-style runner, MCP per il collegamento agenti.

## 7. Roadmap (progetto continuativo)

**Milestone 0 — Proof of concept (un fine settimana).**
Scegli **una** famiglia (consiglio: **B, emissione fattura**) e fai 10 task `base` end-to-end:
sandbox Fatture in Cloud, adapter per un agente, verifier deterministico, scorecard con
correttezza ed efficienza. Obiettivo: dimostrare che il loop gira. Già pubblicabile come teaser.

**Milestone 1 — v0.1 pubblica (2-3 settimane part-time).**
Famiglie A+B+C, ~50 task, 3 livelli di difficoltà, i 4 assi di scoring con intervalli di
confidenza, leaderboard su GitHub Pages, README curato. → primo annuncio LinkedIn + post.

**Milestone 2 — v0.2 (continuativo).**
Famiglie D+E (PEC mock, riconciliazione), test set privato, 3-4 agenti testati a confronto,
articolo tecnico con risultati ("abbiamo testato N agenti sul lavoro di una PMI: ecco chi sbaglia
le fatture"). Questo è il contenuto che gira.

**Milestone 3 — orchestrazione (F) + community.**
Task multi-step, contributi esterni, versione normativa `v2026.x`. Diventa riferimento.

## 8. Piano di visibilità (il tuo obiettivo)

- **GitHub**: repo `mayai-it/italbizbench`, README con leaderboard live, MIT — coerente con la
  tua linea open-source.
- **Articolo lancio**: "Abbiamo dato a 4 agenti AI il lavoro di un ufficio amministrativo
  italiano. Tre hanno sbagliato l'IVA." — angolo concreto, condivisibile.
- **LinkedIn**: tu (personale) + pagina MayAI. Il formato "benchmark con classifica" genera
  discussione e ti posiziona come autorità neutrale.
- **Reddit / HN**: r/LocalLLaMA, r/AI_Agents — apprezzano benchmark verticali e riproducibili.
- **Effetto leva**: ogni nuovo modello uscito = scusa per ri-testare e ripubblicare. Contenuto
  ricorrente quasi gratis.

## 9. Prossimo passo

Se il blueprint ti convince, il passo concreto è il **Milestone 0**: ti preparo lo scaffold del
repo (struttura cartelle, formato dei task YAML, interfaccia dell'adapter, un task `base` di
esempio completo con il suo verifier) così parti col codice già impostato.

Dimmi solo se vuoi cominciare dalla famiglia **emissione fattura (B)** come suggerito o da un'altra.

---

*Fonti trend 2026: stato MCP/Linux Foundation (DualMedia, AAIF); trend agenti goal-driven
(Salesmate, mean.ceo); benchmark agenti e limiti del punteggio medio (mem0, Kili, theaiengineer);
ROI fatturazione SDI per PMI (SUPALABS, castaldosolutions).*
