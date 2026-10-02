"""Re-enrich sample influencers with real YouTube view-based engagement + safer emails."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from influencer_outreach.enrichment import ProfileEnricher
from influencer_outreach.models import InfluencerProfile, Platform
from influencer_outreach.utils import setup_logging, stable_id

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "examples" / "sample_run" / "influencers.csv"
PROFILES = ROOT / "examples" / "sample_run" / "enriched_profiles.json"
# Last known-good emails from prior honest run (before JS false-positive bug)
SEED_EMAILS = ROOT / "examples" / "sample_run" / "known_good_emails.json"
REPORT = ROOT / "examples" / "sample_run" / "enrichment_quality.json"


def _load_seed_emails() -> dict[str, str]:
    if not SEED_EMAILS.exists():
        return {}
    raw = json.loads(SEED_EMAILS.read_text(encoding="utf-8-sig"))
    # Only keep emails that pass the strict extractor
    from influencer_outreach.utils import extract_emails

    clean: dict[str, str] = {}
    for name, email in raw.items():
        found = extract_emails(str(email))
        if found and found[0].lower() == str(email).lower():
            clean[name] = found[0]
    return clean


def _load() -> list[InfluencerProfile]:
    by_name: dict[str, dict] = {}
    if PROFILES.exists():
        for row in json.loads(PROFILES.read_text(encoding="utf-8")):
            by_name[row["name"]] = row
    seeds = _load_seed_emails()
    df = pd.read_csv(CSV)
    profiles: list[InfluencerProfile] = []
    for _, r in df.iterrows():
        name = str(r["Name"])
        rich = by_name.get(name, {})
        themes = rich.get("content_themes") or [
            t.strip() for t in str(r.get("Content Theme") or "").split(";") if t.strip()
        ]
        url = str(rich.get("profile_url") or r["Profile URL"])
        channel = url.rstrip("/").split("/")[-1]
        # Never trust polluted CSV emails — seeds only, else Not Found (enricher may find real ones)
        email = seeds.get(name, "Not Found")
        profiles.append(
            InfluencerProfile(
                id=str(rich.get("id") or stable_id("youtube", channel)),
                name=name,
                platform=Platform.YOUTUBE,
                profile_url=url,
                follower_count=int(r["Followers"]),
                engagement_rate=float(r["Engagement"]),
                category=str(r["Niche"]),
                content_themes=themes or [str(r["Niche"])],
                contact_email=email,
                website=None,
                audience_geography=None,
                recent_content_notes=rich.get("recent_content_notes"),
                raw={},
            )
        )
    return profiles


def main() -> None:
    setup_logging("INFO")
    # sequential is slower but more reliable for yt-dlp; use modest concurrency
    enricher = ProfileEnricher(max_workers=3, refresh_youtube_metrics=True)
    profiles = _load()
    print(f"enriching {len(profiles)} profiles with real public metrics...")
    enriched = enricher.enrich_many(profiles, deep=True)

    rows = []
    payload = []
    with_method = 0
    with_geo = 0
    for p in enriched:
        method = (p.raw.get("youtube_metrics") or {}).get("engagement_method") or ""
        if method:
            with_method += 1
        if p.audience_geography:
            with_geo += 1
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
                "Audience Geography": p.audience_geography or "",
                "Engagement Method": method,
                "Status": "enriched",
            }
        )
        payload.append(p.model_dump(mode="json"))

    from influencer_outreach.utils import extract_emails

    good: dict[str, str] = {}
    for row, pjson in zip(rows, payload, strict=True):
        em = str(row["Email"])
        found = extract_emails(em)
        if found and found[0].lower() == em.lower():
            good[row["Name"]] = found[0]
            row["Email"] = found[0]
            pjson["contact_email"] = found[0]
        else:
            row["Email"] = "Not Found"
            pjson["contact_email"] = "Not Found"

    SEED_EMAILS.write_text(json.dumps(good, indent=2), encoding="utf-8")
    emails_found = len(good)
    summary = {
        "profiles": len(enriched),
        "emails_found": emails_found,
        "emails_not_found": len(enriched) - emails_found,
        "with_audience_geography": with_geo,
        "with_real_engagement_method": with_method,
        "avg_engagement": round(
            sum(p.engagement_rate for p in enriched) / max(len(enriched), 1), 6
        ),
        "integrity": "public YouTube view/interaction stats + validated public emails only",
    }
    pd.DataFrame(rows).to_csv(CSV, index=False)
    PROFILES.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    REPORT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
