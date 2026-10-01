"""Filtering / classification for brand-fit."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from influencer_outreach.models import FilterDecision, FilterResult, InfluencerProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilterConfig:
    niche: str
    min_followers: int = 5_000
    max_followers: int = 100_000
    min_engagement_rate: float = 0.01
    required_platform: str | None = "youtube"
    # Brand-fit keyword groups for technology / AI education
    include_keywords: tuple[str, ...] = (
        "tech",
        "software",
        "developer",
        "programming",
        "coding",
        "ai",
        "python",
        "javascript",
        "cloud",
        "devops",
        "tutorial",
        "engineering",
        "machine learning",
        "data",
    )


class BrandFitFilter:
    """
    Complete filtering category: Technology / Developer-Education brand fit.

    Pass criteria (all must hold):
    - platform match (default youtube)
    - follower count within micro band
    - engagement above threshold (when measurable; zero only fails if explicitly required)
    - content/niche keyword relevance
    """

    def __init__(self, config: FilterConfig, require_engagement: bool = False) -> None:
        self.config = config
        self.require_engagement = require_engagement

    def evaluate(self, profile: InfluencerProfile) -> FilterResult:
        reasons: list[str] = []
        score = 0.0
        cfg = self.config

        # Platform
        if cfg.required_platform and profile.platform.value != cfg.required_platform:
            reasons.append(
                f"FAIL platform: expected {cfg.required_platform}, got {profile.platform.value}"
            )
        else:
            reasons.append(f"PASS platform: {profile.platform.value}")
            score += 1

        # Followers
        if profile.follower_count < cfg.min_followers:
            reasons.append(
                f"FAIL followers: {profile.follower_count} < min {cfg.min_followers}"
            )
        elif profile.follower_count > cfg.max_followers:
            reasons.append(
                f"FAIL followers: {profile.follower_count} > max {cfg.max_followers} (not micro)"
            )
        else:
            reasons.append(
                f"PASS followers: {profile.follower_count} within "
                f"{cfg.min_followers}-{cfg.max_followers}"
            )
            score += 2

        # Engagement
        if profile.engagement_rate <= 0:
            if self.require_engagement:
                reasons.append("FAIL engagement: missing/zero engagement rate")
            else:
                reasons.append(
                    "SOFT engagement: unavailable/zero — not failing "
                    "(public sources often omit precise ER)"
                )
                score += 0.5
        elif profile.engagement_rate < cfg.min_engagement_rate:
            reasons.append(
                f"FAIL engagement: {profile.engagement_rate:.4f} < min {cfg.min_engagement_rate}"
            )
        else:
            reasons.append(f"PASS engagement: {profile.engagement_rate:.4f}")
            score += 2

        # Niche / content relevance
        blob = " ".join(
            [
                profile.category,
                profile.name,
                " ".join(profile.content_themes),
                profile.recent_content_notes or "",
            ]
        ).lower()
        hits = [kw for kw in cfg.include_keywords if re.search(rf"\b{re.escape(kw)}\b", blob)]
        niche_hit = cfg.niche.lower() in blob
        if hits or niche_hit:
            reasons.append(
                "PASS brand-fit/content relevance: "
                + (", ".join(hits[:5]) if hits else f"niche={cfg.niche}")
            )
            score += 2 + min(len(hits), 3) * 0.25
        else:
            reasons.append(
                "FAIL brand-fit: no technology/education keywords matched in profile context"
            )

        decision = (
            FilterDecision.PASSED
            if all(r.startswith("PASS") or r.startswith("SOFT") for r in reasons)
            else FilterDecision.FAILED
        )
        # Stricter: any FAIL => failed
        if any(r.startswith("FAIL") for r in reasons):
            decision = FilterDecision.FAILED

        return FilterResult(profile=profile, decision=decision, reasons=reasons, score=score)

    def apply(self, profiles: list[InfluencerProfile]) -> list[FilterResult]:
        results = [self.evaluate(p) for p in profiles]
        passed = sum(1 for r in results if r.decision == FilterDecision.PASSED)
        logger.info("Filter complete: %s/%s passed", passed, len(results))
        return results
