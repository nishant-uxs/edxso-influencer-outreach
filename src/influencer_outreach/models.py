"""Domain models for the influencer outreach pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Platform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    OTHER = "other"


class FilterDecision(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class SendStatus(str, Enum):
    PENDING = "pending"
    SIMULATED = "simulated"
    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


class InfluencerProfile(BaseModel):
    """Canonical influencer record used across stages."""

    id: str
    name: str
    platform: Platform
    profile_url: str
    follower_count: int = Field(ge=0)
    engagement_rate: float = Field(ge=0.0, description="Fraction, e.g. 0.035 = 3.5%")
    category: str
    content_themes: list[str] = Field(default_factory=list)
    contact_email: str = "Not Found"
    website: Optional[str] = None
    audience_age: Optional[str] = None
    audience_gender: Optional[str] = None
    audience_geography: Optional[str] = None
    recent_content_notes: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @field_validator("contact_email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return "Not Found"
        if value.lower() in {"n/a", "none", "null", "unknown"}:
            return "Not Found"
        return value

    @property
    def has_email(self) -> bool:
        return self.contact_email != "Not Found" and "@" in self.contact_email


class FilterResult(BaseModel):
    profile: InfluencerProfile
    decision: FilterDecision
    reasons: list[str]
    score: float = 0.0


class OutreachMessages(BaseModel):
    influencer_id: str
    email_subject: str
    email_body: str
    instagram_dm: str
    personalization_signals: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)


class OutreachLogEntry(BaseModel):
    influencer_id: str
    name: str
    email: str
    message_generated: bool
    sent: bool
    status: SendStatus
    channel: str = "email"
    date: datetime = Field(default_factory=utc_now)
    detail: str = ""
    dedupe_key: str = ""


class PipelineRunSummary(BaseModel):
    niche: str
    discovered: int
    passed_filter: int
    enriched: int
    messages_generated: int
    emails_attempted: int
    emails_sent_or_simulated: int
    started_at: datetime
    finished_at: datetime
    notes: list[str] = Field(default_factory=list)
