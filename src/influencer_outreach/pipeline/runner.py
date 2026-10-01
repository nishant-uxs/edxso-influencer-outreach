"""End-to-end orchestration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from influencer_outreach.config import Settings
from influencer_outreach.discovery import YouTubeDiscovery
from influencer_outreach.enrichment import ProfileEnricher
from influencer_outreach.filtering import BrandFitFilter, FilterConfig
from influencer_outreach.models import FilterDecision, PipelineRunSummary
from influencer_outreach.personalization import build_personalizer
from influencer_outreach.sending import OutreachSender
from influencer_outreach.storage.exporters import (
    save_filter_report,
    save_messages_json,
    save_profiles_csv,
    save_profiles_json,
)
from influencer_outreach.tracking import OutreachStore

logger = logging.getLogger(__name__)


class OutreachPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self.discovery = YouTubeDiscovery(api_key=settings.youtube_api_key)
        self.filters = BrandFitFilter(
            FilterConfig(
                niche=settings.niche,
                min_followers=settings.min_followers,
                max_followers=settings.max_followers,
                min_engagement_rate=settings.min_engagement_rate,
                required_platform=settings.platform if settings.platform != "all" else None,
            )
        )
        self.enricher = ProfileEnricher()
        self.personalizer = build_personalizer(settings)
        self.store = OutreachStore(settings.database_path)
        self.sender = OutreachSender(settings, self.store)

    def run(self, *, simulate_send: bool = True, limit: int | None = None) -> PipelineRunSummary:
        started = datetime.now(timezone.utc)
        notes: list[str] = []
        target = limit or self.settings.discovery_limit

        # 1) Discovery
        discovered = self.discovery.discover(self.settings.niche, target)
        save_profiles_json(self.settings.raw_dir / "discovered.json", discovered)
        notes.append(f"discovery_source={self.discovery.name}")

        if len(discovered) < 50:
            notes.append(
                f"WARNING: only {len(discovered)} profiles discovered; "
                "set YOUTUBE_API_KEY or check network/yt-dlp for fuller runs"
            )

        # 2) Filter
        filter_results = self.filters.apply(discovered)
        save_filter_report(self.settings.processed_dir / "filter_report.csv", filter_results)
        passed = [r.profile for r in filter_results if r.decision == FilterDecision.PASSED]

        # 3) Enrich
        enriched = self.enricher.enrich_many(passed)
        save_profiles_json(self.settings.processed_dir / "shortlist.json", enriched)
        save_profiles_csv(self.settings.processed_dir / "influencers.csv", enriched)

        # 4) Personalize
        messages = [self.personalizer.personalize(p) for p in enriched]
        save_messages_json(self.settings.outreach_dir / "messages.json", messages)
        by_id = {m.influencer_id: m for m in messages}

        # 5) Send / simulate
        attempted = 0
        delivered = 0
        for profile in enriched:
            msg = by_id[profile.id]
            attempted += 1
            entry = self.sender.send_email(profile, msg, simulate=simulate_send)
            if entry.status.value in {"sent", "simulated"}:
                delivered += 1

        self.store.export_json(self.settings.outreach_dir / "outreach_tracker.json")
        _export_tracker_csv(self.settings.outreach_dir / "outreach_tracker.csv", self.store)

        finished = datetime.now(timezone.utc)
        summary = PipelineRunSummary(
            niche=self.settings.niche,
            discovered=len(discovered),
            passed_filter=len(passed),
            enriched=len(enriched),
            messages_generated=len(messages),
            emails_attempted=attempted,
            emails_sent_or_simulated=delivered,
            started_at=started,
            finished_at=finished,
            notes=notes,
        )
        (self.settings.outreach_dir / "run_summary.json").write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info("Pipeline finished: %s", summary.model_dump())
        return summary


def _export_tracker_csv(path, store: OutreachStore) -> None:
    import pandas as pd

    rows = []
    for e in store.list_entries():
        rows.append(
            {
                "Influencer": e.name,
                "Email": e.email,
                "Message Generated": e.message_generated,
                "Sent": e.sent,
                "Date": e.date if isinstance(e.date, str) else e.date.isoformat(),
                "Status": e.status.value,
                "Detail": e.detail,
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)
