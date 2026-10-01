"""YouTube micro-influencer discovery.

Uses the public YouTube Data API when YOUTUBE_API_KEY is set.
Falls back to yt-dlp search extraction for public metadata (no fabricated rows).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from influencer_outreach.discovery.base import DiscoveryProvider
from influencer_outreach.models import InfluencerProfile, Platform
from influencer_outreach.utils import clamp_engagement, extract_emails, stable_id

logger = logging.getLogger(__name__)

# Curated public search queries for technology niche (expandable).
DEFAULT_QUERIES: dict[str, list[str]] = {
    "technology": [
        "software engineering tips",
        "python programming tutorial",
        "web development career",
        "devtools review",
        "AI machine learning explained",
        "system design interview",
        "javascript frontend tips",
        "open source contributor",
        "react native tutorial",
        "devops kubernetes beginner",
        "rust programming intro",
        "sql database tutorial",
        "cybersecurity basics",
        "vscode tips productivity",
        "api design rest graphql",
        "coding interview prep",
    ],
    "crypto": [
        "crypto explained beginners",
        "solidity smart contracts",
        "web3 developer tutorial",
        "defi education",
    ],
    "fintech": [
        "personal finance tech",
        "fintech product review",
        "investing for beginners app",
    ],
    "fitness": [
        "home workout routine",
        "fitness coaching tips",
        "strength training beginners",
    ],
    "gaming": [
        "indie game review",
        "gaming setup tour",
        "esports commentary",
    ],
}


class YouTubeDiscovery(DiscoveryProvider):
    name = "youtube"

    def __init__(self, api_key: str = "", timeout: float = 30.0) -> None:
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)

    def discover(self, niche: str, limit: int) -> list[InfluencerProfile]:
        niche_key = niche.lower().strip()
        queries = DEFAULT_QUERIES.get(niche_key, [f"{niche} creator", f"{niche} tips"])
        profiles: dict[str, InfluencerProfile] = {}

        if self.api_key:
            logger.info("Discovering via YouTube Data API (%s queries)", len(queries))
            for query in queries:
                if len(profiles) >= limit:
                    break
                for item in self._api_search(query, max(10, limit // len(queries) + 5)):
                    channel_id = item.get("channel_id")
                    if not channel_id or channel_id in profiles:
                        continue
                    profile = self._api_channel_to_profile(channel_id, niche_key)
                    if profile:
                        profiles[channel_id] = profile
                    if len(profiles) >= limit:
                        break
        else:
            logger.info(
                "No YOUTUBE_API_KEY — using yt-dlp public search fallback for niche=%s",
                niche_key,
            )
            for query in queries:
                if len(profiles) >= limit:
                    break
                for profile in self._ytdlp_search(query, niche_key, per_query=12):
                    if profile.id not in profiles:
                        profiles[profile.id] = profile
                    if len(profiles) >= limit:
                        break

        results = list(profiles.values())[:limit]
        logger.info("Discovered %s unique YouTube profiles", len(results))
        return results

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3))
    def _api_search(self, query: str, max_results: int) -> list[dict[str, str]]:
        url = "https://www.googleapis.com/youtube/v3/search"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": min(max_results, 50),
            "key": self.api_key,
        }
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        out: list[dict[str, str]] = []
        for item in resp.json().get("items", []):
            snippet = item.get("snippet", {})
            out.append(
                {
                    "channel_id": snippet.get("channelId", ""),
                    "title": snippet.get("channelTitle", ""),
                }
            )
        return out

    def _api_channel_to_profile(self, channel_id: str, niche: str) -> InfluencerProfile | None:
        url = "https://www.googleapis.com/youtube/v3/channels"
        params = {
            "part": "snippet,statistics,brandingSettings",
            "id": channel_id,
            "key": self.api_key,
        }
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        branding = item.get("brandingSettings", {}).get("channel", {})
        subscribers = int(stats.get("subscriberCount") or 0)
        views = int(stats.get("viewCount") or 0)
        videos = max(int(stats.get("videoCount") or 0), 1)
        # Proxy engagement: average views per video / subscribers
        engagement = clamp_engagement((views / videos) / subscribers) if subscribers else 0.0
        description = snippet.get("description") or ""
        website = branding.get("unsubscribedTrailer")  # not ideal; prefer custom URL later
        emails = extract_emails(description)
        custom_url = snippet.get("customUrl")
        profile_url = (
            f"https://www.youtube.com/{custom_url}"
            if custom_url
            else f"https://www.youtube.com/channel/{channel_id}"
        )
        themes = _themes_from_text(description, niche)
        return InfluencerProfile(
            id=stable_id("youtube", channel_id),
            name=snippet.get("title") or channel_id,
            platform=Platform.YOUTUBE,
            profile_url=profile_url,
            follower_count=subscribers,
            engagement_rate=engagement,
            category=niche,
            content_themes=themes,
            contact_email=emails[0] if emails else "Not Found",
            website=None,
            recent_content_notes=(description[:240] + "…") if len(description) > 240 else description,
            raw={
                "channel_id": channel_id,
                "subscriber_count": subscribers,
                "view_count": views,
                "video_count": videos,
                "discovery": "youtube_data_api",
            },
        )

    def _ytdlp_search(self, query: str, niche: str, per_query: int) -> list[InfluencerProfile]:
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            logger.warning("yt-dlp not installed; install requirements and retry")
            return []

        ydl_opts: dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
        }
        profiles: list[InfluencerProfile] = []
        seen_channels: set[str] = set()
        search = f"ytsearch{per_query}:{query}"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(search, download=False)
        except Exception as exc:  # noqa: BLE001 — network/parser resilience
            logger.warning("yt-dlp search failed for %r: %s", query, exc)
            return []

        for entry in info.get("entries") or []:
            if not entry:
                continue
            channel_id = entry.get("channel_id") or entry.get("uploader_id") or ""
            channel = entry.get("channel") or entry.get("uploader") or entry.get("title") or ""
            if not channel_id or channel_id in seen_channels:
                continue
            seen_channels.add(channel_id)
            # Fetch channel metadata for subscribers when possible
            profile = self._ytdlp_channel_profile(channel_id, channel, niche, entry)
            if profile:
                profiles.append(profile)
        return profiles

    def _ytdlp_channel_profile(
        self,
        channel_id: str,
        channel_name: str,
        niche: str,
        sample_entry: dict[str, Any],
    ) -> InfluencerProfile | None:
        try:
            import yt_dlp  # type: ignore
        except ImportError:
            return None

        url = f"https://www.youtube.com/channel/{channel_id}/about"
        ydl_opts = {"quiet": True, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            # Minimal profile from search hit only
            views = int(sample_entry.get("view_count") or 0)
            return InfluencerProfile(
                id=stable_id("youtube", channel_id),
                name=channel_name,
                platform=Platform.YOUTUBE,
                profile_url=f"https://www.youtube.com/channel/{channel_id}",
                follower_count=0,
                engagement_rate=0.0,
                category=niche,
                content_themes=[niche, "creator content"],
                contact_email="Not Found",
                recent_content_notes=sample_entry.get("title"),
                raw={
                    "channel_id": channel_id,
                    "sample_views": views,
                    "discovery": "yt_dlp_search_partial",
                },
            )

        subscribers = int(info.get("channel_follower_count") or info.get("subscriber_count") or 0)
        description = info.get("description") or ""
        emails = extract_emails(description)
        website = None
        for link in info.get("channel_follower_count") and [] or []:
            pass
        # yt-dlp may expose channel URL
        profile_url = info.get("channel_url") or f"https://www.youtube.com/channel/{channel_id}"
        themes = _themes_from_text(description, niche)
        # Engagement proxy from recent entries if present
        engagement = 0.0
        if subscribers > 0:
            sample_views = int(sample_entry.get("view_count") or 0)
            if sample_views:
                engagement = clamp_engagement(sample_views / subscribers)

        return InfluencerProfile(
            id=stable_id("youtube", channel_id),
            name=info.get("channel") or info.get("uploader") or channel_name,
            platform=Platform.YOUTUBE,
            profile_url=profile_url,
            follower_count=subscribers,
            engagement_rate=engagement,
            category=niche,
            content_themes=themes,
            contact_email=emails[0] if emails else "Not Found",
            website=website,
            recent_content_notes=(description[:240] + "…") if len(description) > 240 else description,
            raw={
                "channel_id": channel_id,
                "discovery": "yt_dlp",
                "tags": info.get("tags") or [],
            },
        )


def _themes_from_text(text: str, niche: str) -> list[str]:
    text_l = (text or "").lower()
    catalog = [
        "python",
        "javascript",
        "ai",
        "machine learning",
        "career",
        "tutorial",
        "devops",
        "cloud",
        "security",
        "startup",
        "product",
        "design",
        "crypto",
        "web3",
        "gaming",
        "fitness",
        "finance",
    ]
    themes = [niche]
    for token in catalog:
        if token in text_l and token not in themes:
            themes.append(token)
        if len(themes) >= 5:
            break
    if len(themes) == 1:
        themes.append("educational content")
    return themes
