"""Runner: carica i task YAML, esegue un adapter, produce la scorecard.

Uso:
    python -m italbizbench.runner tasks/B-emissione
    python -m italbizbench.runner tasks/B-emissione --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .adapters import AgentAdapter, ReferenceAgent
from .costs import CostTable, compute_cost_eur, load_cost_table
from .models import AgentAction, Scenario, UsageStats, Verdict
from .sandbox import BankTransaction, Invoice, InvoicingSandbox, PecMessage, PurchaseInvoice
from .scoring import aggregate, score_task

# ID modello di default per vendor — verificati sulla documentazione ufficiale dei
# vendor il 2026-07-19. Override per run con --model, oppure stabilmente con le
# variabili d'ambiente qui sotto. Se un ID diventa stantio l'API lo rifiuta e i
# client falliscono con un messaggio chiaro (adapters/hints.py), mai in silenzio.
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5.6-sol",
    "local": "qwen2.5",
}
MODEL_ENV_VARS: dict[str, str] = {
    "anthropic": "ITALBIZBENCH_MODEL_ANTHROPIC",
    "openai": "ITALBIZBENCH_MODEL_OPENAI",
    "local": "ITALBIZBENCH_MODEL_LOCAL",
}


def resolve_model(vendor: str, cli_value: str | None,
                  env: Mapping[str, str] | None = None) -> str:
    """ID modello effettivo: --model > variabile d'ambiente > default del vendor."""
    e: Mapping[str, str] = os.environ if env is None else env
    return cli_value or e.get(MODEL_ENV_VARS[vendor], "") or DEFAULT_MODELS[vendor]


RUN_META = "meta.json"


def write_run_meta(save_dir: Path, agent_name: str, model: str | None,
                   trials: int = 1, sources: list[str] | None = None) -> None:
    """Registra in --save CHI ha prodotto i transcript di questa cartella.

    Senza questo marcatore un `--resume`/`--replay-only` lanciato con un `--agent`
    diverso attribuirebbe in SILENZIO i risultati all'agente sbagliato: il report
    porterebbe il nome dell'agente da riga di comando mentre i verdetti vengono
    dai transcript di un altro. E' esattamente il tipo di corruzione silenziosa
    che il benchmark non puo permettersi.
    """
    meta: dict[str, Any] = {"agent": agent_name, "model": model, "trials": trials}
    if sources is not None:
        meta["sources"] = sources
    (save_dir / RUN_META).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_run_meta(save_dir: Path) -> dict[str, Any] | None:
    """Provenienza dei transcript in `save_dir`; None se il marcatore non c'e'.

    Un marcatore ILLEGGIBILE non equivale a un marcatore assente: significa che
    la cartella e stata manomessa o troncata, e trattarlo come "cartella legacy"
    declasserebbe l'attribuzione in silenzio. Meglio fermarsi.
    """
    path = save_dir / RUN_META
    if not path.exists():
        return None
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path}: marcatore di provenienza illeggibile ({e}). "
                         "Rimuovilo solo se sai a chi appartengono i transcript.") from e
    if not isinstance(data, dict) or not isinstance(data.get("agent"), str) \
            or not data["agent"]:
        raise ValueError(f"{path}: marcatore di provenienza malformato "
                         "(campo 'agent' assente o non testuale).")
    return data


def has_transcripts(save_dir: Path) -> bool:
    """True se la cartella contiene almeno un transcript rigiocabile."""
    if not save_dir.is_dir():
        return False
    return any(f.name != RUN_META and not f.name.startswith("report")
               for f in save_dir.glob("*.json"))


def has_run_output(save_dir: Path) -> bool:
    """True se la cartella contiene misure di un run precedente.

    Non basta guardare i transcript: un agente che non li registra (il reference
    rule-based) lascia solo il report, che pero e' un risultato a tutti gli
    effetti e non va sovrascritto da una misura diversa.
    """
    if not save_dir.is_dir():
        return False
    return has_transcripts(save_dir) or any(save_dir.glob("report*.json"))


