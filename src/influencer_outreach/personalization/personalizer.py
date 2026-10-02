"""AI personalization — signal extraction + multi-angle copy generation.

Uses a local AI-style engine by default (no key required). When OPENAI_API_KEY
is set, an LLM refines the draft with structured prompts (prompt engineering).
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from influencer_outreach.config import Settings
from influencer_outreach.models import InfluencerProfile, OutreachMessages

logger = logging.getLogger(__name__)

COLLAB_ANGLES = (
    "UGC content creation",
    "paid sponsorship",
    "affiliate campaign",
    "brand ambassador pilot",
    "product walkthrough series",
    "developer education collab",
)

SUBJECT_PATTERNS = (
    "{first}, quick idea for your {theme} audience",
    "Loved your take on {hook} — collab with {brand}?",
    "{brand} × {first}: {angle_short} for {theme} creators",
    "Your {follower_band} {theme} viewers + our {angle_short}",
    "Not a cold pitch — specific {theme} idea for {first}",
)

EMAIL_HOOKS = (
    "the clarity you bring to {theme}",
    "how you break down {theme} for builders",
    "your practical {theme} storytelling",
    "the way you teach {theme} without fluff",
    "your recent angle on {hook}",
)


class Personalizer(Protocol):
    def personalize(self, profile: InfluencerProfile) -> OutreachMessages: ...


@dataclass(frozen=True)
class PersonalizationSignals:
    """Structured signals extracted before copy generation (AI feature engineering)."""

    first_name: str
    primary_theme: str
    secondary_themes: tuple[str, ...]
    content_angle: str
    audience_hint: str
    hook_phrase: str
    collab_angle: str
    follower_band: str
    tone: str
    recent_snippet: str
    method: str

    def as_list(self) -> list[str]:
        return [
            f"angle={self.content_angle}",
            f"theme={self.primary_theme}",
            f"secondary={','.join(self.secondary_themes) or 'n/a'}",
            f"audience={self.audience_hint}",
            f"hook={self.hook_phrase}",
            f"collab={self.collab_angle}",
            f"followers={self.follower_band}",
            f"tone={self.tone}",
            f"method={self.method}",
        ]


def _first_name(name: str) -> str:
    parts = [p for p in re.split(r"[\s|/]+", name.strip()) if p]
    skip = {"the", "a", "an", "dr", "mr", "mrs", "ms"}
    for part in parts:
        clean = re.sub(r"[^A-Za-z0-9+.#]", "", part)
        if clean.lower() in skip or len(clean) < 2:
            continue
        return clean
    return parts[0] if parts else name


def _sanitize_public_text(text: str) -> str:
    text = html.unescape(text or "")
    for bad, good in {
        "â€™": "'",
        "â€˜": "'",
        "â€œ": '"',
        "â€": '"',
        "â€“": "-",
        "â€”": "-",
    }.items():
        text = text.replace(bad, good)
    return re.sub(r"\s+", " ", text).strip()


def extract_signals(profile: InfluencerProfile, settings: Settings, *, method: str) -> PersonalizationSignals:
    """Feature extraction from public profile text — the 'brain' before generation."""
    first = _first_name(profile.name)
    themes = [t.strip().lower() for t in profile.content_themes if t.strip()]
    if not themes:
        themes = [profile.category.lower()]
    primary = themes[0]
    secondary = tuple(themes[1:3])

    notes = _sanitize_public_text(profile.recent_content_notes or "")
    blob = " ".join(
        [
            profile.category,
            " ".join(themes),
            notes,
            profile.name,
        ]
    ).lower()

    angle = _classify_angle(blob)
    audience = _infer_audience(angle, primary)
    tone = _infer_tone(blob)
    cleaned = profile.model_copy(update={"recent_content_notes": notes})
    hook = _pick_hook(cleaned, themes, angle)
    snippet = _recent_snippet(notes or hook)
    collab = _pick_collab(profile, settings)
    band = _follower_band(profile.follower_count)

    return PersonalizationSignals(
        first_name=first,
        primary_theme=primary,
        secondary_themes=secondary,
        content_angle=angle,
        audience_hint=audience,
        hook_phrase=hook,
        collab_angle=collab,
        follower_band=band,
        tone=tone,
        recent_snippet=snippet,
        method=method,
    )


def _classify_angle(blob: str) -> str:
    rules = [
        ("ai_ml", ("ai", "machine learning", "llm", "gpt", "neural")),
        ("career", ("career", "interview", "job", "resume", "hiring")),
        ("tutorial", ("tutorial", "beginner", "learn", "course", "howto", "how to")),
        ("devops", ("devops", "docker", "kubernetes", "cloud", "aws", "cicd")),
        ("frontend", ("react", "javascript", "frontend", "css", "nextjs", "ui")),
        ("backend", ("backend", "api", "python", "fastapi", "sql", "database")),
        ("security", ("security", "cyber", "hacking", "owasp")),
        ("product", ("product", "startup", "indie", "saas")),
    ]
    for label, keys in rules:
        if any(k in blob for k in keys):
            return label
    return "general_tech"


def _infer_audience(angle: str, theme: str) -> str:
    mapping = {
        "ai_ml": "engineers exploring applied AI",
        "career": "early-career developers job-hunting",
        "tutorial": "self-taught builders learning by doing",
        "devops": "platform / SRE-curious developers",
        "frontend": "frontend and fullstack builders",
        "backend": "backend and API-focused engineers",
        "security": "security-aware developers",
        "product": "indie hackers and product-minded engineers",
    }
    return mapping.get(angle, f"{theme} practitioners and learners")


def _infer_tone(blob: str) -> str:
    if any(x in blob for x in ("beginner", "intro", "basics", "101")):
        return "friendly-explanatory"
    if any(x in blob for x in ("interview", "system design", "senior")):
        return "sharp-professional"
    if any(x in blob for x in ("rant", "honest", "reality", "no fluff")):
        return "candid-direct"
    return "practical-educational"


def _pick_hook(profile: InfluencerProfile, themes: list[str], angle: str) -> str:
    notes = html.unescape((profile.recent_content_notes or "").strip())
    if notes:
        chunk = re.split(r"[.!?\n]", notes)[0].strip()
        chunk = re.sub(r"\s+", " ", chunk)
        if 12 <= len(chunk) <= 80:
            return chunk
        if chunk:
            return chunk[:77] + "..."
    if len(themes) > 1:
        return f"{themes[0]} + {themes[1]}"
    return f"{angle.replace('_', ' ')} content"


def _recent_snippet(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 90:
        return text[:87] + "..."
    return text


def _pick_collab(profile: InfluencerProfile, settings: Settings) -> str:
    idx = int(hashlib.sha1(profile.id.encode()).hexdigest(), 16) % len(COLLAB_ANGLES)
    # Prefer configured collab type often, but vary for diversity
    if idx % 3 == 0:
        return settings.collab_type
    return COLLAB_ANGLES[idx]


def _follower_band(n: int) -> str:
    if n < 15_000:
        return "growing micro"
    if n < 50_000:
        return "mid micro"
    return "upper micro"


def _stable_pick(seed: str, options: tuple[str, ...] | list[str]) -> str:
    idx = int(hashlib.sha1(seed.encode()).hexdigest(), 16) % len(options)
    return options[idx]


class LocalAIPersonalizer:
    """
    Local AI personalization engine (no external LLM required).

    Pipeline: signal extraction → angle/audience inference → multi-template
    generation with profile-stable variation (not one fixed blurb).
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def personalize(self, profile: InfluencerProfile) -> OutreachMessages:
        sig = extract_signals(profile, self.settings, method="local_ai_engine")
        subject = self._subject(profile, sig)
        body = self._email(profile, sig)
        dm = self._dm(profile, sig)
        return OutreachMessages(
            influencer_id=profile.id,
            email_subject=subject,
            email_body=_fit_word_range(body, 60, 95),
            instagram_dm=_fit_word_range(dm, 15, 30),
            personalization_signals=sig.as_list(),
        )

    def _subject(self, profile: InfluencerProfile, sig: PersonalizationSignals) -> str:
        pattern = _stable_pick(profile.id + "|subj", SUBJECT_PATTERNS)
        angle_short = sig.collab_angle.replace(" collaboration", "").replace(" campaign", "")
        return pattern.format(
            first=sig.first_name,
            theme=sig.primary_theme,
            hook=sig.hook_phrase[:42],
            brand=self.settings.brand_name,
            angle_short=angle_short,
            follower_band=sig.follower_band,
        )

    def _email(self, profile: InfluencerProfile, sig: PersonalizationSignals) -> str:
        hook_pat = _stable_pick(profile.id + "|hook", EMAIL_HOOKS)
        hook_line = hook_pat.format(theme=sig.primary_theme, hook=sig.hook_phrase)
        secondary = (
            f" and {', '.join(sig.secondary_themes)}" if sig.secondary_themes else ""
        )
        return (
            f"Hi {sig.first_name},\n\n"
            f"I came across your {profile.platform.value} channel while researching "
            f"{sig.primary_theme}{secondary} creators — specifically {hook_line}. "
            f"The {sig.tone} tone lands well with {sig.audience_hint}.\n\n"
            f"At {self.settings.brand_name}, we're exploring a {sig.collab_angle} around "
            f"{self.settings.brand_value_prop}. I think a short concept built around "
            f"“{sig.recent_snippet}” could feel native to your audience "
            f"({sig.follower_band}, ~{profile.follower_count:,} followers).\n\n"
            f"Open to a 15-min chat on a paid idea?\n\n"
            f"Best,\n{self.settings.brand_name} Partnerships"
        )

    def _dm(self, profile: InfluencerProfile, sig: PersonalizationSignals) -> str:
        variants = (
            f"Hi {sig.first_name}, your {sig.primary_theme} posts ({sig.hook_phrase[:28]}) "
            f"fit our {sig.collab_angle}. Quick collab chat?",
            f"{sig.first_name} — loved the {sig.content_angle.replace('_', ' ')} angle. "
            f"Your audience matches {self.settings.brand_name}. Open to a UGC idea?",
            f"Hey {sig.first_name}, {sig.audience_hint} + your {sig.primary_theme} style "
            f"= strong fit for a short paid collab. Interested?",
        )
        return _stable_pick(profile.id + "|dm", variants)


