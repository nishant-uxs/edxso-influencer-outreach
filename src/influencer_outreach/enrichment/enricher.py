"""Profile enrichment — never invent emails or metrics."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from influencer_outreach.enrichment.youtube_metrics import fetch_channel_public_metrics
from influencer_outreach.models import InfluencerProfile
from influencer_outreach.utils import extract_emails, first_email_or_not_found

logger = logging.getLogger(__name__)

OBFUSCATED_EMAIL_RE = re.compile(
    r"([a-zA-Z0-9._%+\-]{2,})\s*(?:\[\s*at\s*\]|\(\s*at\s\)|\s+at\s+)\s*"
    r"([a-zA-Z0-9.\-]{2,})\s*(?:\[\s*dot\s*\]|\(\s*dot\s\)|\s+dot\s+)\s*([a-zA-Z]{2,})",
    re.I,
)


class ProfileEnricher:
    """
    Enriches profiles with publicly available signals only:
    - email from description / linked website / mailto / light obfuscation
    - website URL if found
    - real recent-video engagement via yt-dlp
    - channel country → audience_geography when public
    """

    def __init__(
        self,
        timeout: float = 15.0,
        max_workers: int = 6,
        *,
        refresh_youtube_metrics: bool = True,
    ) -> None:
        self.timeout = timeout
        self.max_workers = max_workers
        self.refresh_youtube_metrics = refresh_youtube_metrics
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "EDXSO-InfluencerOutreach/0.1 (+research assignment)"},
        )

    def enrich_many(
        self,
        profiles: list[InfluencerProfile],
        *,
        deep: bool = True,
    ) -> list[InfluencerProfile]:
        if not profiles:
            return []
        if not deep or len(profiles) == 1:
            return [self.enrich_one(p, deep=deep) for p in profiles]

        enriched_map: dict[str, InfluencerProfile] = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {
                pool.submit(self.enrich_one, profile, deep=deep): profile.id
                for profile in profiles
            }
            for fut in as_completed(futures):
                pid = futures[fut]
                try:
                    enriched_map[pid] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Enrichment failed for %s: %s", pid, exc)
                    original = next(p for p in profiles if p.id == pid)
                    if original.contact_email != "Not Found" and "@" not in original.contact_email:
                        original.contact_email = "Not Found"
                    enriched_map[pid] = original
        return [enriched_map[p.id] for p in profiles]

    def enrich_one(self, profile: InfluencerProfile, *, deep: bool = True) -> InfluencerProfile:
        texts = [profile.recent_content_notes or "", " ".join(profile.content_themes)]
        website = profile.website
        geo = profile.audience_geography
        engagement = profile.engagement_rate
        followers = profile.follower_count
        notes = profile.recent_content_notes
        metrics_raw: dict = {}

        if deep and self.refresh_youtube_metrics and profile.platform.value == "youtube":
            metrics_raw = fetch_channel_public_metrics(profile.profile_url)
            if metrics_raw.get("subscriber_count"):
                followers = int(metrics_raw["subscriber_count"])
            if metrics_raw.get("engagement_rate") is not None:
                engagement = float(metrics_raw["engagement_rate"])
            if metrics_raw.get("country"):
                geo = str(metrics_raw["country"])
            if metrics_raw.get("description"):
                notes = metrics_raw["description"][:500]
                texts.append(metrics_raw["description"])

        if deep:
            html = self._safe_get_text(profile.profile_url)
            if html:
                texts.append(html)
                if not website:
                    website = _find_website(html)
                for link in _candidate_contact_pages(html):
                    page = self._safe_get_text(link)
                    if page:
                        texts.append(page)
                        if not website and "http" in link:
                            website = website or link
            if website:
                site_html = self._safe_get_text(website)
                if site_html:
                    texts.append(site_html)

        email = profile.contact_email
        if email == "Not Found" or not email:
            email = first_email_or_not_found(texts)
        if email == "Not Found":
            email = _first_obfuscated_email(texts)

        if email != "Not Found" and not re.search(r"^[^@]+@[^@]+\.[^@]+$", email):
            email = "Not Found"
        # Extra junk filter for scraped JS noise
        if email != "Not Found":
            lower = email.lower()
            if any(
                x in lower
                for x in (
                    "noreply@",
                    "no-reply@",
                    "privacy@",
                    "support@youtube",
                    "google.com",
                    "schema.org",
                )
            ):
                # keep business support emails except youtube/google
                if "youtube" in lower or "google.com" in lower or "schema.org" in lower:
                    email = "Not Found"

        themes = list(dict.fromkeys(profile.content_themes))
        if profile.category and profile.category not in themes:
            themes.insert(0, profile.category)

        updated = profile.model_copy(
            update={
                "contact_email": email,
                "website": website or profile.website,
                "content_themes": themes[:8],
                "engagement_rate": engagement,
                "follower_count": followers,
                "audience_geography": geo,
                "recent_content_notes": notes or profile.recent_content_notes,
            }
        )
        updated.raw = {
            **profile.raw,
            "enriched": True,
            "email_source": "public_text" if email != "Not Found" else "not_found",
            "deep": deep,
            "youtube_metrics": {
                k: metrics_raw[k]
                for k in (
                    "engagement_method",
                    "recent_videos_scored",
                    "avg_interactions",
                    "avg_view_rate",
                    "country",
                )
                if k in metrics_raw
            }
            if metrics_raw
            else {},
        }
        return updated

    @retry(wait=wait_exponential(multiplier=1, min=1, max=4), stop=stop_after_attempt(2), reraise=False)
    def _safe_get_text(self, url: str) -> str:
        if not url or not url.startswith("http"):
            return ""
        try:
            resp = self._client.get(url)
            if resp.status_code >= 400:
                return ""
            return resp.text[:200_000]
        except Exception as exc:  # noqa: BLE001
            logger.debug("GET failed %s: %s", url, exc)
            return ""


def _find_website(html: str) -> str | None:
    hrefs = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, flags=re.I)
    skip = (
        "youtube.com",
        "youtu.be",
        "instagram.com",
        "tiktok.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "accounts.google",
    )
    for href in hrefs:
        host = urlparse(href).netloc.lower()
        if any(s in host for s in skip):
            continue
        if "google.com" in host:
            continue
        return href
    return None


def _candidate_contact_pages(html: str) -> list[str]:
    """Public contact hubs often listed on creator pages."""
    hrefs = re.findall(r'href=["\'](https?://[^"\']+)["\']', html, flags=re.I)
    prefer = (
        "linktr.ee",
        "bio.link",
        "beacons.ai",
        "carrd.co",
        "std.lnk",
        "lnk.bio",
        "contact",
    )
    out: list[str] = []
    for href in hrefs:
        low = href.lower()
        if any(p in low for p in prefer):
            out.append(unescape(href).split("&")[0])
        if len(out) >= 3:
            break
    return out


def _first_obfuscated_email(texts) -> str:
    for text in texts:
        if not text:
            continue
        for match in OBFUSCATED_EMAIL_RE.finditer(text):
            email = f"{match.group(1)}@{match.group(2)}.{match.group(3)}".lower()
            if extract_emails(email):
                return extract_emails(email)[0]
    return "Not Found"