def load_scenarios(path: Path) -> list[Scenario]:
    files = sorted(path.rglob("*.yaml")) if path.is_dir() else [path]
    scenarios = []
    for f in files:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        scenarios.append(Scenario(**data))
    return scenarios


def load_all_scenarios(paths: Sequence[Path]) -> list[Scenario]:
    """Carica piu sorgenti di task (es. pubblici + held-out privati) con ID unici.

    Un ID duplicato tra pubblico e privato corromperebbe il confronto: meglio
    fallire subito con un messaggio esplicito.
    """
    scenarios = [sc for p in paths for sc in load_scenarios(p)]
    seen: set[str] = set()
    dups: list[str] = []
    for sc in scenarios:
        if sc.id in seen:
            dups.append(sc.id)
        seen.add(sc.id)
    if dups:
        raise ValueError(f"ID di task duplicati tra le sorgenti: {sorted(set(dups))}")
    return scenarios


def _run_usage(agent: AgentAdapter, cost_table: CostTable) -> UsageStats:
    """Usage del run appena concluso, con costo dalla tabella prezzi.

    Un agente senza tracciamento token (es. il reference rule-based) non consuma
    nulla: usage a zero e costo 0.0 — resta un punto di confronto valido e gratuito.
    """
    raw = getattr(agent, "last_usage", None)
    if raw is None:
        return UsageStats(input_tokens=0, output_tokens=0, cost_eur=0.0)
    if not isinstance(raw, UsageStats):  # adapter esotico: nessuna stima affidabile
        return UsageStats(input_tokens=0, output_tokens=0, cost_eur=None)
    model = getattr(agent, "model", None)
    cost = compute_cost_eur(raw, model if isinstance(model, str) else None, cost_table)
    return UsageStats(input_tokens=raw.input_tokens, output_tokens=raw.output_tokens,
                      cost_eur=cost)


def run(path: Path | Sequence[Path], agent: AgentAdapter, save_dir: Path | None = None,
        cost_table: CostTable | None = None,
        progress: bool = False, resume: bool = False,
        replay_only: bool = False, trials: int = 1) -> tuple[list[Verdict], dict[str, Any]]:
    paths: list[Path] = [path] if isinstance(path, Path) else list(path)
    if cost_table is None:
        cost_table = load_cost_table()
    if trials > 1 and resume:
        raise ValueError("--trials>1 non e compatibile con --resume/--replay-only")
    verdicts: list[Verdict] = []
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
    scenarios = load_all_scenarios(paths)
    # Contatore dei task rigiocati da transcript: un report con token a zero e
    # costo non stimabile deve poter essere spiegato (vedi scorecard["replayed"]).
    replay_count = [0]
    try:
        _run_scenarios(scenarios, agent, verdicts, save_dir, cost_table, progress,
                       resume=resume, replay_only=replay_only, trials=trials,
                       replay_count=replay_count)
        if replay_only and len(verdicts) < len(scenarios):
            partial = aggregate(verdicts)
            partial["partial"] = True
            partial["n_tasks_expected"] = len(scenarios)
            return verdicts, _mark_replayed(partial, replay_count[0])
    except (RuntimeError, KeyboardInterrupt) as e:
        # Un errore API (credito esaurito, rete) o un Ctrl+C a meta run non
        # devono buttare via i verdetti gia raccolti: si aggrega il parziale.
        # Il report va etichettato come parziale, mai spacciato per completo.
        # Su stderr: con --json lo stdout deve restare JSON puro e parsabile.
        print(f"\n*** RUN INTERROTTO dopo {len(verdicts)}/{len(scenarios)} task: {e}",
              file=sys.stderr, flush=True)
        partial = aggregate(verdicts)
        partial["partial"] = True
        partial["n_tasks_expected"] = len(scenarios)
        return verdicts, _mark_replayed(partial, replay_count[0])
    return verdicts, _mark_replayed(aggregate(verdicts), replay_count[0])


