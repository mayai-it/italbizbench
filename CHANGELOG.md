# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/), versioning roughly
[SemVer](https://semver.org/) with dated benchmark releases planned from v1.0.

## [Unreleased]

### Fixed
- **Provenienza dei transcript: un report non puo piu attribuire a un agente i
  risultati di un altro.** `--replay-only` rigiocava i transcript salvati ma
  etichettava il report con l'agente passato da riga di comando: dimenticando
  `--agent` valeva il default, e un run reale finiva sotto il nome sbagliato con
  token a zero e costo non stimabile. E' esattamente quello che era successo a
  `runs/sonnet-5-v3` (124 task di `claude-sonnet-5` etichettati
  `reference-rulebased`). Ora ogni run con `--save` scrive `meta.json` con chi ha
  prodotto i transcript; ogni volta che la cartella ne contiene GIA' (con o senza
  `--resume`: anche un run nuovo su una cartella altrui ne riscriverebbe il
  marcatore) un agente incoerente ferma il run invece di mislabellare. Se
  `--agent` e omesso si adotta l'agente registrato nella cartella, cosi non c'e'
  piu un default che possa ri-etichettare un run. Una cartella senza marcatore
  (prodotta da un harness precedente) pretende un `--agent` esplicito e resta
  marcata come provenienza soltanto dichiarata; un marcatore illeggibile e un
  errore, non l'equivalente di un marcatore assente. La scorecard conta i task
  rigiocati (`replayed: n`) e il report dichiara sempre come e stata stabilita
  l'attribuzione (`agent_provenance`: `run`, `transcript-meta`,
  `dichiarata-da-cli`), cosi un report a zero token non passa per un run reale
  gratuito. Il report di `runs/sonnet-5-v3` e stato rigenerato dai transcript con
  l'etichetta corretta: pass-rate 0.919 invariato, come atteso da un replay
  deterministico (chiunque puo riverificarlo rigiocando quella cartella).
- **Un replay non sovrascrive piu il report del run dal vivo.** `--replay-only`
  scriveva `report.json`, cioe distruggeva l'unico artefatto con token e costo
  reali sostituendolo con uno a zero: ora scrive `report-replay.json` accanto.
- **Un run a k trial non puo piu condividere la cartella con un run a k diverso.**
  Il replay leggeva solo `{id}.json` ignorando i `{id}.trialN.json`, per cui
  rigiocare una cartella `--trials 3` la degradava in silenzio a trial singolo (e
  ne sovrascriveva il report pass^k). Il numero di trial e registrato nel
  marcatore e un k discordante ferma il run.
- **Zero verdetti non produce piu un report pubblicabile.** Un `--replay-only` su
  una cartella senza transcript corrispondenti scriveva un report con scorecard
  vuota (accettata dalla leaderboard) e poi crashava in stampa: ora esce con un
  messaggio esplicito e non scrive nulla.
- **Un run misto non riporta piu un costo sottostimato.** In un `--resume` i task
  rigiocati non consumano nulla, quindi token e costo coprivano solo una parte dei
  task e venivano pubblicati come totali del run. Ora il costo torna `null` — non
  stimabile, come per un modello assente da `costs.yaml`: un costo sottostimato e
  un numero sbagliato, non un'approssimazione — e i token sono dichiarati come
  soglia minima (`tokens_partial`), resa in leaderboard con un `≥`. Per pubblicare
  gli assi di efficienza e costo serve un run andato a termine in una volta sola.
- **Il marcatore non dirotta un run nuovo.** L'adozione dell'agente registrato
  nella cartella vale solo riprendendola (`--resume`/`--replay-only`): senza
  questo vincolo un comando senza `--agent` — documentato come reference
  rule-based, gratuito — sarebbe finito sull'API a pagamento del vendor registrato.
- **Le sorgenti dei task sono ancorate nel marcatore.** Un run sui 240 pubblici piu
  il set privato veniva sostituito senza un segnale da un run sui soli pubblici
  nella stessa cartella; ora sorgenti diverse fermano il run, come per `--trials`.
- **La protezione vale anche per gli agenti che non lasciano transcript.** Il
  reference rule-based produce solo il report: la cartella risultava "senza
  risultati" e le guardie su agente, trial e sorgenti non scattavano.
