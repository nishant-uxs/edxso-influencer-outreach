"""CLI entrypoint."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from influencer_outreach.config import get_settings
from influencer_outreach.pipeline.runner import OutreachPipeline
from influencer_outreach.utils import setup_logging

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


@app.command("run")
def run_pipeline(
    niche: str = typer.Option(None, help="Override niche, e.g. technology"),
    limit: int = typer.Option(None, help="Discovery limit (default from settings)"),
    simulate: bool = typer.Option(True, help="Simulate email sending (recommended)"),
    real_send: bool = typer.Option(False, help="Attempt real SMTP send when configured"),
) -> None:
    """Run discovery → filter → enrich → personalize → send/simulate."""
    settings = get_settings()
    if niche:
        settings.niche = niche
    setup_logging(settings.log_level)
    pipeline = OutreachPipeline(settings)
    # --real-send attempts SMTP; otherwise always simulate (safe default)
    do_simulate = not real_send if real_send else simulate
    summary = pipeline.run(simulate_send=do_simulate, limit=limit)

    table = Table(title="EDXSO Outreach Pipeline Summary")
    table.add_column("Metric")
    table.add_column("Value")
    for key, value in summary.model_dump().items():
        if key in {"started_at", "finished_at"}:
            value = str(value)
        if key == "notes":
            value = "; ".join(value) if value else "-"
        table.add_row(key, str(value))
    console.print(table)
    console.print(
        f"[green]Artifacts written under[/green] {settings.data_dir}"
    )


@app.command("version")
def version() -> None:
    from influencer_outreach import __version__

    console.print(__version__)


if __name__ == "__main__":
    app()
