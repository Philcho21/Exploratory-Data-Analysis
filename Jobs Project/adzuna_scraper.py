"""
adzuna_scraper.py — Adzuna job search via their free public API
Docs: https://developer.adzuna.com/
Covers: Indeed, Reed, Totaljobs, Guardian Jobs, and 50+ boards across 16 countries.
Rate limit: 250 requests/day on free tier.
"""
import os
import requests
import logging
from utils import JobPosting, parse_salary, normalise_date, extract_skills, polite_delay, apply_geo

logger = logging.getLogger("scraper.adzuna")

# All countries supported by Adzuna's free API
ADZUNA_COUNTRIES = {
    "gb": "United Kingdom",
    "us": "United States",
    "au": "Australia",
    "ca": "Canada",
    "de": "Germany",
    "fr": "France",
    "in": "India",
    "nl": "Netherlands",
    "nz": "New Zealand",
    "pl": "Poland",
    "sg": "Singapore",
    "za": "South Africa",
    "br": "Brazil",
    "mx": "Mexico",
    "at": "Austria",
    "be": "Belgium",
}

ADZUNA_CATEGORIES = {
    "it":          "it-jobs",
    "finance":     "accounting-finance-jobs",
    "hr":          "hr-jobs",
    "engineering": "engineering-jobs",
    "healthcare":  "healthcare-nursing-jobs",
    "marketing":   "marketing-jobs",
    "sales":       "sales-jobs",
    "general":     "",
}


class AdzunaScraper:
    """
    Adzuna Partner API — multi-country, 50+ job boards in one request.
    Pass country='us' / 'de' / 'au' etc. to search outside the UK.
    """

    BASE_URL    = "https://api.adzuna.com/v1/api/jobs"
    source_name = "Adzuna"

    _DEFAULT_APP_ID  = "90961c1a"
    _DEFAULT_API_KEY = "a11a5edd3dd3a5f6c8aee3a76f094c24"

    def __init__(self, app_id: str = None, api_key: str = None):
        self.app_id  = app_id  or os.getenv("ADZUNA_APP_ID")  or self._DEFAULT_APP_ID
        self.api_key = api_key or os.getenv("ADZUNA_API_KEY") or self._DEFAULT_API_KEY
        logger.info(f"AdzunaScraper initialised  app_id=...{self.app_id[-4:]}  key=...{self.api_key[-8:]}")

    def search(
        self,
        keyword:      str,
        location:     str,
        pages:        int = 3,
        country:      str = "gb",
        sector:       str = "general",
        max_days_old: int = 30,
        geo_resolve:  bool = True,
    ) -> list[JobPosting]:
        """
        Search Adzuna for live job postings.

        Args:
            keyword:      Job title / keyword
            location:     City or region (use '' for country-wide)
            pages:        Pages to retrieve (50 results/page)
            country:      ISO country code — see ADZUNA_COUNTRIES
            sector:       Category filter — see ADZUNA_CATEGORIES
            max_days_old: Max age of postings in days
            geo_resolve:  Geocode each posting's location via Nominatim
        """
        all_jobs: list[JobPosting] = []
        seen_ids: set = set()
        category = ADZUNA_CATEGORIES.get(sector, "")
        country  = country.lower()
        country_name = ADZUNA_COUNTRIES.get(country, country.upper())

        for page in range(1, pages + 1):
            if category:
                url = f"{self.BASE_URL}/{country}/{category}/search/{page}"
            else:
                url = f"{self.BASE_URL}/{country}/search/{page}"

            params = {
                "app_id":           self.app_id,
                "app_key":          self.api_key,
                "what":             keyword,
                "where":            location,
                "results_per_page": 50,
                "max_days_old":     max_days_old,
                "sort_by":          "date",
            }

            logger.info(f"  Adzuna [{country_name}] p{page}/{pages}: '{keyword}' in '{location or 'all'}'")

            try:
                resp = requests.get(url, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"  Adzuna error p{page}: {e}")
                break

            results = data.get("results", [])
            if not results:
                logger.info(f"  Adzuna: no more results at page {page}")
                break

            for r in results:
                jid = str(r.get("id", ""))
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)

                sal_min = r.get("salary_min")
                sal_max = r.get("salary_max")
                desc    = r.get("description", "")
                loc_str = r.get("location", {}).get("display_name", location)

                # Build salary_raw from API fields when present
                if sal_min and sal_max:
                    salary_raw = f"{sal_min:,.0f} - {sal_max:,.0f}"
                    currency   = "USD" if country == "us" else \
                                 "EUR" if country in ("de","fr","nl","at","be") else \
                                 "AUD" if country == "au" else \
                                 "CAD" if country == "ca" else \
                                 "INR" if country == "in" else "GBP"
                else:
                    salary_raw = ""
                    _, _, currency = parse_salary("")

                job = JobPosting(
                    job_id        = f"adzuna_{country}_{jid}",
                    title         = r.get("title",   "").strip(),
                    company       = r.get("company", {}).get("display_name", "").strip(),
                    location      = loc_str,
                    salary_raw    = salary_raw,
                    salary_min    = sal_min,
                    salary_max    = sal_max,
                    currency      = currency,
                    contract_type = r.get("contract_time", "full_time").replace("_", "-").title(),
                    description   = desc[:500],
                    skills        = extract_skills(desc),
                    date_posted   = r.get("created", "")[:10],
                    url           = r.get("redirect_url", ""),
                    source        = f"Adzuna/{r.get('category',{}).get('label','')} [{country_name}]",
                )
                if geo_resolve:
                    apply_geo(job)
                all_jobs.append(job)

            logger.info(f"  Adzuna p{page}: +{len(results)} jobs (total: {len(all_jobs)})")
            polite_delay(0.5, 1.2)

        logger.info(f"Adzuna [{country_name}] complete: {len(all_jobs)} postings")
        return all_jobs

    def get_salary_stats(self, keyword: str, location: str = "", country: str = "gb") -> dict:
        url = f"{self.BASE_URL}/{country}/histogram"
        params = {"app_id": self.app_id, "app_key": self.api_key,
                  "what": keyword, "where": location}
        try:
            resp = requests.get(url, params=params, timeout=10)
            return {"keyword": keyword, "location": location, "country": country,
                    "histogram": resp.json().get("histogram", {})}
        except Exception as e:
            logger.warning(f"Adzuna salary stats error: {e}")
            return {}
