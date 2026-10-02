from influencer_outreach.personalization.personalizer import (
    LLMPersonalizer,
    LocalAIPersonalizer,
    build_personalizer,
    extract_signals,
)

# Backward-compatible alias used in older tests/docs
TemplatePersonalizer = LocalAIPersonalizer

__all__ = [
    "LLMPersonalizer",
    "LocalAIPersonalizer",
    "TemplatePersonalizer",
    "build_personalizer",
    "extract_signals",
]
