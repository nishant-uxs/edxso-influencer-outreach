"""Unit tests — no network required."""

from __future__ import annotations

from pathlib import Path

from influencer_outreach.config import Settings
from influencer_outreach.filtering import BrandFitFilter, FilterConfig
from influencer_outreach.models import FilterDecision, InfluencerProfile, Platform
from influencer_outreach.personalization import TemplatePersonalizer
from influencer_outreach.tracking import OutreachStore
from influencer_outreach.models import OutreachLogEntry, SendStatus
from influencer_outreach.utils import extract_emails, first_email_or_not_found, stable_id


def _profile(**kwargs) -> InfluencerProfile:
    base = dict(
        id="abc123",
        name="Dev Tips Channel",
        platform=Platform.YOUTUBE,
        profile_url="https://www.youtube.com/channel/UC123",
        follower_count=25_000,
        engagement_rate=0.04,
        category="technology",
        content_themes=["python", "tutorial"],
        contact_email="Not Found",
        recent_content_notes="Python programming tutorials for beginners",
    )
    base.update(kwargs)
    return InfluencerProfile(**base)


def test_stable_id_deterministic():
    assert stable_id("a", "b") == stable_id("a", "b")
    assert stable_id("a", "b") != stable_id("a", "c")


def test_extract_emails_filters_junk():
    text = "reach me at hello@creator.dev or spam@example.com also bad@sentry.io"
    emails = extract_emails(text)
    assert emails == ["hello@creator.dev"]
    assert first_email_or_not_found([""]) == "Not Found"


def test_brand_fit_filter_pass_and_fail():
    filt = BrandFitFilter(FilterConfig(niche="technology"))
    ok = filt.evaluate(_profile())
    assert ok.decision == FilterDecision.PASSED

    too_big = filt.evaluate(_profile(follower_count=500_000))
    assert too_big.decision == FilterDecision.FAILED
    assert any("FAIL followers" in r for r in too_big.reasons)

    off_niche = filt.evaluate(
        _profile(
            category="cooking",
            content_themes=["recipes"],
            recent_content_notes="best pasta sauce",
            name="Kitchen Daily",
        )
    )
    assert off_niche.decision == FilterDecision.FAILED


def test_template_personalizer_word_bounds():
    settings = Settings(openai_api_key="")
    msg = TemplatePersonalizer(settings).personalize(_profile(contact_email="a@b.com"))
    assert 15 <= len(msg.instagram_dm.split()) <= 35
    assert len(msg.email_body.split()) >= 60
    assert "EDXSO" in msg.email_body or "EDXSO" in msg.email_subject


def test_outreach_store_dedupe(tmp_path: Path):
    store = OutreachStore(tmp_path / "t.db")
    entry = OutreachLogEntry(
        influencer_id="1",
        name="A",
        email="a@b.com",
        message_generated=True,
        sent=True,
        status=SendStatus.SIMULATED,
        dedupe_key="key-1",
    )
    store.record(entry)
    assert store.already_sent("key-1") is True
    assert store.already_sent("key-2") is False
    assert len(store.list_entries()) == 1
