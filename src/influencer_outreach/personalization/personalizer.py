"""AI / template personalization for outreach messages."""

from __future__ import annotations

import logging
from typing import Protocol

from influencer_outreach.config import Settings
from influencer_outreach.models import InfluencerProfile, OutreachMessages

logger = logging.getLogger(__name__)


class Personalizer(Protocol):
    def personalize(self, profile: InfluencerProfile) -> OutreachMessages: ...


class TemplatePersonalizer:
    """Deterministic, high-quality personalization without an LLM (always available)."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def personalize(self, profile: InfluencerProfile) -> OutreachMessages:
        theme = profile.content_themes[0] if profile.content_themes else profile.category
        tone_bits = profile.content_themes[1:3]
        tone = ", ".join(tone_bits) if tone_bits else "clear educational"
        recent = (profile.recent_content_notes or theme).strip()
        if len(recent) > 90:
            recent = recent[:87] + "..."

        signals = [
            f"niche={profile.category}",
            f"themes={','.join(profile.content_themes[:3])}",
            f"followers={profile.follower_count}",
            f"platform={profile.platform.value}",
        ]

        email_body = (
            f"Hi {profile.name.split()[0]},\n\n"
            f"I've been following your {theme} content on {profile.platform.value} — "
            f"especially the way you cover {tone} topics"
            f"{f' (e.g. “{recent}”)' if recent else ''}. "
            f"Your audience looks like a strong fit for {self.settings.brand_name}.\n\n"
            f"We're exploring a {self.settings.collab_type} collaboration around "
            f"{self.settings.brand_value_prop}. Open to a quick chat about a paid concept?\n\n"
            f"Best,\n{self.settings.brand_name} Partnerships"
        )
        # Enforce 60–90 words roughly by trimming if needed
        email_body = _fit_word_range(email_body, 60, 95)

        subject = f"Collab idea for your {theme} audience — {self.settings.brand_name}"

        first = profile.name.split()[0]
        dm = (
            f"Hi {first}, loved your recent {theme} content — "
            f"your audience fits our {self.settings.collab_type}. Open to a quick collab chat?"
        )
        dm = _fit_word_range(dm, 15, 30)

        return OutreachMessages(
            influencer_id=profile.id,
            email_subject=subject,
            email_body=email_body,
            instagram_dm=dm,
            personalization_signals=signals,
        )


class LLMPersonalizer:
    """OpenAI-compatible personalizer with safe fallback to templates."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fallback = TemplatePersonalizer(settings)

    def personalize(self, profile: InfluencerProfile) -> OutreachMessages:
        if not self.settings.openai_api_key:
            return self._fallback.personalize(profile)
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )
            prompt = f"""
You write influencer outreach for {self.settings.brand_name}.
Brand value: {self.settings.brand_value_prop}
Collab type: {self.settings.collab_type}

Influencer:
- Name: {profile.name}
- Platform: {profile.platform.value}
- Followers: {profile.follower_count}
- Niche: {profile.category}
- Themes: {', '.join(profile.content_themes)}
- Notes: {profile.recent_content_notes or 'n/a'}

Return JSON with keys: email_subject, email_body (60-90 words), instagram_dm (15-30 words), signals (array of strings).
Do not invent fake case studies. Be specific to their niche/themes.
"""
            completion = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": "You are an expert partnerships copywriter."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            import json

            data = json.loads(completion.choices[0].message.content or "{}")
            return OutreachMessages(
                influencer_id=profile.id,
                email_subject=str(data.get("email_subject") or f"Collab with {self.settings.brand_name}"),
                email_body=_fit_word_range(str(data.get("email_body") or ""), 60, 100),
                instagram_dm=_fit_word_range(str(data.get("instagram_dm") or ""), 15, 35),
                personalization_signals=list(data.get("signals") or []),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM personalization failed, using template fallback: %s", exc)
            return self._fallback.personalize(profile)


def build_personalizer(settings: Settings) -> Personalizer:
    if settings.openai_api_key:
        return LLMPersonalizer(settings)
    return TemplatePersonalizer(settings)


def _fit_word_range(text: str, min_words: int, max_words: int) -> str:
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    # Soft minimum — pad only with a single natural closer if extremely short
    if len(text.split()) < min_words:
        text = text.rstrip() + " Looking forward to hearing your thoughts."
    return text.strip()
