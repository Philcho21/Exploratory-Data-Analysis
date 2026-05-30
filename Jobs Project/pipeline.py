"""
pipeline.py — ETL extraction orchestrator (multi-keyword, multi-source, global)

Sources & limits:
  Reed      — UK Partner API.  100 results/page. No hard daily cap documented.
  Adzuna    — 16 countries.    50 results/page.  250 requests/day FREE TIER HARD LIMIT.
  The Muse  — Global.          100 results/page. No auth, no hard cap.
  Remotive  — Global remote.   Single call, returns all matches.  No cap.
  Arbeitnow — Global tech/EU.  100 results/page. No auth, no hard cap.

Page settings (per keyword, per source):
  Reed:      REED_PAGES      = 5   →  500 results/keyword
  Adzuna:    ADZUNA_PAGES    = 3   →  150 results/keyword/country
  TheMuse:   THEMUSE_PAGES   = 3   →  ~25–50 matched/page (client-side filter)
  Arbeitnow: ARBEITNOW_PAGES = 3   →  ~10–20 matched/page (client-side filter)

Adzuna budget (16 keywords × 5 countries × 3 pages = 240 requests — fits 250/day).

Usage:
    python pipeline.py
    python pipeline.py --keywords "Data Analyst,DevOps Engineer" --countries us,gb
    python pipeline.py --no-geo  # skip geocoding for speed
"""
import argparse
import json
import csv
import hashlib
import logging
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from utils import JobPosting, logger
from reed_scraper      import ReedScraper
from adzuna_scraper    import AdzunaScraper, ADZUNA_COUNTRIES
from themuse_scraper   import TheMuseScraper
from remotive_scraper  import RemotiveScraper
from arbeitnow_scraper import ArbeitnowScraper

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Default keyword set — 16 tech job titles ─────────────────────────────────

DEFAULT_KEYWORDS = [
    "Data Analyst",
    "Data Scientist",
    "Data Engineer",
    "Machine Learning Engineer",
    "MLOps Engineer",
    "DevOps Engineer",
    "Platform Engineer",
    "Site Reliability Engineer",
    "Software Engineer",
    "Backend Developer",
    "Frontend Developer",
    "Full Stack Developer",
    "Cloud Engineer",
    "Python Developer",
    "Java Developer",
    "Business Intelligence Analyst",
]

# ── Page counts per source ────────────────────────────────────────────────────
# Adjust here; Adzuna budget = len(keywords) × len(countries) × ADZUNA_PAGES ≤ 250

REED_PAGES       = 5    # 100 results/page → 500/keyword
ADZUNA_PAGES     = 3    # 50  results/page → 150/keyword/country  (budget: 240/250)
THEMUSE_PAGES    = 3    # ~25–50 matched   → ~75–150/keyword
ARBEITNOW_PAGES  = 3    # ~10–20 matched   → ~30–60/keyword

# ── Adzuna rate-limit guard ───────────────────────────────────────────────────

class AdzunaBudget:
    """
    Tracks Adzuna requests against the 250/day free-tier hard limit.
    Warns when approaching the cap; raises when it would be exceeded.
    """
    DAILY_LIMIT = 250
    WARN_AT     = 220      # warn when 220 of 250 used

    def __init__(self, limit: int = None):
        self.limit = limit or self.DAILY_LIMIT
        self.used  = 0

    def check(self, n: int = 1):
        """Call before making n requests. Raises RuntimeError if over budget."""
        if self.used + n > self.limit:
            raise RuntimeError(
                f"Adzuna daily budget exhausted: {self.used}/{self.limit} used. "
                "Pipeline will skip remaining Adzuna calls for this run."
            )
        if self.used + n >= self.WARN_AT:
            logger.warning(
                f"Adzuna budget: {self.used + n}/{self.limit} — approaching daily limit."
            )

    def consume(self, n: int = 1):
        self.used += n

    def request(self, n: int = 1):
        """check + consume in one call."""
        self.check(n)
        self.consume(n)

    @property
    def remaining(self):
        return self.limit - self.used


