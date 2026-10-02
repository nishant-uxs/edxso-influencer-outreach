"""Real YouTube public metrics via yt-dlp flat extract — never invents numbers."""

from __future__ import annotations

import logging
from typing import Any

from influencer_outreach.utils import clamp_engagement

logger = logging.getLogger(__name__)


def fetch_channel_public_metrics(channel_url: str, *, recent_videos: int = 8) -> dict[str, Any]:
    """
    One yt-dlp call against the channel /videos tab (flat playlist).

    Engagement method (documented, real public stats only):
      mean(recent video view_count) / subscriber_count
    Likes/comments are often unavailable without JS runtime; we do not invent them.
    """
    try:
        import yt_dlp
    except ImportError:
        logger.warning("yt-dlp missing; cannot refresh YouTube metrics")
        return {}

    out: dict[str, Any] = {}
    videos_url = channel_url.rstrip("/") + "/videos"
    opts = {
        "quiet": True,
        "noprogress": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": recent_videos,
        "ignoreerrors": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(videos_url, download=False) or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("yt-dlp metrics failed %s: %s", channel_url, exc)
        return out

    subs = int(info.get("channel_follower_count") or info.get("subscriber_count") or 0)
    if subs:
        out["subscriber_count"] = subs

    desc = info.get("description") or ""
    if desc:
        out["description"] = desc[:500]

    samples: list[dict[str, int | None]] = []
    views_list: list[int] = []
    for entry in (info.get("entries") or [])[:recent_videos]:
        if not entry:
            continue
        views = entry.get("view_count")
        if views is None:
            continue
        views_i = int(views)
        views_list.append(views_i)
        samples.append(
            {
                "views": views_i,
                "likes": int(entry["like_count"]) if entry.get("like_count") is not None else None,
                "comments": int(entry["comment_count"])
                if entry.get("comment_count") is not None
                else None,
            }
        )

    if samples:
        out["recent_video_samples"] = samples[:5]
        out["recent_videos_scored"] = len(samples)

    if views_list and subs > 0:
        avg_views = sum(views_list) / len(views_list)
        out["engagement_rate"] = clamp_engagement(avg_views / subs)
        out["engagement_method"] = "mean(views)/subscribers over recent public videos"
        out["avg_views"] = round(avg_views, 2)

    # Prefer interaction ER if likes present on enough samples
    interactions = [
        float((s["likes"] or 0) + (s["comments"] or 0))
        for s in samples
        if s.get("likes") is not None or s.get("comments") is not None
    ]
    if interactions and subs > 0:
        avg_inter = sum(interactions) / len(interactions)
        out["engagement_rate"] = clamp_engagement(avg_inter / subs)
        out["engagement_method"] = "mean(likes+comments)/subscribers over recent public videos"
        out["avg_interactions"] = round(avg_inter, 2)

    return out