class LLMPersonalizer:
    """LLM personalizer with local-AI draft + prompt-engineered refinement."""

    SYSTEM_PROMPT = (
        "You are a senior influencer partnerships copywriter for a tech brand. "
        "Write specific, non-generic outreach. Never invent metrics, case studies, "
        "or personal facts not provided in the input signals. "
        "Vary subject lines; avoid repeating the same formula across creators."
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._local = LocalAIPersonalizer(settings)

    def personalize(self, profile: InfluencerProfile) -> OutreachMessages:
        draft = self._local.personalize(profile)
        if not self.settings.openai_api_key:
            return draft
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
            )
            sig = extract_signals(profile, self.settings, method="llm_refined")
            user_prompt = self._build_prompt(profile, sig, draft)
            completion = client.chat.completions.create(
                model=self.settings.openai_model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.85,
            )
            data = json.loads(completion.choices[0].message.content or "{}")
            signals = list(data.get("signals") or sig.as_list())
            if "method=llm_refined" not in signals:
                signals.append("method=llm_refined")
            return OutreachMessages(
                influencer_id=profile.id,
                email_subject=str(data.get("email_subject") or draft.email_subject),
                email_body=_fit_word_range(str(data.get("email_body") or draft.email_body), 60, 95),
                instagram_dm=_fit_word_range(
                    str(data.get("instagram_dm") or draft.instagram_dm), 15, 30
                ),
                personalization_signals=signals,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM personalization failed, using local AI engine: %s", exc)
            return draft

    def _build_prompt(
        self,
        profile: InfluencerProfile,
        sig: PersonalizationSignals,
        draft: OutreachMessages,
    ) -> str:
        return f"""Refine this influencer outreach for {self.settings.brand_name}.

Brand value proposition: {self.settings.brand_value_prop}
Default collab type: {self.settings.collab_type}

Influencer (ground truth — do not invent beyond this):
- Name: {profile.name}
- Platform: {profile.platform.value}
- Followers: {profile.follower_count}
- Niche: {profile.category}
- Themes: {', '.join(profile.content_themes)}
- About/notes: {profile.recent_content_notes or 'n/a'}
- Profile URL: {profile.profile_url}

Extracted signals:
{json.dumps(sig.as_list(), indent=2)}

Local AI draft (improve specificity & voice; keep facts):
- subject: {draft.email_subject}
- email: {draft.email_body}
- dm: {draft.instagram_dm}

Return JSON with keys:
- email_subject (unique, specific, not generic "Collab idea for your technology audience")
- email_body (60-90 words, reference a concrete signal)
- instagram_dm (15-30 words, natural)
- signals (string array of personalization signals used)
"""


def build_personalizer(settings: Settings) -> Personalizer:
    # Always prefer LLM wrapper: it falls back to local AI engine automatically.
    return LLMPersonalizer(settings)


def _fit_word_range(text: str, min_words: int, max_words: int) -> str:
    words = text.split()
    if len(words) > max_words:
        text = " ".join(words[:max_words])
    if len(text.split()) < min_words:
        text = text.rstrip() + " Looking forward to hearing your thoughts."
    return text.strip()
