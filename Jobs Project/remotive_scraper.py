"""
remotive_scraper.py — Remotive.com remote jobs API (free, no auth)
Docs: https://remotive.com/api/remote-jobs
Global remote-first jobs. No key required; single endpoint.
"""
import requests
import logging
from utils import JobPosting, parse_salary, extract_skills, normalise_date, polite_delay, apply_geo

logger = logging.getLogger("scraper.remotive")

# Remotive category slugs
REMOTIVE_CATEGORIES = [
    "software-dev", "customer-support", "design", "marketing",
    "sales", "product", "business", "data", "devops", "finance",
    "hr", "qa", "writing", "all-other",
]


class RemotiveScraper:
    """
    Remotive.com API — curated remote jobs worldwide, free & no API key.
    Results are always remote-first; location = candidate timezone/region.
    """

    BASE_URL    = "https://remotive.com/api/remote-jobs"
    source_name = "Remotive"

    def search(
        self,
        keyword:     str,
        location:    str  = "",        # used as label only; all Remotive jobs are remote
        pages:       int  = 1,         # API returns all matches in one call; pages ignored
        category:    str  = "",        # Remotive category slug
        geo_resolve: bool = False,     # most Remotive jobs have no fixed location
    ) -> list[JobPosting]:
        """
        Fetch Remotive remote jobs matching keyword.

        Args:
            keyword:  Search term (job title / skill)
            location: Candidate region filter (e.g. 'Europe', 'USA') — advisory
            category: Remotive category slug (see REMOTIVE_CATEGORIES)
            geo_resolve: Geocode candidate_required_location if set
        """
        params: dict = {"search": keyword, "limit": 500}
        if category:
            params["category"] = category

        logger.info(f"  Remotive: '{keyword}' (remote, category='{category or 'all'}')")

        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"  Remotive error: {e}")
            return []

        results  = data.get("jobs", [])
        all_jobs: list[JobPosting] = []
        seen_ids: set              = set()

        for r in results:
            jid = str(r.get("id", ""))
            if jid in seen_ids:
                continue
            seen_ids.add(jid)

            sal_raw          = r.get("salary", "")
            sal_min, sal_max, currency = parse_salary(sal_raw)
            desc             = r.get("description", "")
            candidate_region = r.get("candidate_required_location", "Worldwide")
            pub_date         = r.get("publication_date", "")[:10]

            job = JobPosting(
                job_id        = f"remotive_{jid}",
                title         = r.get("title",        "").strip(),
                company       = r.get("company_name", "").strip(),
                location      = f"Remote — {candidate_region}" if candidate_region else "Remote",
                salary_raw    = sal_raw,
                salary_min    = sal_min,
                salary_max    = sal_max,
                currency      = currency,
                contract_type = r.get("job_type", "full_time").replace("_", "-").title(),
                description   = desc[:500],
                skills        = extract_skills(" ".join(r.get("tags") or []) + " " + desc),
                date_posted   = pub_date,
                url           = r.get("url", ""),
                source        = f"Remotive/{r.get('category','remote')}",
                # geo: remote jobs have no fixed lat/lon — leave blank
                geo_city      = "",
                geo_country   = candidate_region,
                geo_lat       = None,
                geo_lon       = None,
            )
            if geo_resolve and candidate_region and candidate_region.lower() != "worldwide":
                apply_geo(job)
            all_jobs.append(job)

        logger.info(f"Remotive complete: {len(all_jobs)} remote postings for '{keyword}'")
        return all_jobs


if __name__ == "__main__":
    import json
    s = RemotiveScraper()
    jobs = s.search(keyword="data analyst", category="data")
    print(json.dumps([j.to_dict() for j in jobs[:2]], indent=2, default=str))
    print(f"✓ {len(jobs)} jobs")
