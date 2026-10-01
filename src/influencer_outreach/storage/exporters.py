"""Persistence helpers for datasets (CSV/JSON) — scalable batch IO."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from influencer_outreach.models import FilterResult, InfluencerProfile, OutreachMessages


def save_profiles_json(path: Path, profiles: list[InfluencerProfile]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([p.model_dump(mode="json") for p in profiles], indent=2),
        encoding="utf-8",
    )


def save_profiles_csv(path: Path, profiles: list[InfluencerProfile]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in profiles:
        rows.append(
            {
                "Name": p.name,
                "Platform": p.platform.value,
                "Followers": p.follower_count,
                "Engagement": p.engagement_rate,
                "Niche": p.category,
                "Email": p.contact_email,
                "Profile URL": p.profile_url,
                "Content Theme": "; ".join(p.content_themes),
                "Website": p.website or "",
                "Status": "enriched",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def save_filter_report(path: Path, results: list[FilterResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in results:
        rows.append(
            {
                "Name": r.profile.name,
                "Decision": r.decision.value,
                "Score": r.score,
                "Followers": r.profile.follower_count,
                "Engagement": r.profile.engagement_rate,
                "Reasons": " | ".join(r.reasons),
                "Profile URL": r.profile.profile_url,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def save_messages_json(path: Path, messages: list[OutreachMessages]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([m.model_dump(mode="json") for m in messages], indent=2),
        encoding="utf-8",
    )
