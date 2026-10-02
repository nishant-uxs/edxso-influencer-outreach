"""CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from influencer_outreach.config import get_settings
from influencer_outreach.models import InfluencerProfile, Platform
from influencer_outreach.personalization import build_personalizer
from influencer_outreach.pipeline.runner import OutreachPipeline
from influencer_outreach.storage.exporters import save_messages_json
from influencer_outreach.utils import setup_logging, stable_id

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
    console.print(f"[green]Artifacts written under[/green] {settings.data_dir}")


@app.command("personalize")
def personalize_only(
    input_csv: Path = typer.Option(Path("examples/sample_run/influencers.csv")),
    profiles_json: Path = typer.Option(
        Path("examples/sample_run/enriched_profiles.json"),
        help="Optional enriched profiles with about/notes for stronger AI signals",
    ),
    output: Path = typer.Option(Path("examples/sample_run/messages.json")),
    sleep_ms: int = typer.Option(150, help="Pause between LLM calls to avoid rate limits"),
) -> None:
    """Re-run AI personalization (local engine + optional LLM) on a dataset."""
    import time

    settings = get_settings()
    setup_logging(settings.log_level)
    personalizer = build_personalizer(settings)
    profiles = _load_profiles(input_csv, profiles_json if profiles_json.exists() else None)
    messages = []
    for i, profile in enumerate(profiles, start=1):
        messages.append(personalizer.personalize(profile))
        if settings.openai_api_key and sleep_ms > 0 and i < len(profiles):
            time.sleep(sleep_ms / 1000.0)
        if i % 10 == 0:
            console.print(f"personalized {i}/{len(profiles)}")
    save_messages_json(output, messages)
    subjects = {m.email_subject for m in messages}
    methods = {
        s
        for m in messages
        for s in m.personalization_signals
        if s.startswith("method=")
    }
    console.print(f"[green]Wrote {len(messages)} AI messages -> {output}[/green]")
    console.print(f"Unique subjects: {len(subjects)}/{len(messages)}")
    console.print(f"Methods: {', '.join(sorted(methods)) or 'n/a'}")
    meta = {
        "count": len(messages),
        "unique_subjects": len(subjects),
        "methods": sorted(methods),
        "model": settings.openai_model if settings.openai_api_key else None,
        "llm_enabled": bool(settings.openai_api_key),
    }
    output.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


@app.command("version")
def version() -> None:
    from influencer_outreach import __version__

    console.print(__version__)


def _load_profiles(csv_path: Path, profiles_json: Path | None) -> list[InfluencerProfile]:
    by_name: dict[str, dict] = {}
    if profiles_json and profiles_json.exists():
        for row in json.loads(profiles_json.read_text(encoding="utf-8")):
            by_name[row["name"]] = row

    df = pd.read_csv(csv_path)
    out: list[InfluencerProfile] = []
    for _, r in df.iterrows():
        name = str(r["Name"])
        rich = by_name.get(name, {})
        themes = rich.get("content_themes") or [
            t.strip() for t in str(r.get("Content Theme") or "").split(";") if t.strip()
        ]
        url = str(rich.get("profile_url") or r["Profile URL"])
        channel = url.rstrip("/").split("/")[-1]
        out.append(
            InfluencerProfile(
                id=str(rich.get("id") or stable_id("youtube", channel)),
                name=name,
                platform=Platform(str(r["Platform"]).lower()),
                profile_url=url,
                follower_count=int(rich.get("follower_count") or r["Followers"]),
                engagement_rate=float(rich.get("engagement_rate") or r["Engagement"]),
                category=str(rich.get("category") or r["Niche"]),
                content_themes=themes or [str(r["Niche"])],
                contact_email=str(rich.get("contact_email") or r["Email"]),
                website=rich.get("website"),
                recent_content_notes=rich.get("recent_content_notes")
                or f"{name} creates {', '.join(themes[:3]) or r['Niche']} content on YouTube.",
            )
        )
    return out


if __name__ == "__main__":
    app()
