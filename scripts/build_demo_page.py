"""Generate a static demo HTML page from sample_run artifacts."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "examples" / "sample_run"
OUT = ROOT / "docs" / "demo" / "index.html"


def main() -> None:
    inf = pd.read_csv(SAMPLE / "influencers.csv")
    track = pd.read_csv(SAMPLE / "outreach_tracker.csv")
    msgs = json.loads((SAMPLE / "messages.json").read_text(encoding="utf-8"))
    summary = json.loads((SAMPLE / "run_summary.json").read_text(encoding="utf-8"))

    # Align messages with enriched CSV order from the same pipeline run.
    samples: list[tuple] = []
    with_email_idx = [i for i, e in enumerate(inf["Email"]) if e != "Not Found"]
    for i in with_email_idx[:3]:
        samples.append((inf.iloc[i], msgs[i]))

    rows_html = []
    for _, r in inf.head(15).iterrows():
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(str(r['Name']))}</td>"
            f"<td>{int(r['Followers']):,}</td>"
            f"<td>{float(r['Engagement']):.2%}</td>"
            f"<td>{html.escape(str(r['Email']))}</td>"
            f"<td><a href=\"{html.escape(str(r['Profile URL']))}\">profile</a></td>"
            "</tr>"
        )

    track_rows = []
    for _, r in track.head(12).iterrows():
        track_rows.append(
            "<tr>"
            f"<td>{html.escape(str(r['Influencer']))}</td>"
            f"<td>{html.escape(str(r['Email']))}</td>"
            f"<td>{html.escape(str(r['Status']))}</td>"
            f"<td>{html.escape(str(r['Detail']))}</td>"
            "</tr>"
        )

    msg_blocks = []
    for r, m in samples:
        msg_blocks.append(
            "<div class='card'>"
            f"<h3>{html.escape(str(r['Name']))}</h3>"
            f"<p class='meta'>{html.escape(str(r['Email']))} · "
            f"{int(r['Followers']):,} followers</p>"
            f"<p class='subj'><strong>Subject:</strong> "
            f"{html.escape(m['email_subject'])}</p>"
            f"<pre>{html.escape(m['email_body'])}</pre>"
            f"<p class='dm'><strong>DM:</strong> "
            f"{html.escape(m['instagram_dm'])}</p>"
            "</div>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>EDXSO Outreach Demo</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; margin: 0; background: #0f1419; color: #e7ecf1; }}
header {{ padding: 28px 36px; background: linear-gradient(120deg, #102033, #1a3a4a); border-bottom: 1px solid #2a3a45; }}
h1 {{ margin: 0 0 8px; font-size: 28px; }}
.sub {{ opacity: .85; }}
.stats {{ display: flex; gap: 16px; padding: 20px 36px; flex-wrap: wrap; }}
.stat {{ background: #18222b; padding: 14px 18px; border-radius: 10px; min-width: 120px; }}
.stat b {{ display: block; font-size: 22px; }}
section {{ padding: 8px 36px 28px; }}
table {{ width: 100%; border-collapse: collapse; background: #18222b; border-radius: 10px; overflow: hidden; }}
th, td {{ padding: 10px 12px; border-bottom: 1px solid #24313c; text-align: left; font-size: 14px; }}
th {{ background: #1e2b36; color: #9fb3c3; }}
a {{ color: #6ec1ff; }}
.card {{ background: #18222b; padding: 16px 18px; border-radius: 10px; margin-bottom: 14px; }}
pre {{ white-space: pre-wrap; background: #101820; padding: 12px; border-radius: 8px; line-height: 1.45; }}
.subj, .dm, .meta {{ color: #b7c5d0; }}
</style>
</head>
<body>
<header>
  <h1>EDXSO Automated Micro-Influencer Outreach</h1>
  <p class="sub">Working demo snapshot · niche=technology · real YouTube public data · emails never fabricated</p>
</header>
<div class="stats">
  <div class="stat"><b>{summary['discovered']}</b>discovered</div>
  <div class="stat"><b>{summary['passed_filter']}</b>passed filter</div>
  <div class="stat"><b>{summary['messages_generated']}</b>messages</div>
  <div class="stat"><b>{summary['emails_sent_or_simulated']}</b>simulated sends</div>
</div>
<section>
  <h2>Influencer dataset (sample rows)</h2>
  <table>
    <thead><tr><th>Name</th><th>Followers</th><th>Engagement</th><th>Email</th><th>Profile</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
  </table>
  <p class="sub">Full dataset: examples/sample_run/influencers.csv ({len(inf)} rows)</p>
</section>
<section>
  <h2>Outreach tracker</h2>
  <table>
    <thead><tr><th>Influencer</th><th>Email</th><th>Status</th><th>Detail</th></tr></thead>
    <tbody>{''.join(track_rows)}</tbody>
  </table>
</section>
<section>
  <h2>Sample personalized outreach</h2>
  {''.join(msg_blocks)}
</section>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