# ── Deduplication ─────────────────────────────────────────────────────────────

def fingerprint(job: JobPosting) -> str:
    key = (f"{job.title.lower().strip()}|"
           f"{job.company.lower().strip()}|"
           f"{job.location.lower().strip()}")
    return hashlib.md5(key.encode()).hexdigest()


def deduplicate(jobs: list[JobPosting]) -> list[JobPosting]:
    seen:   set             = set()
    unique: list[JobPosting] = []
    for job in jobs:
        fp = fingerprint(job)
        if fp not in seen:
            seen.add(fp)
            unique.append(job)
    removed = len(jobs) - len(unique)
    logger.info(f"Deduplication: {len(jobs):,} → {len(unique):,} ({removed:,} dupes removed)")
    return unique


# ── Savers ────────────────────────────────────────────────────────────────────

def save_csv(jobs: list[JobPosting], path: Path):
    if not jobs:
        return
    fieldnames = list(jobs[0].to_dict().keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in jobs:
            row = job.to_dict()
            row["skills"] = ", ".join(row["skills"])
            writer.writerow(row)
    logger.info(f"CSV saved → {path} ({len(jobs):,} rows)")


def save_json(jobs: list[JobPosting], path: Path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([j.to_dict() for j in jobs], f, indent=2, default=str)
    logger.info(f"JSON saved → {path} ({len(jobs):,} records)")


def save_summary(jobs: list[JobPosting], keywords: list[str], location: str, path: Path):
    if not jobs:
        return

    salaries     = [j.salary_min for j in jobs if j.salary_min]
    avg_sal      = sum(salaries) / len(salaries) if salaries else 0
    top_skills   = Counter(s for j in jobs for s in j.skills).most_common(15)
    by_source    = Counter(j.source        for j in jobs)
    by_contract  = Counter(j.contract_type for j in jobs)
    by_country   = Counter(j.geo_country   for j in jobs if j.geo_country)
    by_currency  = Counter(j.currency      for j in jobs)
    by_title     = Counter(j.title         for j in jobs)

    lines = [
        "RECRUITMENT INTELLIGENCE BRIEFING",
        f"Generated  : {datetime.utcnow().strftime('%d %b %Y %H:%M UTC')}",
        f"Keywords   : {', '.join(keywords)}",
        f"Location   : {location or 'global (all countries)'}",
        "=" * 68,
        f"\nTOTAL UNIQUE VACANCIES : {len(jobs):,}",
        f"\nSOURCE BREAKDOWN:",
        *[f"  {src:<45} {n:>5} postings" for src, n in by_source.most_common()],
        f"\nGEO DISTRIBUTION (top 12 countries):",
        *[f"  {c:<35} {n:>5}" for c, n in by_country.most_common(12)],
        f"\nCURRENCIES:",
        *[f"  {cur:<12} {n:>5} postings" for cur, n in by_currency.most_common()],
        f"\nCONTRACT TYPES:",
        *[f"  {ct:<35} {n:>5}" for ct, n in by_contract.most_common()],
        f"\nSALARY INTELLIGENCE:",
        (f"  Average min salary : {avg_sal:,.0f} (local currency)"
         if avg_sal else "  Salary data limited across sources"),
        f"  Roles with salary  : {len(salaries):,} / {len(jobs):,} ({100*len(salaries)//len(jobs) if jobs else 0}%)",
        f"\nTOP JOB TITLES (by posting volume):",
        *[f"  {i+1:>2}. {t:<40} {n:>5}" for i, (t, n) in enumerate(by_title.most_common(10))],
        f"\nTOP IN-DEMAND SKILLS (across all roles):",
        *[f"  {i+1:>2}. {skill:<32} ({count:,} mentions)"
          for i, (skill, count) in enumerate(top_skills)],
        f"\nSAMPLE VACANCIES (10 most recent):",
    ]
    for j in sorted(jobs, key=lambda x: x.date_posted, reverse=True)[:10]:
        geo_tag = (f" ({j.geo_city}, {j.geo_country})" if j.geo_city
                   else f" ({j.geo_country})"         if j.geo_country else "")
        lines += [
            f"\n  {j.title} — {j.company}",
            f"  Location : {j.location}{geo_tag}",
            f"  Salary   : {j.salary_raw or 'Not stated'} ({j.currency})",
            f"  Source   : {j.source}  |  Posted: {j.date_posted}",
            f"  URL      : {j.url}",
        ]
    lines.append("\n" + "=" * 68)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Summary saved → {path}")


# ── Per-source scrapers ───────────────────────────────────────────────────────

def _run_reed(keyword: str, location: str, pages: int,
              reed: ReedScraper, geo: bool) -> list[JobPosting]:
    try:
        results = reed.search(keyword, location or "London",
                              pages=pages, geo_resolve=geo)
        logger.info(f"    Reed '{keyword}': {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"    Reed '{keyword}' failed: {e}")
        return []


def _run_adzuna(keyword: str, location: str, pages: int, country: str,
                adzuna: AdzunaScraper, budget: AdzunaBudget, geo: bool) -> list[JobPosting]:
    try:
        budget.request(pages)
    except RuntimeError as e:
        logger.warning(f"    Adzuna budget: {e}")
        return []
    try:
        results = adzuna.search(keyword, location, pages=pages,
                                country=country, geo_resolve=geo)
        logger.info(f"    Adzuna [{country.upper()}] '{keyword}': {len(results)} jobs "
                    f"(budget used: {budget.used}/{budget.limit})")
        return results
    except Exception as e:
        logger.error(f"    Adzuna [{country}] '{keyword}' failed: {e}")
        return []


def _run_themuse(keyword: str, pages: int,
                 muse: TheMuseScraper, geo: bool) -> list[JobPosting]:
    try:
        results = muse.search(keyword, pages=pages, geo_resolve=geo)
        logger.info(f"    TheMuse '{keyword}': {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"    TheMuse '{keyword}' failed: {e}")
        return []


def _run_remotive(keyword: str, remotive: RemotiveScraper) -> list[JobPosting]:
    try:
        results = remotive.search(keyword)
        logger.info(f"    Remotive '{keyword}': {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"    Remotive '{keyword}' failed: {e}")
        return []


def _run_arbeitnow(keyword: str, location: str, pages: int,
                   arb: ArbeitnowScraper, geo: bool) -> list[JobPosting]:
    try:
        results = arb.search(keyword, location=location,
                             pages=pages, geo_resolve=geo)
        logger.info(f"    Arbeitnow '{keyword}': {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"    Arbeitnow '{keyword}' failed: {e}")
        return []


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run_pipeline(
    keywords:          list[str]  = None,
    location:          str        = "",
    countries:         list[str]  = None,
    reed_pages:        int        = REED_PAGES,
    adzuna_pages:      int        = ADZUNA_PAGES,
    themuse_pages:     int        = THEMUSE_PAGES,
    arbeitnow_pages:   int        = ARBEITNOW_PAGES,
    reed_key:          str        = None,
    adzuna_id:         str        = None,
    adzuna_key:        str        = None,
    include_reed:      bool       = True,
    include_adzuna:    bool       = True,
    include_themuse:   bool       = True,
    include_remotive:  bool       = True,
    include_arbeitnow: bool       = True,
    geo_resolve:       bool       = True,
    adzuna_daily_limit: int       = 250,
) -> list[JobPosting]:

    keywords  = keywords  or DEFAULT_KEYWORDS
    countries = countries or ["gb", "us", "de", "fr", "au"]

    reed_key   = reed_key   or os.getenv("REED_API_KEY")   or ReedScraper._DEFAULT_KEY
    adzuna_id  = adzuna_id  or os.getenv("ADZUNA_APP_ID")  or AdzunaScraper._DEFAULT_APP_ID
    adzuna_key = adzuna_key or os.getenv("ADZUNA_API_KEY") or AdzunaScraper._DEFAULT_API_KEY

    # Pre-flight budget check
    adzuna_needed = len(keywords) * len(countries) * adzuna_pages
    budget = AdzunaBudget(adzuna_daily_limit)
    logger.info(f"\n{'='*68}")
    logger.info("EXTRACTION PIPELINE START")
    logger.info(f"Keywords   : {len(keywords)} titles")
    logger.info(f"Countries  : {countries}")
    logger.info(f"Pages      : Reed={reed_pages}(×100) | Adzuna={adzuna_pages}(×50) | "
                f"TheMuse={themuse_pages} | Arbeitnow={arbeitnow_pages}")
    logger.info(f"Adzuna req : {adzuna_needed} / {adzuna_daily_limit} daily limit "
                f"({'✓ OK' if adzuna_needed <= adzuna_daily_limit else '⚠ OVER BUDGET — some calls will be skipped'})")
    logger.info(f"Geo-resolve: {geo_resolve}")
    logger.info(f"{'='*68}\n")

    # Instantiate scrapers once (shared across all keywords)
    reed     = ReedScraper(api_key=reed_key)           if include_reed      else None
    adzuna   = AdzunaScraper(app_id=adzuna_id,
                              api_key=adzuna_key)       if include_adzuna    else None
    muse     = TheMuseScraper()                         if include_themuse   else None
    remotive = RemotiveScraper()                        if include_remotive  else None
    arb      = ArbeitnowScraper()                       if include_arbeitnow else None

    all_jobs: list[JobPosting] = []
    kw_totals: dict[str, int]  = {}

    for i, keyword in enumerate(keywords, 1):
        logger.info(f"\n── Keyword {i}/{len(keywords)}: '{keyword}' ──")
        kw_start = len(all_jobs)

        # ── Reed (UK only) ────────────────────────────────────────────────────
        if reed and "gb" in countries:
            all_jobs.extend(_run_reed(keyword, location, reed_pages, reed, geo_resolve))

        # ── Adzuna (each country) ─────────────────────────────────────────────
        if adzuna:
            for country in countries:
                results = _run_adzuna(keyword, location, adzuna_pages,
                                      country, adzuna, budget, geo_resolve)
                all_jobs.extend(results)

        # ── The Muse ──────────────────────────────────────────────────────────
        if muse:
            all_jobs.extend(_run_themuse(keyword, themuse_pages, muse, geo_resolve))

        # ── Remotive ──────────────────────────────────────────────────────────
        if remotive:
            all_jobs.extend(_run_remotive(keyword, remotive))

        # ── Arbeitnow ─────────────────────────────────────────────────────────
        if arb:
            all_jobs.extend(_run_arbeitnow(keyword, location, arbeitnow_pages, arb, geo_resolve))

        kw_count = len(all_jobs) - kw_start
        kw_totals[keyword] = kw_count
        logger.info(f"  '{keyword}' subtotal: {kw_count:,} raw  |  running total: {len(all_jobs):,}")

    logger.info(f"\n── Raw total: {len(all_jobs):,} postings across all keywords ──")
    logger.info(f"── Adzuna requests used: {budget.used}/{budget.limit} ──")

    # ── Deduplicate globally ──────────────────────────────────────────────────
    jobs = deduplicate(all_jobs)

    # ── Keyword coverage report ───────────────────────────────────────────────
    logger.info("\nPer-keyword raw counts:")
    for kw, n in sorted(kw_totals.items(), key=lambda x: -x[1]):
        logger.info(f"  {kw:<40} {n:>6,} raw jobs")

    # ── Persist ───────────────────────────────────────────────────────────────
    ts   = datetime.utcnow().strftime("%Y%m%d_%H%M")
    slug = f"multi_keyword_{ts}"
    save_csv(jobs,      OUTPUT_DIR / f"{slug}.csv")
    save_json(jobs,     OUTPUT_DIR / f"{slug}.json")
    save_summary(jobs, keywords, location, OUTPUT_DIR / f"{slug}_briefing.txt")

    logger.info(f"\n✓ Pipeline complete — {len(jobs):,} unique vacancies\n")
    return jobs


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Global multi-keyword recruitment ETL pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Default keywords ({len(DEFAULT_KEYWORDS)}):
  {'\n  '.join(DEFAULT_KEYWORDS[:8])}
  ... (use --keywords to override)

Adzuna budget: len(keywords) × len(countries) × adzuna_pages ≤ 250/day
  Default: {len(DEFAULT_KEYWORDS)} × 5 × {ADZUNA_PAGES} = {len(DEFAULT_KEYWORDS)*5*ADZUNA_PAGES} requests

Examples:
  python pipeline.py                                   # full run, all 16 keywords
  python pipeline.py --keywords "Data Analyst,DevOps"  # subset
  python pipeline.py --countries us,gb --no-geo        # fast, no geocoding
        """
    )
    parser.add_argument("--keywords",    default=None,
                        help="Comma-separated job titles (default: all 16)")
    parser.add_argument("--location",    default="",
                        help="City filter (empty = country-wide)")
    parser.add_argument("--countries",   default="gb,us,de,fr,au",
                        help="Comma-separated Adzuna country codes")
    parser.add_argument("--reed-pages",      default=REED_PAGES,      type=int)
    parser.add_argument("--adzuna-pages",    default=ADZUNA_PAGES,    type=int)
    parser.add_argument("--themuse-pages",   default=THEMUSE_PAGES,   type=int)
    parser.add_argument("--arbeitnow-pages", default=ARBEITNOW_PAGES, type=int)
    parser.add_argument("--adzuna-limit",    default=250, type=int,
                        help="Override Adzuna daily request cap (default 250)")
    parser.add_argument("--reed-key",    default=None)
    parser.add_argument("--adzuna-id",   default=None)
    parser.add_argument("--adzuna-key",  default=None)
    parser.add_argument("--no-reed",      action="store_true")
    parser.add_argument("--no-adzuna",    action="store_true")
    parser.add_argument("--no-remote",    action="store_true")
    parser.add_argument("--no-themuse",   action="store_true")
    parser.add_argument("--no-arbeitnow", action="store_true")
    parser.add_argument("--no-geo",       action="store_true",
                        help="Skip geocoding (faster)")
    args = parser.parse_args()

    kw_list = ([k.strip() for k in args.keywords.split(",")]
               if args.keywords else DEFAULT_KEYWORDS)

    jobs = run_pipeline(
        keywords          = kw_list,
        location          = args.location,
        countries         = [c.strip() for c in args.countries.split(",")],
        reed_pages        = args.reed_pages,
        adzuna_pages      = args.adzuna_pages,
        themuse_pages     = args.themuse_pages,
        arbeitnow_pages   = args.arbeitnow_pages,
        reed_key          = args.reed_key   or os.getenv("REED_API_KEY"),
        adzuna_id         = args.adzuna_id  or os.getenv("ADZUNA_APP_ID"),
        adzuna_key        = args.adzuna_key or os.getenv("ADZUNA_API_KEY"),
        include_reed      = not args.no_reed,
        include_adzuna    = not args.no_adzuna,
        include_themuse   = not args.no_themuse,
        include_remotive  = not args.no_remote,
        include_arbeitnow = not args.no_arbeitnow,
        geo_resolve       = not args.no_geo,
        adzuna_daily_limit= args.adzuna_limit,
    )

    print(f"\n{'='*68}")
    print(f"EXTRACTION COMPLETE — {len(jobs):,} unique job postings")
    print(f"Outputs: {OUTPUT_DIR.resolve()}")
    print("=" * 68)