def _mark_replayed(scorecard: dict[str, Any], replayed: int) -> dict[str, Any]:
    """Annota quanti task vengono da transcript rigiocati (chiave assente se zero).

    I task rigiocati non ricontano token ne costo, quindi in un run misto i due
    assi coprono solo una parte dei task: i token restano come SOGLIA MINIMA
    (dichiarata da `tokens_partial`) e il costo torna non stimabile, perche un
    costo sottostimato e' un numero sbagliato, non un'approssimazione — la stessa
    regola di costs.yaml, che preferisce `null` a un prezzo inventato.
    """
    if replayed:
        scorecard["replayed"] = replayed
        scorecard["tokens_partial"] = True
        scorecard["cost_eur_total"] = None
    return scorecard


def _replay_agent(transcript_path: Path) -> AgentAdapter:
    """Agente che RIGIOCA un transcript salvato, senza chiamate API.

    Le tool call registrate vengono rieseguite in ordine sulla sandbox dal loop
    standard (ScriptedLLMClient): l'esecuzione e deterministica, quindi i verdetti
    sono identici al run originale. Token e costo del task NON vengono ricontati.
    """
    from .adapters.llm import LLMAgent, ScriptedLLMClient, ToolCall
    msgs = json.loads(transcript_path.read_text(encoding="utf-8"))
    script = [[ToolCall(**tc) for tc in m["tool_calls"]]
              for m in msgs if m.get("role") == "assistant" and "tool_calls" in m]
    return LLMAgent(ScriptedLLMClient(script), name="replay")


def _seed_sandbox(sc: Scenario) -> InvoicingSandbox:
    """Sandbox fresca seminata dallo stato iniziale dello scenario.

    Copie profonde: niente stato condiviso tra task ne tra trial ripetuti
    (update_client muta l'anagrafica) ne mutazioni degli Scenario caricati.
    """
    sandbox = InvoicingSandbox()
    for name, info in sc.initial_state.get("extra_clients", {}).items():
        sandbox.clients[name] = dict(info)
    # Famiglia C: semina le fatture gia trasmesse (es. scartate dallo SDI).
    # Non sono opera dell'agente: seeded_invoices le esclude dalle sue azioni.
    for inv in sc.initial_state.get("issued_invoices", []):
        sandbox.issued.append(Invoice(**inv))
    sandbox.seeded_invoices = len(sandbox.issued)
    # Famiglia D: semina la casella PEC e le fatture passive gia registrate.
    for msg in sc.initial_state.get("pec_inbox", []):
        sandbox.pec_inbox.append(PecMessage(**msg))
    for pur in sc.initial_state.get("purchases", []):
        sandbox.purchases.append(PurchaseInvoice(**pur))
    sandbox.seeded_purchases = len(sandbox.purchases)
    # Famiglia E: semina i movimenti bancari (estratto conto simulato).
    for tx in sc.initial_state.get("transactions", []):
        sandbox.transactions.append(BankTransaction(**tx))
    return sandbox


