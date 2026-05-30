# Recruitment Intelligence Pipeline — Project Overview

## What We Built

A fully automated, multi-source job market data collection system that scrapes live job postings from five APIs across 16 countries, enriches them with geographic coordinates, and saves structured datasets ready for analysis — all on a 12-hour recurring schedule.

---

## The Problem It Solves

Recruitment data is fragmented across dozens of job boards. No single source gives a complete picture of the market. This pipeline aggregates all of them into one clean, deduplicated dataset with consistent fields, making it possible to answer questions like: *Which skills are most in demand? What does a Data Engineer earn in Germany vs the US? How many DevOps roles are being posted this week?*

---

## Data Sources (All Free Tier)

| Source | Coverage | Jobs/run (est.) |
|--------|----------|----------------|
| **Reed** | UK | ~8,000 |
| **Adzuna** | 16 countries (GB, US, DE, FR, AU, CA, IN + 9 more) | ~12,000 |
| **The Muse** | Global (US-heavy) | ~1,200 |
| **Remotive** | Global remote jobs | ~320 |
| **Arbeitnow** | Global tech, strong EU | ~700 |

**Target yield:** ~14,000 unique postings per full run after deduplication.

---

## Job Titles Tracked (16)

Data Analyst · Data Scientist · Data Engineer · Machine Learning Engineer · MLOps Engineer · DevOps Engineer · Platform Engineer · Site Reliability Engineer · Software Engineer · Backend Developer · Frontend Developer · Full Stack Developer · Cloud Engineer · Python Developer · Java Developer · Business Intelligence Analyst

---

## What Each Job Record Contains

Every posting is captured with 19 structured fields:

- **Identity** — unique ID, job title, company name
- **Location** — raw location string from the source, plus geocoded `city`, `country`, `latitude`, `longitude` (via OpenStreetMap, no key needed)
- **Salary** — raw salary string, parsed `min`/`max` as annual figures, currency code (GBP/USD/EUR/AUD etc.)
- **Role details** — contract type, first 500 characters of description
- **Skills** — up to 15 skills auto-detected from the description (matched against a 60-term library covering cloud, data, finance, HR, and general skills)
- **Metadata** — date posted (normalised to ISO format), source URL, data source name, scrape timestamp

---

## Key Technical Features

**Multi-source deduplication.** The same job posted on both Reed and Adzuna is stored only once, identified by a fingerprint of title + company + location.

**Global salary parsing.** Handles `£30k–£40k`, `$90,000`, `€50k`, `£350/day`, `$45/hour` — all normalised to annual equivalents in the detected currency.

**Automatic geocoding.** Every location string is resolved to lat/lon coordinates using the free Nominatim (OpenStreetMap) API, cached in memory to avoid redundant lookups.

**Adzuna budget guard.** Adzuna's free tier allows exactly 250 API requests per day. The pipeline tracks usage at runtime, warns at 220, and stops gracefully at 250 rather than hitting a hard API error.

**Scheduled automation.** The scheduler runs the full pipeline immediately on start, then repeats every 12 hours. It handles `Ctrl+C` cleanly, waits for the current run to finish before exiting, and writes rotating logs to `logs/scheduler.log`.

---

## Output Files

Each run produces three files in the `output/` folder:

| File | Use |
|------|-----|
| `.csv` | Excel, pandas, BI tools, SQL import |
| `.json` | Downstream APIs, database loading |
| `_briefing.txt` | Human-readable summary with skill rankings, salary averages, geo distribution, and sample postings |

---

## File Structure

```
Jobs Project/
├── pipeline.py          # Main orchestrator — runs all sources, deduplicates, saves
├── scheduler.py         # Runs pipeline every 12 hours automatically
├── utils.py             # Shared data model, geocoder, salary parser, skill extractor
├── reed_scraper.py      # Reed.co.uk UK Partner API
├── adzuna_scraper.py    # Adzuna — 16 countries, 50+ boards per country
├── themuse_scraper.py   # The Muse — global, no key required
├── remotive_scraper.py  # Remotive — global remote jobs, no key required
├── arbeitnow_scraper.py # Arbeitnow — global tech/EU, no key required
├── base_scraper.py      # Shared base class (rotating headers, retry logic)
├── requirements.txt     # pip dependencies
├── Dockerfile           # Container image definition
├── docker-compose.yml   # One-command production deployment
├── output/              # Generated — CSV, JSON, briefing files
└── logs/                # Generated — rotating scheduler logs
```

---

## How to Run

**One-off full run:**
```bash
pip install -r requirements.txt
python pipeline.py
```

**Automated every 12 hours:**
```bash
python scheduler.py
```

**Docker (background, persistent):**
```bash
docker-compose up -d
```

No API keys required — working credentials are built in. See `OPERATIONS_GUIDE.md` for the full CLI reference and advanced options.
