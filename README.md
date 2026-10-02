# EDXSO Assignment 1 — Automated Micro-Influencer Outreach

Production-minded Python pipeline that discovers micro-influencers, filters for brand fit,
enriches public contact signals, personalizes outreach, and tracks every send attempt.

**Never fabricates emails or follower metrics.** Missing emails are stored as `Not Found`.

## Architecture

### System overview

```mermaid
flowchart TB
  subgraph User
    CLI["CLI<br/>influencer-outreach run"]
  end

  subgraph Core["influencer_outreach"]
    CFG["Settings / .env"]
    PIPE["OutreachPipeline<br/>pipeline/runner.py"]
    CLI --> PIPE
    CFG --> PIPE

    PIPE --> DISC["Discovery"]
    PIPE --> FILT["Brand-fit Filter"]
    PIPE --> ENR["Enricher"]
    PIPE --> PERS["Personalizer"]
    PIPE --> SEND["Sender"]
    PIPE --> STORE["OutreachStore"]
    PIPE --> EXP["Exporters<br/>CSV / JSON"]
  end

  subgraph External["External systems"]
    YTAPI["YouTube Data API"]
    YTDLP["yt-dlp public search"]
    WEB["Public profile / website HTML"]
    LLM["OpenAI-compatible API<br/>optional"]
    SMTP["SMTP relay<br/>optional"]
  end

  subgraph Data["Local artifacts"]
    RAW["data/raw/"]
    PROC["data/processed/"]
    OUT["data/outreach/"]
    DB[("SQLite<br/>outreach.db")]
  end

  DISC --> YTAPI
  DISC --> YTDLP
  ENR --> WEB
  PERS --> LLM
  SEND --> SMTP
  STORE --> DB
  EXP --> RAW
  EXP --> PROC
  EXP --> OUT
```

### End-to-end pipeline

```mermaid
flowchart LR
  A[Discover<br/>≥50 creators] --> B[Filter<br/>micro + niche]
  B --> C[Enrich<br/>public email/site]
  C --> D[Personalize<br/>email + DM]
  D --> E{Email found?}
  E -->|Yes| F[Send or Simulate]
  E -->|No| G[Skip<br/>Not Found]
  F --> H[Track + export]
  G --> H
```

### Component map

```mermaid
flowchart TB
  subgraph entry["Entry"]
    cli["cli.py"]
    main["__main__.py"]
  end

  subgraph orchestration["Orchestration"]
    runner["pipeline/runner.py"]
    config["config.py"]
    models["models.py"]
  end

  subgraph stages["Pipeline stages"]
    disc["discovery/<br/>YouTubeDiscovery"]
    filt["filtering/<br/>BrandFitFilter"]
    enr["enrichment/<br/>ProfileEnricher"]
    pers["personalization/<br/>Template | LLM"]
    send["sending/<br/>OutreachSender"]
  end

  subgraph persistence["Persistence"]
    track["tracking/store.py"]
    storage["storage/exporters.py"]
  end

  cli --> runner
  main --> cli
  config --> runner
  models -.-> stages
  runner --> disc
  runner --> filt
  runner --> enr
  runner --> pers
  runner --> send
  send --> track
  runner --> storage
```

### Discovery decision flow

```mermaid
flowchart TD
  START([discover niche, limit]) --> KEY{YOUTUBE_API_KEY set?}
  KEY -->|Yes| API[YouTube Data API<br/>search + channels]
  KEY -->|No| YT[yt-dlp ytsearch<br/>+ channel /about]
  API --> BUCKET[Bucket by follower band]
  YT --> BUCKET
  BUCKET --> MICRO{5k–100k<br/>subscribers?}
  MICRO -->|Yes| KEEP[Prefer micro list]
  MICRO -->|No| EXTRA[Extras pool]
  KEEP --> ENOUGH{micro ≥ limit?}
  ENOUGH -->|No| MORE[Next query]
  MORE --> KEY
  ENOUGH -->|Yes| OUT[Return micro profiles]
  EXTRA -.->|fallback if thin| OUT
```

### Send + tracking states