def _run_scenarios(scenarios: list[Scenario], agent: AgentAdapter,
                   verdicts: list[Verdict], save_dir: Path | None,
                   cost_table: CostTable, progress: bool,
                   resume: bool = False, replay_only: bool = False,
                   trials: int = 1, replay_count: list[int] | None = None) -> None:
    for i, sc in enumerate(scenarios, start=1):
        for t in range(1, trials + 1):
            sandbox = _seed_sandbox(sc)
            # --resume: se il transcript del task esiste gia, lo si rigioca offline
            # (zero API, zero costo) invece di rieseguire l'agente.
            # --replay-only: i task SENZA transcript vengono saltati (nessuna
            # chiamata API): estrae il report parziale da un run interrotto.
            task_agent = agent
            replayed = False
            if resume and save_dir is not None:
                transcript_path = save_dir / f"{sc.id}.json"
                if transcript_path.exists():
                    task_agent = _replay_agent(transcript_path)
                    replayed = True
                    if replay_count is not None:
                        replay_count[0] += 1
                elif replay_only:
                    continue
            action = task_agent.run(sc, sandbox)
            v = score_task(sc, sandbox, action,
                           usage=_run_usage(task_agent, cost_table))
            verdicts.append(v)
            if progress:
                # Feedback in tempo reale sui run lunghi (240 task con un LLM
                # reale richiedono decine di minuti): un verdetto per riga.
                mark = "PASS" if v.passed else "FAIL"
                tag = " (replay)" if replayed else ""
                trial_tag = f" t{t}/{trials}" if trials > 1 else ""
                print(f"[{i}/{len(scenarios)}{trial_tag}] [{mark}] {sc.id}{tag}",
                      flush=True)
            # Salva il transcript (riproducibilita / debug / replay). I task
            # rigiocati NON riscrivono l'originale; i trial oltre il primo
            # hanno un suffisso .trialN.
            transcript = getattr(task_agent, "last_messages", None)
            if save_dir is not None and transcript is not None and not replayed:
                suffix = f".trial{t}" if t > 1 else ""
                (save_dir / f"{sc.id}{suffix}.json").write_text(
                    json.dumps(transcript, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )


class ReplayOnlyAgent(AgentAdapter):
    """Segnaposto per `--replay-only`: porta solo il nome dell'agente originale.

    In questa modalita OGNI task viene rigiocato da transcript e i task senza
    transcript vengono saltati, quindi nessun client di vendor va costruito:
    niente SDK installato, niente chiave API, niente rete. Se qualcuno prova
    davvero a eseguirlo e' un bug dell'harness, e deve fallire forte.
    """

    def __init__(self, name: str, model: str | None = None) -> None:
        self.name = name
        self.model = model

    def run(self, scenario: Scenario, sandbox: InvoicingSandbox) -> AgentAction:
        raise RuntimeError(
            f"--replay-only: {scenario.id} non ha transcript e va saltato, non eseguito")


def _agent_label(args: argparse.Namespace) -> tuple[str, str | None]:
    """Nome (e modello) dell'agente SENZA costruirne il client.

    Serve in `--replay-only`, dove il client non va mai istanziato.
    """
    if args.agent == "reference":
        return ReferenceAgent.name, None
    model = resolve_model(args.agent, args.model)
    return f"{args.agent}:{model}", model


def _build_agent(args: argparse.Namespace) -> AgentAdapter:
    """Costruisce l'agente scelto. Import pigri: i client SDK servono solo se usati."""
    if args.agent == "reference":
        return ReferenceAgent()

    from .adapters.llm import LLMAgent
    model = resolve_model(args.agent, args.model)
    if args.agent == "anthropic":
        from .adapters.anthropic_client import AnthropicLLMClient
        return LLMAgent(AnthropicLLMClient(model=model), name=f"anthropic:{model}")
    if args.agent == "openai":
        from .adapters.openai_client import OpenAIClient
        return LLMAgent(OpenAIClient(model=model), name=f"openai:{model}")
    # local: API OpenAI-compatibile (default Ollama)
    from .adapters.openai_client import OpenAIClient
    base_url = args.base_url or "http://localhost:11434/v1"
    return LLMAgent(OpenAIClient(model=model, base_url=base_url, api_key="local"),
                    name=f"local:{model}")


def _agent_from_label(label: str, model: Any) -> tuple[str, str | None]:
    """Inverso di `_agent_label`: da "vendor:modello" a (vendor, modello).

    Serve per adottare l'etichetta registrata nel marcatore quando l'utente non
    passa `--agent`: la cartella sa gia chi l'ha prodotta, ridigitarlo e' solo
    un'occasione di sbagliare.
    """
    if ":" not in label:
        return "reference", None
    vendor, _, model_in_label = label.partition(":")
    if vendor not in DEFAULT_MODELS:
        raise ValueError(f"{RUN_META}: vendor '{vendor}' non riconosciuto in "
                         f"'{label}'")
    return vendor, (model if isinstance(model, str) and model else model_in_label)


def _sources(args: argparse.Namespace) -> list[str]:
    """Sorgenti di task del run, normalizzate e ordinate (per il marcatore)."""
    paths = [args.tasks] + ([args.private_dir] if args.private_dir else [])
    return sorted(str(Path(q)) for q in paths)


def _resolve_provenance(args: argparse.Namespace, p: argparse.ArgumentParser,
                        agent_explicit: bool) -> str:
    """Stabilisce a chi vanno attribuiti i verdetti, e come lo sappiamo.

    Ritorna l'origine dell'etichetta: `transcript-meta` (letta dal marcatore
    della cartella) o `dichiarata-da-cli` (asserita da chi lancia il comando).
    Il controllo scatta ogni volta che la cartella contiene GIA' dei transcript,
    non solo con `--resume`: anche un run nuovo su una cartella altrui ne
    riscriverebbe il marcatore, lasciando i transcript di un agente sotto il nome
    di un altro.
    """
    if args.save is None:
        return "run"
    meta = read_run_meta(args.save)
    if not has_run_output(args.save):
        # Cartella nuova (o con il solo marcatore, senza misure): niente da
        # attribuire, e nessun risultato altrui da riscrivere.
        return "run"
    if meta is None:
        # Cartella prodotta da una versione precedente dell'harness: nessun
        # marcatore. L'etichetta va DICHIARATA, non dedotta da un default.
        if not agent_explicit:
            p.error(
                f"{args.save} contiene transcript ma nessun {RUN_META}: non e "
                "possibile sapere quale agente li ha prodotti. Ripeti indicando "
                "esplicitamente --agent/--model di chi ha generato quel run."
            )
        # Su stderr: con --json lo stdout deve restare JSON puro e parsabile.
        print(f"*** ATTENZIONE: {args.save} non ha {RUN_META}; la provenienza dei "
              "transcript e' DICHIARATA da riga di comando, non verificata.",
              file=sys.stderr, flush=True)
        return "dichiarata-da-cli"

    # Marcatore presente: se l'agente non e' stato indicato lo si adotta da qui —
    # ma SOLO quando si sta riprendendo quella cartella. Adottarlo anche per un run
    # nuovo dirotterebbe un comando senza --agent (che documentiamo come reference
    # rule-based, gratuito) verso l'API a pagamento del vendore registrato.
    if not agent_explicit and args.resume:
        args.agent, model = _agent_from_label(str(meta["agent"]), meta.get("model"))
        if args.model is None:
            args.model = model
    if meta["agent"] != _agent_label(args)[0]:
        p.error(
            f"i transcript in {args.save} sono stati prodotti da "
            f"'{meta['agent']}', ma stai eseguendo con --agent "
            f"'{_agent_label(args)[0]}': il report attribuirebbe a quest'ultimo i "
            f"risultati di un altro agente. Ripeti con --agent/--model coerenti "
            f"con {args.save}/{RUN_META}, oppure usa una cartella nuova."
        )
    # Un run a k trial salva anche i transcript .trialN: rigiocarne o estenderne
    # uno con un k diverso mescolerebbe misure incomparabili nella stessa cartella.
    meta_trials = meta.get("trials", 1)
    if isinstance(meta_trials, int) and meta_trials != args.trials:
        p.error(
            f"{args.save} contiene un run a {meta_trials} trial, ma stai eseguendo "
            f"con --trials {args.trials}: i due non sono confrontabili e "
            "condividerebbero la stessa cartella. Usa una cartella nuova."
        )
    # Stessa logica per le sorgenti dei task: un run sui 240 pubblici + il set
    # privato e un run sui soli pubblici misurano cose diverse, e il secondo
    # sostituirebbe il primo senza che nulla nel report lo dica.
    meta_sources = meta.get("sources")
    if isinstance(meta_sources, list) and sorted(meta_sources) != _sources(args):
        p.error(
            f"{args.save} contiene un run sui task {sorted(meta_sources)}, ma stai "
            f"eseguendo su {_sources(args)}: misure diverse nella stessa cartella. "
            "Usa una cartella nuova."
        )
    return "transcript-meta"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ItalBizBench runner")
    p.add_argument("tasks", type=Path, help="cartella o file di task YAML")
    # default None (non "reference") per distinguere "non specificato" da "scelto
    # esplicitamente": in --replay-only su una cartella senza meta.json l'etichetta
    # dell'agente DEVE essere dichiarata, non ereditata da un default.
    p.add_argument("--agent", choices=["reference", "anthropic", "openai", "local"],
                   default=None,
                   help="agente da valutare; se omesso vale l'agente registrato in "
                        f"--save/{RUN_META}, altrimenti il reference rule-based")
    p.add_argument("--model", default=None,
                   help="ID modello LLM; se omesso vale la variabile d'ambiente "
                        "ITALBIZBENCH_MODEL_<VENDOR> o il default del vendor "
                        f"({DEFAULT_MODELS})")
    p.add_argument("--base-url", default=None,
                   help="endpoint OpenAI-compatibile (per --agent local, es. Ollama)")
    p.add_argument("--save", type=Path, default=None,
                   help="cartella dove salvare i transcript degli agenti LLM")
    p.add_argument("--costs", type=Path, default=None,
                   help="tabella costi YAML (default: costs.yaml alla radice del repo)")
    p.add_argument("--private-dir", type=Path, default=None,
                   help="cartella di task held-out privati da AGGIUNGERE ai task "
                        "pubblici (es. tasks-private/; mai committata)")
    p.add_argument("--resume", action="store_true",
                   help="riprende un run interrotto: i task con transcript gia "
                        "presente in --save vengono rigiocati offline (senza API "
                        "e senza costi); si eseguono solo i mancanti")
    p.add_argument("--replay-only", action="store_true",
                   help="come --resume ma i task senza transcript vengono SALTATI "
                        "(zero chiamate API): estrae il report parziale da un run "
                        "interrotto")
    p.add_argument("--trials", type=int, default=1,
                   help="esegue ogni task k volte e riporta pass^k (un task 'passa' "
                        "solo se passano TUTTI i k trial): misura l'affidabilita, "
                        "al costo di k volte il run. Incompatibile con --resume")
    p.add_argument("--json", action="store_true", help="output JSON")
    args = p.parse_args(argv)
    if args.trials < 1:
        p.error("--trials deve essere >= 1")
    if args.trials > 1 and (args.resume or args.replay_only):
        p.error("--trials>1 non e compatibile con --resume/--replay-only")
    if args.replay_only:
        args.resume = True
    if args.resume and args.save is None:
        p.error("--resume/--replay-only richiedono --save (la cartella con i transcript)")

    paths: list[Path] = [args.tasks]
    if args.private_dir is not None:
        if not args.private_dir.exists():
            p.error(f"--private-dir: la cartella {args.private_dir} non esiste")
        paths.append(args.private_dir)

    # Il default va risolto PRIMA di stabilire la provenienza (che confronta
    # l'etichetta effettiva col marcatore), ma "esplicito" va ricordato: e' la
    # differenza tra un agente scelto e un default ereditato.
    agent_explicit = args.agent is not None
    if args.agent is None:
        args.agent = "reference"
    try:
        label_source = _resolve_provenance(args, p, agent_explicit)
    except ValueError as e:  # marcatore illeggibile o malformato
        p.error(str(e))
        raise  # p.error non ritorna; serve solo a mypy

    agent: AgentAdapter
    if args.replay_only:
        # Nessun task verra eseguito: si evita di costruire il client di vendor
        # (che richiederebbe SDK e chiave API) per un'operazione 100% offline.
        label, model = _agent_label(args)
        agent = ReplayOnlyAgent(label, model)
    else:
        agent = _build_agent(args)

    # Il marcatore va scritto PRIMA di eseguire: un run ucciso al primo task non
    # deve lasciare transcript non attribuibili. Non si scrive un marcatore su una
    # cartella legacy (una provenienza dichiarata non diventa verificata per il solo
    # fatto di essere stata ripetuta) ne in `--replay-only`, che non produce nessun
    # transcript da attribuire.
    if args.save is not None and label_source != "dichiarata-da-cli" \
            and not args.replay_only:
        args.save.mkdir(parents=True, exist_ok=True)
        write_run_meta(args.save, agent.name, getattr(agent, "model", None),
                       args.trials, _sources(args))

    verdicts, scorecard = run(paths, agent, save_dir=args.save,
                              cost_table=load_cost_table(args.costs),
                              progress=not args.json, resume=args.resume,
                              replay_only=args.replay_only, trials=args.trials)

    if not verdicts:
        print(f"*** nessun task eseguito: {args.tasks} non ha prodotto verdetti "
              "(con --replay-only: nessun transcript corrispondente in "
              f"{args.save}). Nessun report scritto.", file=sys.stderr, flush=True)
        return 1

    report: dict[str, Any] = {
        "agent": agent.name,
        "scorecard": scorecard,
        # Un run dal vivo attribuisce per costruzione; su task rigiocati vale
        # l'origine dell'etichetta (marcatore verificato o dichiarazione a mano).
        "agent_provenance": label_source if scorecard.get("replayed") else "run",
        "verdicts": [v.model_dump(mode="json") for v in verdicts],
    }
    # Con --save il report JSON viene anche scritto su file: e l'input del
    # generatore di leaderboard (italbizbench.leaderboard). Un replay NON
    # sovrascrive il report del run dal vivo: quello e l'unico artefatto che
    # porta token e costo reali, e va conservato.
    if args.save is not None:
        name = "report-replay.json" if args.replay_only else "report.json"
        (args.save / name).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print(f"\n=== ItalBizBench — agente: {agent.name} ===")
    for v in verdicts:
        mark = "PASS" if v.passed else "FAIL"
        cal = "astensione" if v.abstained else f"brier={v.scores.brier}"
        print(f"[{mark}] {v.scenario_id:24} ({v.difficulty.value:11}) "
              f"corr={v.scores.correctness} eff={v.scores.efficiency} "
              f"saf={v.scores.safety} conf={v.confidence} {cal}  {v.detail}")
    print("\n--- Scorecard ---")
    print(f"Task: {scorecard['n_tasks']}  Pass-rate: {scorecard['pass_rate']} "
          f"(IC95% bootstrap {scorecard['correctness_ci95']}, "
          f"Wilson {scorecard['correctness_wilson_ci95']})")
    if "pass_hat_k" in scorecard:
        print(f"pass^{scorecard['trials']} su {scorecard['n_scenarios']} scenari: "
              f"{scorecard['pass_hat_k']} "
              f"(Wilson {scorecard['pass_hat_k_wilson_ci95']})")
    print(f"Efficienza media: {scorecard['efficiency_mean']}  "
          f"Sicurezza media: {scorecard['safety_mean']}")
    cost = scorecard["cost_eur_total"]
    print(f"Token: {scorecard['tokens_input_total']} in / "
          f"{scorecard['tokens_output_total']} out  "
          f"Costo: {'non stimabile' if cost is None else f'EUR {cost}'}")
    print(f"Calibrazione (su {scorecard['n_predictions']} predizioni): "
          f"Brier={scorecard['brier']}  ECE={scorecard['ece']}")
    print(f"Astensioni: {scorecard['n_abstentions']} "
          f"(accuratezza: {scorecard['abstention_accuracy']})")
    print(f"Per difficolta: {scorecard['by_difficulty']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
