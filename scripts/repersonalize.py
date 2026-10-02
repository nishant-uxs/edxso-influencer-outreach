"""Regenerate AI-personalized messages from an existing shortlist / sample CSV."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import typer
from rich.console import Console

from influencer_outreach.config import get_settings
from influencer_outreach.models import InfluencerProfile, Platform
from influencer_outreach.personalization import build_personalizer
from influencer_outreach.storage.exporters import save_messages_json
from influencer_outreach.utils import setup_logging, stable_id

app = typer.Typer(add_completion=False)
console = Console()


def _profiles_from_sample(csv_path: Path, shortlist_json: Path | None) -> list[InfluencerProfile]:
    notes_by_name: dict[str, str] = {}
    id_by_name: dict[str, str] = {}
    if shortlist_json and shortlist_json.exists():
        for row in json.loads(shortlist_json.read_text(encoding="utf-8")):
            notes_by_name[row["name"]] = row.get("recent_content_notes") or ""
            id_by_name[row["name"]] = row["id"]

    df = pd.read_csv(csv_path)
    profiles: list[InfluencerProfile] = []
    for _, r in df.iterrows():
        name = str(r["Name"])
        themes = [t.strip() for t in str(r.get("Content Theme") or "").split(";") if t.strip()]
        url = str(r["Profile URL"])
        channel = url.rstrip("/").split("/")[-1]
        pid = id_by_name.get(name) or stable_id("youtube", channel)
        profiles.append(
            InfluencerProfile(
                id=pid,
                name=name,
                platform=Platform(str(r["Platform"]).lower()),
                profile_url=url,
                follower_count=int(r["Followers"]),
                engagement_rate=float(r["Engagement"]),
                category=str(r["Niche"]),
                content_themes=themes or [str(r["Niche"])],
                contact_email=str(r["Email"]),
                website=(None if pd.isna(r.get("Website")) else str(r.get("Website"))),
                recent_content_notes=notes_by_name.get(name)
                or f"{name} creates {', '.join(themes[:3]) or r['Niche']} content on YouTube.",
            )
        )
    return profiles


@app.command("messages")
def regenerate_messages(
    input_csv: Path = typer.Option(
        Path("examples/sample_run/influencers.csv"),
        help="Influencer dataset CSV",
    ),
    shortlist_json: Path = typer.Option(
        Path("data/processed/shortlist.json"),
        help="Optional enriched JSON for richer about/notes",
    ),
    output: Path = typer.Option(
        Path("examples/sample_run/messages.json"),
        help="Where to write personalized messages",
    ),
) -> None:
    """Run local AI (+ optional LLM) personalization over an existing dataset."""
    settings = get_settings()
    setup_logging(settings.log_level)
    personalizer = build_personalizer(settings)
    profiles = _profiles_from_sample(input_csv, shortlist_json if shortlist_json.exists() else None)
    messages = [personalizer.personalize(p) for p in profiles]
    save_messages_json(output, messages)

    subjects = {m.email_subject for m in messages}
    methods = set()
    for m in messages:
        for s in m.personalization_signals:
            if s.startswith("method="):
                methods.add(s)
    console.print(f"[green]Wrote {len(messages)} messages → {output}[/green]")
    console.print(f"Unique subjects: {len(subjects)}/{len(messages)}")
    console.print(f"Methods: {', '.join(sorted(methods)) or 'n/a'}")


if __name__ == "__main__":
    app()
