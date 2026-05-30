"""
utils.py — shared helpers for the recruitment scraper pipeline
"""
import time
import random
import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("scraper")


# ── Data model ──────────────────────────────────────────────────────────────

@dataclass
class JobPosting:
    job_id:        str            = ""
    title:         str            = ""
    company:       str            = ""
    location:      str            = ""
    # ── Geo fields (new) ────────────────────────────────────────────────────
    geo_city:      str            = ""
    geo_country:   str            = ""
    geo_lat:       Optional[float] = None
    geo_lon:       Optional[float] = None
    # ────────────────────────────────────────────────────────────────────────
    salary_raw:    str            = ""
    salary_min:    Optional[float] = None
    salary_max:    Optional[float] = None
    currency:      str            = "GBP"          # NEW — tracks currency
    contract_type: str            = ""
    description:   str            = ""
    skills:        list           = field(default_factory=list)
    date_posted:   str            = ""
    url:           str            = ""
    source:        str            = ""
    scraped_at:    str            = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )

    def to_dict(self):
        return asdict(self)


# ── Geocoder (Nominatim / OpenStreetMap — free, no key) ─────────────────────

_GEO_CACHE: dict[str, dict] = {}          # simple in-process cache

def geocode(location_str: str) -> dict:
    """
    Resolves a free-text location to {city, country, lat, lon}.
    Uses Nominatim (OpenStreetMap) — free, no API key required.
    Results are cached in-process to minimise requests.
    Returns an empty dict on failure.
    """
    if not location_str:
        return {}
    key = location_str.strip().lower()
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location_str, "format": "json", "limit": 1,
                    "addressdetails": 1},
            headers={"User-Agent": "recruitment-scraper-pipeline/1.0"},
            timeout=8,
        )
        resp.raise_for_status()
        hits = resp.json()
        if not hits:
            _GEO_CACHE[key] = {}
            return {}
        h   = hits[0]
        addr = h.get("address", {})
        result = {
            "city":    (addr.get("city") or addr.get("town") or
                        addr.get("village") or addr.get("county") or ""),
            "country": addr.get("country", ""),
            "lat":     float(h.get("lat", 0)),
            "lon":     float(h.get("lon", 0)),
        }
        _GEO_CACHE[key] = result
        # Nominatim asks for ≤1 req/s — polite_delay is called by scrapers anyway
        time.sleep(1.1)
        return result
    except Exception as e:
        logger.debug(f"Geocode failed for '{location_str}': {e}")
        _GEO_CACHE[key] = {}
        return {}


def apply_geo(job: "JobPosting") -> "JobPosting":
    """Fills geo_* fields on a JobPosting in place. Returns the job."""
    if job.geo_lat is not None:          # already resolved
        return job
    geo = geocode(job.location)
    if geo:
        job.geo_city    = geo.get("city", "")
        job.geo_country = geo.get("country", "")
        job.geo_lat     = geo.get("lat")
        job.geo_lon     = geo.get("lon")
    return job


# ── Salary parser ────────────────────────────────────────────────────────────

CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR", "₹": "INR",
                    "A$": "AUD", "C$": "CAD", "¥": "JPY"}

def parse_salary(raw: str) -> tuple[Optional[float], Optional[float], str]:
    """
    Extracts (min, max, currency) from messy salary strings.
    Handles: '£30k–£40k', '$90,000', '€50k', 'Competitive', '£200/day', etc.
    Returns floats as annual equivalents where possible.
    """
    if not raw:
        return None, None, "GBP"

    # detect currency
    currency = "GBP"
    for sym, code in CURRENCY_SYMBOLS.items():
        if sym in raw:
            currency = code
            break

    cleaned = raw.replace(",", "").replace(" ", "").lower()
    cleaned = re.sub(r"[£$€₹¥]", "", cleaned)

    # daily rate → annual (220 working days)
    daily = re.search(r"([\d.]+)(?:k)?/(?:day|pd)", cleaned)
    if daily:
        rate = float(daily.group(1))
        if rate < 500:
            rate *= 220
        return rate, rate, currency

    # hourly rate → annual (1,760 hours)
    hourly = re.search(r"([\d.]+)/(?:hour|hr|h)\b", cleaned)
    if hourly:
        rate = float(hourly.group(1)) * 1760
        return rate, rate, currency

    nums = re.findall(r"([\d.]+)k?", cleaned)
    if not nums:
        return None, None, currency
    values = [float(n) * 1000 if float(n) < 1000 else float(n) for n in nums]
    values = [v for v in values if v >= 1000]   # strip stray small numbers
    values.sort()
    if not values:
        return None, None, currency
    if len(values) == 1:
        return values[0], values[0], currency
    return values[0], values[-1], currency


# ── Date normaliser ──────────────────────────────────────────────────────────

def normalise_date(raw: str) -> str:
    """Converts relative strings like '3 days ago', 'Today' to ISO dates."""
    if not raw:
        return ""
    raw = raw.strip().lower()
    today = datetime.utcnow().date()
    if raw in ("today", "just now", "a moment ago"):
        return str(today)
    m = re.search(r"(\d+)\s*(hour|day|week|month)", raw)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {
            "hour":  timedelta(hours=n),
            "day":   timedelta(days=n),
            "week":  timedelta(weeks=n),
            "month": timedelta(days=n * 30),
        }
        return str(today - delta.get(unit, timedelta(0)))
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return str(datetime.strptime(raw, fmt).date())
        except ValueError:
            continue
    return raw


# ── Skills extractor ─────────────────────────────────────────────────────────

SKILLS_LIBRARY = {
    # Tech
    "python", "sql", "java", "javascript", "typescript", "react", "node.js",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "git",
    "machine learning", "data analysis", "power bi", "tableau", "excel",
    "spark", "hadoop", "kafka", "airflow", "dbt", "snowflake", "redis",
    "postgresql", "mongodb", "elasticsearch", "fastapi", "django", "flask",
    "rust", "go", "scala", "r", "matlab",
    # Finance
    "financial modelling", "ifrs", "gaap", "bloomberg", "vba", "quickbooks",
    "accounts payable", "accounts receivable", "risk management", "cfa",
    # HR / Recruitment
    "ats", "talent acquisition", "stakeholder management", "interviewing",
    "onboarding", "hris", "workforce planning", "succession planning",
    # General
    "project management", "agile", "scrum", "communication", "leadership",
    "salesforce", "crm", "microsoft office", "negotiation", "jira",
    "confluence", "product management", "ux", "ui", "figma",
}


def extract_skills(text: str) -> list:
    text_lower = text.lower()
    found = sorted({s for s in SKILLS_LIBRARY if s in text_lower})
    return found[:15]   # cap at 15 per posting


# ── Polite delay ─────────────────────────────────────────────────────────────

def polite_delay(min_s: float = 1.5, max_s: float = 4.0):
    """Random sleep between requests to avoid rate-limiting."""
    time.sleep(random.uniform(min_s, max_s))
