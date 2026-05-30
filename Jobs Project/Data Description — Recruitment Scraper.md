# Data Description — Recruitment Scraper Pipeline

## Overview

Each pipeline run produces a single unified dataset of deduplicated job
postings collected from five global sources. The data is structured around
a flat record per job posting, enriched with normalised salary figures,
geolocation coordinates, detected skills, and source metadata.

---

## Output files

Three files are written to `output/` on every run, sharing the same
timestamp in their filename (`multi_keyword_YYYYMMDD_HHMM`):

| File | Format | Best used for |
|------|--------|---------------|
| `*.csv` | Comma-separated, UTF-8 | Excel, pandas, BI tools |
| `*.json` | Indented JSON array | APIs, NoSQL ingestion, Python |
| `*_briefing.txt` | Plain text report | Quick human review |

---

## Data schema

Every record — whether from the CSV, JSON, or as a Python `JobPosting`
object — has the following fields:

### Identity

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `job_id` | string | Unique identifier prefixed by source | `adzuna_gb_4829301` |
| `source` | string | Source name and country/category | `Adzuna/IT Jobs [United Kingdom]` |
| `url` | string | Direct link to the original posting | `https://...` |
| `scraped_at` | ISO datetime | UTC timestamp when the record was collected | `2026-05-30T10:22:14.331` |

**`job_id` prefixes by source:**

| Prefix | Source |
|--------|--------|
| `reed_` | Reed.co.uk |
| `adzuna_gb_`, `adzuna_us_`, `adzuna_de_`, etc. | Adzuna (country-specific) |
| `themuse_` | The Muse |
| `remotive_` | Remotive |
| `arbeitnow_` | Arbeitnow |

### Job details

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `title` | string | Job title as posted | `Senior Data Engineer` |
| `company` | string | Hiring company name | `DeepMind` |
| `contract_type` | string | Employment type | `Full-time`, `Part-time`, `Remote`, `Contract`, `Senior` |
| `date_posted` | ISO date | Date the job was posted (normalised) | `2026-05-28` |
| `description` | string | First 500 characters of the job description (HTML stripped) | `We are looking for...` |

### Location

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `location` | string | Location string as returned by the source | `London, Greater London` |
| `geo_city` | string | Resolved city name via Nominatim | `London` |
| `geo_country` | string | Resolved country name via Nominatim | `United Kingdom` |
| `geo_lat` | float or null | Latitude (WGS84) | `51.5074` |
| `geo_lon` | float or null | Longitude (WGS84) | `-0.1278` |

**Notes on geo fields:**
- Populated by the Nominatim (OpenStreetMap) geocoder, which is free and
  requires no key.
- Remote jobs from Remotive have `geo_city` and `geo_lat`/`geo_lon` left
  blank; `geo_country` holds the candidate region string
  (e.g. `"Worldwide"`, `"Europe"`, `"USA"`).
- Geocoding can be disabled with `--no-geo`, in which case all four geo
  fields are empty/null.
- Results are cached in-process, so repeated location strings within a run
  only trigger one Nominatim call.

### Salary

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `salary_raw` | string | Salary as written in the original posting | `£55,000 - £70,000` |
| `salary_min` | float or null | Normalised minimum annual salary | `55000.0` |
| `salary_max` | float or null | Normalised maximum annual salary | `70000.0` |
| `currency` | string | ISO 4217 currency code | `GBP`, `USD`, `EUR`, `INR` |

**Salary normalisation rules:**
- Daily rates (e.g. `£350/day`) are annualised at **220 working days**
- Hourly rates (e.g. `$45/hr`) are annualised at **1,760 working hours**
- Shorthand values (e.g. `£40k`) are expanded to full integers
- Salary-less postings have `null` in `salary_min` and `salary_max`
- `salary_raw` is always preserved verbatim from the source
- Currency is detected from the symbol in `salary_raw`, or inferred from
  the source country when the API returns numeric fields without a symbol

**Currency by source:**

| Source | Default currency | Notes |
|--------|-----------------|-------|
| Reed | GBP | UK-only source |
| Adzuna GB | GBP | |
| Adzuna US | USD | |
| Adzuna DE / FR / NL / AT / BE | EUR | |
| Adzuna AU | AUD | |
| Adzuna CA | CAD | |
| Adzuna IN | INR | |
| TheMuse | USD | US-dominant source |
| Remotive | Detected from `salary` field | Mixed; often USD |
| Arbeitnow | EUR | European-dominant source |

### Skills

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `skills` | list of strings (CSV: comma-separated) | Skills detected in the job description | `["python", "sql", "aws", "docker"]` |

