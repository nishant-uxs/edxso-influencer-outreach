"""Batch LLM personalization with checkpointing + model rotation."""

from __future__ import annotations

import json
import time
from pathlib import Path

from influencer_outreach.cli import _load_profiles
from influencer_outreach.config import Settings
from influencer_outreach.personalization import build_personalizer
from influencer_outreach.storage.exporters import save_messages_json

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "examples" / "sample_run" / "influencers.csv"
PROFILES = ROOT / "examples" / "sample_run" / "enriched_profiles.json"
OUT = ROOT / "examples" / "sample_run" / "messages.json"
CKPT = ROOT / "examples" / "sample_run" / "messages.checkpoint.json"

# Prefer models with separate free-tier quotas
MODEL_ROTATION = [
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash",
]


def main() -> None:
    settings = Settings()
    settings.openai_model = MODEL_ROTATION[0]
    settings.openai_fallback_models = ",".join(MODEL_ROTATION[1:])
    personalizer = build_personalizer(settings)
    profiles = _load_profiles(CSV, PROFILES if PROFILES.exists() else None)

    done: dict[str, dict] = {}
    if CKPT.exists():
        for row in json.loads(CKPT.read_text(encoding="utf-8")):
            done[row["influencer_id"]] = row
        print(f"resumed {len(done)} checkpointed messages")

    for i, profile in enumerate(profiles, start=1):
        if profile.id in done and any(
            s.startswith("method=llm_refined")
            for s in done[profile.id].get("personalization_signals", [])
        ):
            print(f"skip {i}/{len(profiles)} already llm_refined")
            continue

        # rotate preferred model every 8 creators to spread quota
        settings.openai_model = MODEL_ROTATION[(i - 1) % len(MODEL_ROTATION)]
        settings.openai_fallback_models = ",".join(
            m for m in MODEL_ROTATION if m != settings.openai_model
        )
        personalizer = build_personalizer(settings)

        msg = personalizer.personalize(profile)
        done[profile.id] = msg.model_dump(mode="json")
        CKPT.write_text(json.dumps(list(done.values()), indent=2), encoding="utf-8")
        method = next(
            (s for s in msg.personalization_signals if s.startswith("method=")),
            "method=?",
        )
        model = next(
            (s for s in msg.personalization_signals if s.startswith("model=")),
            "model=?",
        )
        print(f"{i}/{len(profiles)} {profile.name[:28]:28} {method} {model}")
        time.sleep(1.2)

    ordered = [done[p.id] for p in profiles if p.id in done]
    # keep pydantic roundtrip via save helper
    from influencer_outreach.models import OutreachMessages

    messages = [OutreachMessages.model_validate(x) for x in ordered]
    save_messages_json(OUT, messages)
    subjects = {m.email_subject for m in messages}
    methods = {
        s
        for m in messages
        for s in m.personalization_signals
        if s.startswith("method=")
    }
    meta = {
        "count": len(messages),
        "unique_subjects": len(subjects),
        "methods": sorted(methods),
        "llm_refined": sum(
            1
            for m in messages
            if any(s == "method=llm_refined" for s in m.personalization_signals)
        ),
        "llm_enabled": True,
    }
    OUT.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(meta)


if __name__ == "__main__":
    main()
