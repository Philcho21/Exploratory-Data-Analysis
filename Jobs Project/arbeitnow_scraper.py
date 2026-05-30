"""
arbeitnow_scraper.py — Arbeitnow job board API (free, no auth)
Docs: https://arbeitnow.com/api
Global tech jobs with strong European coverage; supports visa sponsorship filter.
No API key required.
"""
import re
import requests
import logging
from utils import JobPosting, extract_skills, normalise_date, polite_delay, apply_geo


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities to plain text."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = (text.replace("&amp;", "&").replace("&nbsp;", " ")
                .replace("&lt;", "<").replace("&gt;", ">")
                .replace("&#39;", "'").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", text).strip()

logger = logging.getLogger("scraper.arbeitnow")


class ArbeitnowScraper:
    """
    Arbeitnow public API — free, no key, paginated, global tech jobs.
    Strong coverage for Germany, Netherlands, UK, and remote roles.
    """

    BASE_URL    = "https://arbeitnow.com/api/job-board-api"
    source_name = "Arbeitnow"

    def search(
        self,
        keyword:        str,
        location:       str  = "",
        pages:          int  = 3,
        visa_sponsored: bool = False,
        remote_only:    bool = False,
        geo_resolve:    bool = True,
    ) -> list[JobPosting]:
        """
        Search Arbeitnow for tech jobs.

        Args:
            keyword:        Job title / keyword (client-side filter)
            location:       Location string to filter by (client-side)
            pages:          Pages to fetch (up to 100 results/page)
            visa_sponsored: Only return roles with visa sponsorship
            remote_only:    Only return remote roles
            geo_resolve:    Geocode each posting's location
        """
        all_jobs: list[JobPosting] = []
        seen_slugs: set = set()
        kw_lower  = keyword.lower()
        loc_lower = location.lower()

        for page in range(1, pages + 1):
            params: dict = {"page": page}

            logger.info(f"  Arbeitnow p{page}/{pages}: '{keyword}' location='{location or 'global'}'")

            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"  Arbeitnow error p{page}: {e}")
                break

            results = data.get("data", [])
            if not results:
                logger.info(f"  Arbeitnow: no results at p{page}")
                break

            matched = 0
            for r in results:
                slug  = r.get("slug", "")
                title = r.get("title", "")
                tags  = " ".join(r.get("tags") or [])
                desc  = _strip_html(r.get("description", ""))   # strip HTML

                # Client-side filters
                if kw_lower and (kw_lower not in title.lower() and
                                 kw_lower not in desc.lower() and
                                 kw_lower not in tags.lower()):
                    continue
                loc_str = r.get("location", "")
                if loc_lower and loc_lower not in loc_str.lower():
                    continue
                if visa_sponsored and not r.get("visa_sponsorship", False):
                    continue
                if remote_only and not r.get("remote", False):
                    continue
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                contract = "Remote" if r.get("remote") else "On-site"
                pub_date = r.get("created_at", "")[:10]

                job = JobPosting(
                    job_id        = f"arbeitnow_{slug}",
                    title         = title.strip(),
                    company       = r.get("company_name", "").strip(),
                    location      = loc_str,
                    salary_raw    = "",          # Arbeitnow rarely exposes salary
                    currency      = "EUR",       # primarily European jobs
                    contract_type = contract,
                    description   = desc[:500],
                    skills        = extract_skills(tags + " " + desc),
                    date_posted   = pub_date,
                    url           = r.get("url", ""),
                    source        = self.source_name,
                )
                if geo_resolve:
                    apply_geo(job)
                all_jobs.append(job)
                matched += 1

            logger.info(f"  Arbeitnow p{page}: {matched} matched (total: {len(all_jobs)})")
            polite_delay(0.6, 1.3)

            # Stop if API signals last page
            meta = data.get("meta", {})
            if page >= meta.get("last_page", page):
                break

        logger.info(f"Arbeitnow complete: {len(all_jobs)} postings for '{keyword}'")
        return all_jobs


if __name__ == "__main__":
    import json
    s = ArbeitnowScraper()
    jobs = s.search(keyword="data analyst", pages=1)
    print(json.dumps([j.to_dict() for j in jobs[:2]], indent=2, default=str))
    print(f"✓ {len(jobs)} jobs")