- **`--replay-only` e davvero offline.** Non costruisce piu il client del vendor
  (che pretendeva SDK installato e chiave API) per un'operazione che non fa
  nessuna chiamata: rigiocare un run e ora possibile su una macchina senza
  credenziali. Nuovo `ReplayOnlyAgent`, segnaposto che porta solo l'etichetta.
- **Leaderboard: i run non confrontabili sono marcati.** Le righe che vengono da
  un run interrotto (`parziale n/N`) o da transcript rigiocati (`replay`,
  `replay non verificato` se la provenienza e solo dichiarata) portano
  un'etichetta visibile e una legenda: prima sedevano in classifica
  indistinguibili da un run completo e pulito.
- **Leaderboard: colonna pass^k.** Su report a trial ripetuti la classifica
  espone pass^k con il suo IC di Wilson e ci si ordina; prima mostrava il solo
  pass-rate medio sui trial, cioe nascondeva proprio la metrica di affidabilita.
  Se la tabella mescola run a trial ripetuti e a trial singolo l'ordinamento resta
  sul pass-rate (un run senza pass^k non vale zero) e la pagina lo avvisa.
- **`run_gauntlet.sh` non ripesca piu i run vecchi.** Costruiva la leaderboard con
  un glob su `runs/*/report.json`, mettendo in classifica anche iterazioni
  superate dell'harness e prove su famiglia singola; ora pubblica solo le
  cartelle prodotte dal gauntlet corrente (in `leaderboard-gauntlet.html`).
- **Diagnostica su stderr.** Gli avvisi di run interrotto e di provenienza non
  verificata finivano su stdout, rompendo il JSON di `--json`.

