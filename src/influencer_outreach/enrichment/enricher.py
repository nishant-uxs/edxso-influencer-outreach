"""Profile enrichment — never invent emails or metrics."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from influencer_outreach.models import InfluencerProfile
from influencer_outreach.utils import first_email_or_not_found

logger = logging.getLogger(__name__)


class ProfileEnricher:
    """
    Enriches profiles with publicly available signals:
    - email from description / linked website (mailto or visible address)
    - website URL if found
    - content themes refinement

    Missing emails are explicitly set to "Not Found".
    """

    def __init__(self, timeout: float = 15.0, max_workers: int = 8) -> None:
        self.timeout = timeout
        self.max_workers = max_workers
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

        if deep:
            html = self._safe_get_text(profile.profile_url)
            if html:
                texts.append(html)
                if not website:
                    website = _find_website(html)
            if website:
                site_html = self._safe_get_text(website)
                if site_html:
                    texts.append(site_html)

        email = profile.contact_email
        if email == "Not Found" or not email:
            email = first_email_or_not_found(texts)

        if email != "Not Found" and not re.search(r"^[^@]+@[^@]+\.[^@]+$", email):
            email = "Not Found"

        themes = list(dict.fromkeys(profile.content_themes))
        if profile.category and profile.category not in themes:
            themes.insert(0, profile.category)

        updated = profile.model_copy(
            update={
                "contact_email": email,
                "website": website or profile.website,
                "content_themes": themes[:8],
            }
        )
        updated.raw = {
            **profile.raw,
            "enriched": True,
            "email_source": "public_text" if email != "Not Found" else "not_found",
            "deep": deep,
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
    )
    for href in hrefs:
        host = urlparse(href).netloc.lower()
        if any(s in host for s in skip):
            continue
        if "google.com" in host or "account" in host:
            continue
        return href
    return None
