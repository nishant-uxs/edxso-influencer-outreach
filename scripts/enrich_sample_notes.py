"""Fetch public about text for sample influencers to improve AI personalization signals."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "examples" / "sample_run" / "influencers.csv"
OUT = ROOT / "examples" / "sample_run" / "enriched_profiles.json"


def _clean_text(raw: str) -> str:
    text = unescape(raw)
    # Fix common mojibake / smart punctuation from HTML meta tags
    replacements = {
        "â€™": "'",
        "â€˜": "'",
        "â€œ": '"',
        "â€": '"',
        "â€“": "-",
        "â€”": "-",
        "Ã—": "x",
        "&amp;": "&",
        "&#39;": "'",
        "&quot;": '"',
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    try:
        # If string is mojibake of utf-8 interpreted as latin-1
        repaired = text.encode("latin-1", errors="ignore").decode("utf-8", errors="ignore")
        if repaired and len(repaired) > 10:
            text = repaired
    except Exception:
        pass
    return re.sub(r"\s+", " ", text).strip()


def _about(url: str, client: httpx.Client) -> str:
    try:
        resp = client.get(url, timeout=20)
        if resp.status_code >= 400:
            return ""
        html = resp.text
        for pattern in (
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'"shortDescription":"(.*?)"',
        ):
            m = re.search(pattern, html, flags=re.I)
            if m:
                raw = m.group(1)
                # Prefer JSON-style unescape only for shortDescription patterns
                if "shortDescription" in pattern:
                    try:
                        raw = bytes(raw, "utf-8").decode("unicode_escape")
                    except Exception:
                        pass
                return _clean_text(raw)[:500]
        return ""
    except Exception:
        return ""


def main() -> None:
    df = pd.read_csv(CSV)
    rows: dict[str, dict] = {}
    with httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": "EDXSO-InfluencerOutreach/0.1 (+research)"},
    ) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futs = {
                pool.submit(_about, str(r["Profile URL"]), client): r for _, r in df.iterrows()
            }
            for fut in as_completed(futs):
                r = futs[fut]
                notes = fut.result() or ""
                themes = [t.strip() for t in str(r["Content Theme"]).split(";") if t.strip()]
                rows[str(r["Name"])] = {
                    "id": str(r["Profile URL"]).rstrip("/").split("/")[-1],
                    "name": r["Name"],
                    "platform": r["Platform"],
                    "profile_url": r["Profile URL"],
                    "follower_count": int(r["Followers"]),
                    "engagement_rate": float(r["Engagement"]),
                    "category": r["Niche"],
                    "content_themes": themes,
                    "contact_email": r["Email"],
                    "website": None if pd.isna(r.get("Website")) else r.get("Website"),
                    "recent_content_notes": notes
                    or f"{r['Name']} covers {', '.join(themes)} on YouTube.",
                    "raw": {"notes_source": "public_meta" if notes else "theme_fallback"},
                }
    ordered = [rows[n] for n in df["Name"].tolist() if n in rows]
    OUT.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    with_notes = sum(1 for x in ordered if x["raw"]["notes_source"] == "public_meta")
    print(f"wrote {OUT} ({len(ordered)} profiles, {with_notes} with public meta notes)")


if __name__ == "__main__":
    main()
