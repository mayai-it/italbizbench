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
from .models import Scenario, UsageStats, Verdict
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
    try:
        _run_scenarios(scenarios, agent, verdicts, save_dir, cost_table, progress,
                       resume=resume, replay_only=replay_only, trials=trials)
        if replay_only and len(verdicts) < len(scenarios):
            partial = aggregate(verdicts)
            partial["partial"] = True
            partial["n_tasks_expected"] = len(scenarios)
            return verdicts, partial
    except (RuntimeError, KeyboardInterrupt) as e:
        # Un errore API (credito esaurito, rete) o un Ctrl+C a meta run non
        # devono buttare via i verdetti gia raccolti: si aggrega il parziale.
        # Il report va etichettato come parziale, mai spacciato per completo.
        print(f"\n*** RUN INTERROTTO dopo {len(verdicts)}/{len(scenarios)} task: {e}",
              flush=True)
        partial = aggregate(verdicts)
        partial["partial"] = True
        partial["n_tasks_expected"] = len(scenarios)
        return verdicts, partial
    return verdicts, aggregate(verdicts)


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
                   trials: int = 1) -> None:
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ItalBizBench runner")
    p.add_argument("tasks", type=Path, help="cartella o file di task YAML")
    p.add_argument("--agent", choices=["reference", "anthropic", "openai", "local"],
                   default="reference", help="agente da valutare (default: reference rule-based)")
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

    agent: AgentAdapter = _build_agent(args)
    verdicts, scorecard = run(paths, agent, save_dir=args.save,
                              cost_table=load_cost_table(args.costs),
                              progress=not args.json, resume=args.resume,
                              replay_only=args.replay_only, trials=args.trials)

    report = {
        "agent": agent.name,
        "scorecard": scorecard,
        "verdicts": [v.model_dump(mode="json") for v in verdicts],
    }
    # Con --save il report JSON viene anche scritto su file: e l'input del
    # generatore di leaderboard (italbizbench.leaderboard).
    if args.save is not None:
        (args.save / "report.json").write_text(
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