```mermaid
stateDiagram-v2
  [*] --> Pending
  Pending --> Skipped: no email / duplicate
  Pending --> Simulated: default / no SMTP
  Pending --> Sent: SMTP success
  Pending --> Failed: SMTP error
  Simulated --> [*]
  Sent --> [*]
  Skipped --> [*]
  Failed --> [*]
```

### Data flow

```mermaid
flowchart LR
  subgraph inputs
    ENV[.env / Settings]
    NICHE[Niche queries]
  end

  subgraph transforms
    P1[InfluencerProfile]
    P2[FilterResult]
    P3[Enriched Profile]
    P4[OutreachMessages]
    P5[OutreachLogEntry]
  end

  subgraph outputs
    J1[discovered.json]
    C1[filter_report.csv]
    C2[influencers.csv]
    J2[messages.json]
    C3[outreach_tracker.csv]
    J3[run_summary.json]
    DB[(outreach.db)]
  end

  ENV --> P1
  NICHE --> P1
  P1 --> J1
  P1 --> P2
  P2 --> C1
  P2 --> P3
  P3 --> C2
  P3 --> P4
  P4 --> J2
  P4 --> P5
  P5 --> C3
  P5 --> DB
  P5 --> J3
```

## Pipeline stages

| Stage | Module | Behavior |
|-------|--------|----------|
| Discovery | `discovery/youtube.py` | YouTube Data API if `YOUTUBE_API_KEY` is set; otherwise public `yt-dlp` search |
| Filter | `filtering/brand_fit.py` | Micro band (5k–100k), platform, engagement soft-check, tech niche keywords |
| Enrich | `enrichment/enricher.py` | Concurrent public HTML scrape for mailto / website; no invented contacts |
| Personalize | `personalization/` | Template engine by default; optional OpenAI-compatible LLM |
| Send | `sending/sender.py` | Simulate by default; optional SMTP |
| Track | `tracking/store.py` | SQLite + JSON/CSV exports, dedupe keys |

## Quick start

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env

# Run full pipeline (simulate sends)
influencer-outreach run --niche technology --limit 60

# Or:
python -m influencer_outreach.cli run --niche technology --limit 60
```

Artifacts land under `data/`:

- `data/raw/discovered.json`
- `data/processed/filter_report.csv`
- `data/processed/influencers.csv`
- `data/outreach/messages.json`
- `data/outreach/outreach_tracker.csv`
- `data/outreach/run_summary.json`

## Configuration

See `.env.example`. Important knobs:

| Variable | Default | Notes |
|----------|---------|-------|
| `NICHE` | `technology` | Primary assignment niche |
| `MIN_FOLLOWERS` / `MAX_FOLLOWERS` | 5k / 100k | Micro-influencer band |
| `YOUTUBE_API_KEY` | empty | Recommended for higher-quality discovery |
| `SMTP_*` | empty | Leave empty to simulate |
| `OPENAI_API_KEY` | empty | Falls back to local templates |

## Design notes (quality & scale)

- **Typed domain models** (`pydantic`) shared across stages — easy to add Instagram/TikTok providers.
- **Pluggable discovery** via `DiscoveryProvider` ABC.
- **Concurrent enrichment** with bounded workers.
- **Idempotent outreach** via SQLite `dedupe_key` (safe re-runs).
- **CLI** with Typer + Rich summaries for ops use.

## Tests

```bash
pytest -q
```

## Project layout

```
src/influencer_outreach/
  discovery/       # YouTube provider
  filtering/       # Brand-fit rules
  enrichment/      # Public contact enrichment
  personalization/ # Template + optional LLM
  sending/         # SMTP / simulate
  tracking/        # SQLite tracker
  storage/         # CSV/JSON exporters
  pipeline/        # Orchestration
  cli.py
```

## Assignment mapping

1. **Discovery** — ≥50 YouTube tech creators via API or yt-dlp (real public metadata).
2. **Filtering** — technology / developer-education brand-fit + micro follower band.
3. **Enrichment** — public email/website extraction; `Not Found` when unavailable.
4. **Personalization** — niche/theme-aware email (60–90 words) + short DM.
5. **Sending** — simulated by default; real SMTP when configured.
6. **Tracking** — CSV/JSON/SQLite with influencer, email, generated, sent, date, status.

## License

Assignment submission code — use at your own risk for outreach compliance (CAN-SPAM / GDPR).