Skills are extracted by scanning the full job description against a
library of ~65 known skill terms. The library covers:

- **Programming:** Python, SQL, Java, JavaScript, TypeScript, Go, Rust,
  Scala, R, MATLAB
- **Web / backend:** React, Node.js, FastAPI, Django, Flask
- **Data:** Spark, Kafka, Airflow, dbt, Snowflake, Hadoop, PostgreSQL,
  MongoDB, Elasticsearch, Redis
- **Cloud & DevOps:** AWS, Azure, GCP, Docker, Kubernetes, Terraform, Git
- **Analytics:** Power BI, Tableau, Excel, Bloomberg, VBA
- **Finance:** Financial Modelling, IFRS, GAAP, CFA, Risk Management
- **HR:** ATS, HRIS, Talent Acquisition, Workforce Planning
- **General:** Agile, Scrum, Jira, Confluence, Salesforce, CRM, Leadership,
  Stakeholder Management, Negotiation, Project Management, UX, Figma

Maximum 15 skills stored per posting.

---

## Data sources

| Source | Coverage | Auth | Results/page | Daily limit | Geo note |
|--------|----------|------|-------------|-------------|----------|
| Reed.co.uk | United Kingdom | API key (built-in) | 100 | None documented | UK locations |
| Adzuna | 16 countries | API key (built-in) | 50 max | **250 requests/day** | Multi-country |
| The Muse | Global (US-heavy) | None | ~100 | None | US + international |
| Remotive | Global remote | None | All in one call | None | No fixed location |
| Arbeitnow | Global (EU-heavy) | None | ~100 | None | EU + international |

---

## Deduplication

Cross-source duplicates are removed using an MD5 fingerprint of the
normalised tuple `(title.lower(), company.lower(), location.lower())`.
This means:

- The same job appearing on both Reed and Adzuna is kept once
- Slight variations in title capitalisation or spacing are collapsed
- Postings with identical title and company but different locations are
  treated as distinct roles
- The first occurrence seen wins; later duplicates are discarded

Deduplication is applied **globally after all sources and all keywords**
have been collected, so a "Data Analyst" posting at the same company
found under both the "Data Analyst" and "Data Scientist" keyword passes
only once into the final dataset.

Typical deduplication rate: 25–40% of raw results removed.

---

## Volume and scale

With default settings (16 keywords, 5 countries, standard page counts):

| Source | Raw results (approx.) | Notes |
|--------|-----------------------|-------|
| Reed | ~8,000 | 16 kw × 5 pages × 100 |
| Adzuna | ~12,000 | 16 kw × 5 countries × 3 pages × 50 |
| TheMuse | ~1,200 | Client-side filter; yield varies by keyword |
| Remotive | ~300 | Single call per keyword; remote-only |
| Arbeitnow | ~600 | Client-side filter; EU-heavy |
| **Total raw** | **~22,000** | Before deduplication |
| **After dedup** | **~13,000–15,000** | Typical range |

A single pipeline run at default settings comfortably exceeds 2,000 unique
job postings and typically returns 10,000–15,000.

---

## Briefing report structure

The `*_briefing.txt` file is a human-readable summary written after every
run. It contains:

1. Run metadata: timestamp, keywords searched, location filter
2. Total unique vacancy count
3. Source breakdown: postings per source
4. Geo distribution: top 12 countries by posting count
5. Currency breakdown: postings per currency
6. Contract type breakdown
7. Salary intelligence: average minimum salary (local currency),
   percentage of postings with salary data
8. Top 10 job titles by posting volume
9. Top 15 in-demand skills by mention count across all descriptions
10. 10 most recently posted sample vacancies with title, company,
    location, salary, source, and URL

---

## Notes on data quality

- **Descriptions** are capped at 500 characters. Full descriptions are not
  stored in order to stay within free API tiers and keep file sizes
  manageable.
- **Salary coverage** varies significantly by source. Reed and Adzuna GB
  have the best salary coverage (~40–60% of postings). TheMuse and
  Arbeitnow rarely include salary data.
- **Date normalisation** converts relative strings ("3 days ago", "Today")
  and multiple date formats (`dd/mm/yyyy`, `YYYY-MM-DD`, `dd Mon YYYY`)
  to ISO 8601 (`YYYY-MM-DD`). Unparseable dates are stored as-is.
- **Geocoding accuracy** depends on how specific the location string is.
  City-level strings ("London", "Berlin") resolve reliably. Vague strings
  ("Remote — Europe") resolve poorly or not at all, and geo fields are
  left blank rather than guessing.
- **Skills extraction** is keyword-based, not NLP-based. It will miss
  skills not in the library and may occasionally false-positive on
  coincidental mentions.