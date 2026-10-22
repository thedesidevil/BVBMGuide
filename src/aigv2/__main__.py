import json
from pathlib import Path
from typing import Optional

import typer

from src.aigv2 import pipeline
from src.aigv2.intake.template import build_template
from src.aigv2.preflight import PreflightStop
from src.aigv2.store import RunStore

app = typer.Typer(name="aigv2", help="AIG v2: build and QC All Inclusive Guides", no_args_is_help=True)


def _path(store: RunStore, name: str) -> str:
    base = getattr(store.backend, "base_path", None)
    return str(Path(base) / store.key(name)) if base is not None else store.key(name)


def _store(deps, run_id: str) -> RunStore:
    store = RunStore(deps.backend, run_id)
    if not store.has("trip_plan.json"):
        typer.echo(f"Run {run_id} not found")
        raise typer.Exit(1)
    return store


def _print_qc(qc) -> None:
    typer.echo(f"QC: {'PASS' if qc.passed else 'FAIL'}")
    typer.echo(f"Markers: {qc.marker_count}")
    typer.echo(f"Findings: {len(qc.findings)}")


def _print_build(store: RunStore, result) -> None:
    typer.echo(f"Run id: {store.run_id}")
    typer.echo(f"Guide: {_path(store, 'guide.docx')}  (save as: {result.docx_name})")
    typer.echo(f"QC report: {_path(store, 'qc_report.md')}")
    typer.echo(f"Verification sheet: {_path(store, 'verification.xlsx')}")
    typer.echo(f"Cost log: {_path(store, 'cost.json')}")
    _print_qc(result.qc)
    typer.echo(pipeline.cost_summary(result.cost))


def _build_errors(fn):
    try:
        return fn()
    except pipeline.UnansweredQuestions as e:
        typer.echo("These questions still need an answer:")
        for q in e.questions:
            typer.echo(f"  [{q.id}] {q.text}")
        raise typer.Exit(1)
    except (PreflightStop, ValueError) as e:
        _failed(e)
    except Exception as e:
        _failed(e, f"{type(e).__name__}: ")


def _failed(e: Exception, prefix: str = ""):
    typer.echo(f"FAILED: {prefix}{e}")
    cost = getattr(e, "run_cost", None)
    if cost is not None:
        typer.echo(f"Run id: {e.run_id}")
        typer.echo(pipeline.cost_summary(cost))
    raise typer.Exit(1)


@app.command()
def template(out: Path = typer.Argument(..., help="Where to write the intake template .docx")):
    """Write the blank intake template."""
    build_template(out)
    typer.echo(f"Template: {out}")


@app.command()
def start(attachments: Optional[list[Path]] = typer.Argument(None, help="Attachment files"),
          intake: Optional[Path] = typer.Option(None, "--intake", help="Filled intake template .docx")):
    """Read inputs, extract the trip and list the pre-flight questions."""
    deps = pipeline.default_deps()
    store, questions = _build_errors(lambda: pipeline.start_run(intake, list(attachments or []), deps))
    typer.echo(f"Run id: {store.run_id}")
    if questions:
        typer.echo(f"Questions ({len(questions)}):")
        for i, q in enumerate(questions, 1):
            typer.echo(f"  {i}. [{q.id}] {q.text}")
            if q.options:
                typer.echo(f"     options: {' | '.join(q.options)}")
        typer.echo(f"Answers template: {_path(store, 'answers.template.json')}")
    else:
        typer.echo("No questions.")
    typer.echo(f"Trip plan: {_path(store, 'trip_plan.json')}")
    typer.echo(pipeline.cost_summary(store.load_json("cost.json")))


@app.command()
def build(run_id: str, answers: Path = typer.Option(..., "--answers", help='JSON {"question_id": "answer"}')):
    """Build the guide, run QC and write the verification sheet."""
    deps = pipeline.default_deps()
    store = _store(deps, run_id)
    data = json.loads(answers.read_text(encoding="utf-8"))
    _print_build(store, _build_errors(lambda: pipeline.build_run(store, data, deps)))


@app.command()
def regenerate(run_id: str, day: list[int] = typer.Option([], "--day", help="Day number to rewrite"),
               section: list[str] = typer.Option([], "--section", help="Section key to rewrite")):
    """Rewrite chosen days/sections, re-render and re-run QC (previous outputs kept as .vN)."""
    deps = pipeline.default_deps()
    store = _store(deps, run_id)
    _print_build(store, _build_errors(lambda: pipeline.regenerate(store, list(day), list(section), deps)))


@app.command()
def qc(edited: Path = typer.Argument(..., help="Edited guide .docx"),
       run: str = typer.Option(..., "--run", help="Run id the guide came from (required: QC needs its trip plan)")):
    """Re-run QC on an edited guide."""
    deps = pipeline.default_deps()
    store = _store(deps, run)
    meter = pipeline.CostMeter(deps)
    out, result, report = _build_errors(lambda: pipeline.requalify(store, edited, deps))
    cost = meter.cost()
    stem = edited.with_suffix("")
    paths = {"doc": Path(f"{stem}.qc.docx"), "report": Path(f"{stem}.qc_report.md"), "cost": Path(f"{stem}.cost.json")}
    paths["doc"].write_bytes(out)
    paths["report"].write_text(report, encoding="utf-8")
    paths["cost"].write_text(json.dumps(cost, indent=2), encoding="utf-8")
    typer.echo(f"Annotated guide: {paths['doc']}")
    typer.echo(f"QC report: {paths['report']}")
    typer.echo(f"Cost log: {paths['cost']}")
    _print_qc(result)
    typer.echo(pipeline.cost_summary(cost))


if __name__ == "__main__":
    app()
