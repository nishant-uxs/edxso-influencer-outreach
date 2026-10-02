"""Shared utilities."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Iterable

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Conservative public mailbox TLDs — rejects JS token false positives.
_ALLOWED_TLDS = {
    "com",
    "org",
    "net",
    "io",
    "ai",
    "dev",
    "me",
    "co",
    "in",
    "uk",
    "us",
    "ca",
    "de",
    "app",
    "tech",
    "xyz",
    "info",
    "biz",
    "edu",
    "gov",
    "pro",
    "tv",
    "cc",
    "so",
    "gg",
}


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )


def stable_id(*parts: str) -> str:
    blob = "|".join(p.strip().lower() for p in parts if p)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def extract_emails(text: str) -> list[str]:
    if not text:
        return []
    found = EMAIL_RE.findall(text)
    cleaned: list[str] = []
    junk_substrings = (
        "example.com",
        "email.com",
        "domain.com",
        "sentry.io",
        "wixpress.com",
        "schema.org",
        "google.com",
        "youtube.com",
        "gstatic.com",
        "window.",
        "document.",
        "useragent",
        "webpack",
        "jquery",
        "loc@ion",
        "navig@",
    )
    for email in found:
        lower = email.lower().strip(".")
        local, _, domain = lower.partition("@")
        if any(x in lower for x in junk_substrings):
            continue
        if not local or not domain or "." not in domain:
            continue
        tld = domain.rsplit(".", 1)[-1]
        if tld not in _ALLOWED_TLDS:
            continue
        if len(local) < 2 or local.startswith(".") or domain.startswith("."):
            continue
        if any(tok in local for tok in ("window", "document", "function", "undefined")):
            continue
        if lower not in {c.lower() for c in cleaned}:
            cleaned.append(email)
    return cleaned


def first_email_or_not_found(texts: Iterable[str]) -> str:
    for text in texts:
        emails = extract_emails(text or "")
        if emails:
            return emails[0]
    return "Not Found"


def clamp_engagement(rate: float) -> float:
    if rate < 0:
        return 0.0
    if rate > 1:
        # allow percentage inputs like 3.5 meaning 3.5%
        if rate <= 100:
            return round(rate / 100.0, 6)
        return 1.0
    return round(rate, 6)