### Added
- **`examples/run_official.sh` — il run ufficiale in un comando.** Preflight
  (`make check` verde, chiavi API presenti, stima della spesa dai volumi di token
  osservati nell'ultimo run completo), N agenti di frontiera sulla suite piena con
  `--resume`, pass^k su una famiglia, gauntlet dei modelli locali, e due
  leaderboard distinte: la classifica principale e quella di affidabilita (i
  report pass^k non sono confrontabili con quelli a trial unico). Gli agenti
  senza chiave vengono saltati con un avviso, non fanno morire il run notturno;
  in leaderboard finiscono solo le cartelle prodotte dall'invocazione corrente.
- **pass^k su trial ripetuti (`--trials k`).** Un task "passa^k" solo se passano
  tutti i k trial (stile tau-bench): misura l'affidabilità, motivata dalla varianza
  osservata tra run reali identici. In scorecard: `trials`, `n_scenarios`,
  `pass_hat_k` con IC di Wilson.
- **Benchmark card e canary anti-contaminazione.** `BENCHMARK-CARD.md` (scopo,
  costruzione, protocollo di astensione, policy anti-gaming, come riportare i
  risultati, limiti noti) e canary GUID in ogni file di task, con test
  d'invarianza. Primo run LLM reale documentato: sonnet-5, due iterazioni di
  harness-fixing (0.75 → 0.975 sulla famiglia A; 0.782 → 0.919 sulle stesse 124
  task della suite piena), quattro difetti d'ambiente trovati dall'agente.
- **Resilienza dei run reali:** progress in tempo reale, retry con backoff,
  report parziale su interruzione, `--resume` (rigioca i transcript offline,
  esegue solo i mancanti) e `--replay-only` (estrae il report parziale senza
  chiamate API).
- **Famiglia F — orchestrazione multi-step: 40 task (13 base, 16 tricky, 11
  adversarial), suite totale a 240.** Ogni scenario compone 2+ passi sulle capacita
  B/C/D/E (emissione+incasso, correzione scarto+registrazione passiva, nota di
  credito+riconciliazione, censimento PA+abbinamento per importo univoco...); il
  verifier giudica lo STATO FINALE della sandbox combinando tutti gli oracoli
  dichiarati, non i singoli passi. Nuovo campo `Scenario.expected_tool_calls`
  (default 3, retro-compatibile): l'asse efficienza usa un budget per-task, cosi i
  multi-step non sono penalizzati strutturalmente. Trappole adversarial in cui UN
  solo passo ambiguo (bonifico cumulativo, passiva incoerente, "chiudi il mese"
  senza dettagli, richiesta di alterare l'IVA) deve fermare l'intera sequenza:
  eseguire anche solo il passo chiaro e un errore di sicurezza. Reference agent a
  passi sequenziali; prompt di sistema LLM aggiornato.
- **Famiglie D ed E a regime: 40 task ciascuna (13 base, 16 tricky, 11 adversarial),
  suite totale a 200.** D: aliquote miste per riga (IVA arrotondata al centesimo),
  esente con bollo nel totale documento (soglia 77,47/77,48), fornitori esteri,
  numeri simili/alfanumerici, mittenti terzi, casella affollata; trappole con totali
  incoerenti, allegato mancante, duplicati gia a registro, fatture annullate,
  richieste di alterare l'IVA, PEC sospette. E: abbinamento per numero anche con
  causali compattate/sporche, importo univoco a causale muta, split payment e
  reverse charge all'incasso, esente con bollo, estratti conto affollati; trappole
  con bonifici cumulativi/parziali, importi uguali, eccedenze, pagatori terzi,
  causali contraddittorie. Invarianti del task set estesi a tutte e cinque le
  famiglie (5x40, bilanciamento difficolta).
- **Famiglia E — riconciliazione incassi (scaffold, 8 task base).** Estratto conto
  simulato (`BankTransaction`, tool `list_transactions`) e abbinamento
  movimento↔fattura per numero documento (`Reconciliation`, tool `reconcile`, che
  marca la fattura incassata; `list_open_invoices` per le fatture aperte). `Invoice`
  guadagna `numero` e `paid` (default retro-compatibili). Verifier E: match ESATTO
  dell'insieme degli abbinamenti — un abbinamento indebito fallisce quanto uno
  mancante (`expected_reconciliations`). Task base: causale con numero, causale
  generica con importo univoco, split payment (la PA paga il solo imponibile),
  esente con bollo nel totale, uscite da ignorare, due fatture aperte dello stesso
  cliente. Regola §11 in FISCAL-RULES (⚠️ approssimazioni: incassi parziali/cumulativi,
  scadenze e liquidazioni non modellati). Nuovi tool esposti anche all'agente LLM.
- **Famiglia D — ciclo passivo via PEC (scaffold, 8 task base).** Casella PEC simulata
  (`PecMessage`, tool `list_pec`/`read_pec`: l'elenco non espone gli allegati, il
  documento va aperto) e registro acquisti (`PurchaseInvoice`, tool
  `register_purchase`: la registrazione REPLICA i dati del documento, nessun
  ricalcolo). Verifier D: l'ultima fattura passiva registrata deve combaciare con il
  documento ricevuto (`expected_purchase`). Task base: multi-aliquota 4/10/22%,
  esente N4, decimali, rumore in casella, due fatture dello stesso fornitore.
  Semina di `pec_inbox`/`purchases` dallo stato iniziale (`seeded_purchases` esclude
  i documenti seminati dalle azioni dell'agente, come per la famiglia C). Regola §10
  in FISCAL-RULES (⚠️ approssimazioni dichiarate: parsing XML FatturaPA fuori
  perimetro, detraibilità art. 19, TD16–TD19 e termini art. 25 non modellati).
  Nuovi tool esposti anche all'agente LLM.
- **Famiglia C a regime: 40 task (13 base, 16 tricky, 11 adversarial).** Aggiunti 32
  task al scaffold: ritrasmissioni con eccezioni fiscali (esente con soglia bollo
  77,47/77,48, reverse charge, split payment PA, flag estero mancante, censimento PA
  su 00200, doppio errore P.IVA+codice, arrotondamenti su quantità decimali) e note
  di credito TD04 (reverse charge, esente sopra soglia bollo, parziale multi-aliquota,
  split payment, quantità frazionarie). 11 trappole adversarial (codici destinatario
  contraddittori, censimento senza dati, fattura da stornare ambigua, ritrasmissione
  forzata senza correzione, importi "circa", codice di scarto sconosciuto, omonimi,
  P.IVA a 10 cifre, riga non identificata, istruzione invalida, doppio storno).
  Oracoli generati programmaticamente con le stesse regole di calcolo della sandbox
  (nessun importo scritto a mano). Invarianti del task set estesi alla famiglia C
  (conteggio 40, bilanciamento difficoltà).
- **Famiglia C — gestione scarti SDI (scaffold, 8 task base).** Ciclo
  scarto→correzione→ritrasmissione (00312 su privati e PA, 00200 con censimento
  cliente, esente con bollo) e note di credito TD04 (storno totale, parziale, su
  split payment). Sandbox: `update_client`, `add_client`, `emit_credit_note` (importi
  calcolati con le stesse regole della fattura, `CreditNote` transita dallo SDI),
  semina di fatture già trasmesse via `initial_state.issued_invoices`
  (`seeded_invoices` esclude i documenti seminati dalle azioni dell'agente).
  Verifier C: anagrafica corretta (`expected_client_update`), ultima fattura
  ritrasmessa, ultima nota di credito (`expected_credit_note`). Regole §8–§9 in
  FISCAL-RULES (⚠️ approssimazioni dichiarate: finestra 5 giorni, art. 26 non
  modellati). Nuovi tool esposti anche all'agente LLM.

### Fixed
- **Isolamento delle sandbox:** `update_client` mutava i dict condivisi di
  `DEFAULT_CLIENTS` (copia shallow), facendo colare lo stato tra un task e l'altro.
  Ora ogni sandbox parte da copie profonde (regression test incluso).
- **Test set privato (held-out).** Cartella `tasks-private/` esclusa da git (committato
  solo il README con le regole), stesso formato dei task pubblici; il runner la aggiunge
  con `--private-dir` e **rifiuta ID duplicati** tra sorgenti. I risultati pubblicati
  devono dichiarare se includono il set privato.
- **ID modello configurabili e robusti.** Default per vendor in `runner.DEFAULT_MODELS`
  — aggiornati e verificati sulla documentazione ufficiale dei vendor il 2026-07-19
  (`claude-sonnet-5`, `gpt-5.6-sol`, `qwen2.5`) — con override via `--model` o variabili
  d'ambiente `ITALBIZBENCH_MODEL_*`. Se l'API rifiuta l'ID modello o l'endpoint non è
  raggiungibile, i client falliscono subito con un messaggio operativo
  (`adapters/hints.py`), mai default silenziosi e stantii. `costs.yaml` aggiornato ai
  listini correnti (conversione 1 USD ≈ 0,876 EUR al 2026-07-19).
- **Generatore di leaderboard statica** (`italbizbench/leaderboard.py`, entry point
  `italbizbench-leaderboard`): legge N `report.json` del runner (uno per agente) e
  produce una pagina HTML self-contained pronta per GitHub Pages — tabella pass-rate
  con IC bootstrap+Wilson, 4 assi, token/costo, breakdown per difficoltà e reliability
  curve per agente (SVG inline). Niente JavaScript né risorse esterne, light/dark,
  deterministica (stesso input → stessi byte). Con `--save` il runner ora scrive anche
  il report JSON completo (`report.json`), input della leaderboard.
- **Task set espanso: 20 → 80 task** (40 famiglia A, 40 famiglia B), bilanciati per
  difficoltà (A: 14 base / 15 tricky / 11 adversarial; B: 13 / 16 / 11). Nuovi casi:
  tutte le aliquote (4/5/10/22), quantità frazionarie e arrotondamenti, confine
  dell'imposta di bollo (77,47 vs 77,48), esente multi-riga, seconda PA in split
  payment, scarti SDI aggiuntivi (00312 su PA e privati, 00200), P.IVA trasposte /
  repdigit / con zero iniziale / estere, e 18 nuovi task adversarial (istruzioni a
  forzare l'esito, valuta estera, omonimi, dati mancanti).
- `italbizbench/piva.py`: helper unico per check digit e **generazione di P.IVA
  sintetiche valide** (basi arbitrarie o RNG seedato); la sandbox ora delega qui la
  validazione. Regole e confini documentati in `docs/FISCAL-RULES.md`.
- **IC di Wilson** accanto al bootstrap (`correctness_wilson_ci95`): formula chiusa,
  non degenera a (p, p) sulle proporzioni estreme. README: tabella di potenza
  statistica (quanti task servono perché gli IC discriminino due agenti).
- Test nuovi: invarianti del task set (conteggi, bilanciamento, oracoli P.IVA coerenti
  con l'algoritmo, convenzione ambiguous↔should_ask), helper P.IVA, Wilson a mano.
- **Efficienza con costo reale (token + €).** `LLMResponse` cattura l'usage di token
  riportato dall'API (Anthropic: `input/output_tokens`; OpenAI-compat:
  `prompt/completion_tokens`, assente su alcuni server locali); `LLMAgent` lo accumula
  per run (azzerato a ogni task, contato anche il turno di `finish`). La scorecard
  riporta `tokens_input_total`, `tokens_output_total` e `cost_eur_total` calcolato da
  una **tabella prezzi configurabile** (`costs.yaml`, override con `--costs`). Modello
  non in tabella → costo `null` ("non stimabile"), mai un prezzo inventato. Il
  reference agent resta una baseline valida a costo 0. Test con usage mockato,
  senza rete (`tests/test_costs.py`).

### Changed
- **Calibrazione vera al posto del placeholder.** L'asse calibrazione non è più la media
  di |confidenza − esito|: la scorecard riporta **Brier score**, **ECE** (Expected
  Calibration Error su 10 bin di uguale ampiezza) e i dati completi della **reliability
  curve** (confidenza media vs accuratezza per bin). Per task, `AxisScores.brier` è il
  contributo (p − y)².
- **Le astensioni non sono predizioni a confidenza 0.** Chiedere conferma senza agire è
  un rifiuto di predire: escluso da Brier/ECE e misurato a parte con
  `abstention_accuracy` (quota di astensioni avvenute dove astenersi era corretto).
  Chiude il buco per cui un agente che non faceva nulla con confidenza 0 otteneva
  calibrazione "perfetta". Chi invece agisce su un task ambiguo entra nel pool con
  esito 0: la sovraconfidenza resta punita.
- `Verdict` espone `confidence` (clampata in [0, 1]) e `abstained`; `aggregate()` riporta
  `brier`, `ece`, `reliability_bins`, `n_predictions`, `n_abstentions`,
  `abstention_accuracy`.

### Fixed
- **Reverse charge non sconta l'imposta di bollo** (principio di alternatività IVA/bollo):
  rimosso il bollo €2 erroneamente applicato (oracoli B-002, B-009 corretti).
- Rimosso l'uso improprio del codice SDI `00400` per "PA senza split payment" (lo split
  payment non è un controllo di scarto SDI).

### Added
- `docs/FISCAL-RULES.md`: ogni regola fiscale tracciata con fonte e stato di validazione.
- Adapter **OpenAI-compatibile** (`openai_client.py`): un solo client per GPT e per modelli
  locali (Ollama / llama.cpp / vLLM) cambiando `--base-url`.
- Runner: opzioni `--agent {reference,anthropic,openai,local}`, `--base-url`, `--save`
  (salvataggio transcript per riproducibilita).
- Hardening: gestione errori sulle tool-call (argomenti malformati non interrompono il run).

## [0.1.0] — 2026-06-21

### Added
- Benchmark harness: `Scenario` / `Oracle` / `Verdict` models, recursive task runner,
  deterministic per-family verifier.
- Invoicing **sandbox** with an **SDI simulator** (no live APIs; synthetic clients).
- Scoring on **4 axes** (correctness, efficiency, safety, calibration) with **bootstrap
  confidence intervals** on the pass-rate.
- **20 tasks** across two families on 3 difficulty tiers:
  - Family **A — Anagrafiche** (7): P.IVA check-digit validation, recipient code lookup.
  - Family **B — Emissione** (13): ordinary, reverse charge, split payment (PA), exempt
    art.10, stamp duty, SDI rejections, adversarial cases.
- **Reference rule-based agent** (baseline) and a vendor-agnostic **LLM tool-use adapter**
  with an Anthropic client and a `ScriptedLLMClient` for offline tests.
- Project tooling: `ruff`, `mypy --strict`, `pytest`, `Makefile`, CI on Python 3.11–3.13.

### Notes
- Fiscal rules in the sandbox are a first approximation, pending review by an accountant
  before any results are published.

[0.1.0]: https://github.com/mayai-it/italbizbench/releases/tag/v0.1.0
