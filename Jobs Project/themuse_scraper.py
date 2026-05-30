"""
themuse_scraper.py — The Muse job search API (free tier, no auth required)
Docs: https://www.themuse.com/developers/api/v2
Global coverage, rich company data, unlimited free reads (no key needed).
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

logger = logging.getLogger("scraper.themuse")

# The Muse level → seniority label mapping
LEVEL_MAP = {
    "internship":         "Internship",
    "entry level":        "Entry-Level",
    "mid level":          "Mid-Level",
    "senior level":       "Senior",
    "management":         "Management",
    "director":           "Director",
    "vp":                 "VP",
    "svp":                "SVP",
    "evp":                "EVP",
    "c suite":            "C-Suite",
}


class TheMuseScraper:
    """
    The Muse public API — no API key required.
    Covers US + international remote roles; great for tech, finance, marketing.
    """

    BASE_URL    = "https://www.themuse.com/api/public/jobs"
    source_name = "TheMuse"

    def search(
        self,
        keyword:     str,
        location:    str  = "",
        pages:       int  = 3,
        category:    str  = "",
        geo_resolve: bool = True,
    ) -> list[JobPosting]:
        """
        Search The Muse for job postings.

        Args:
            keyword:     Job title or keyword to filter by (client-side)
            location:    City name or '' for global/remote
            pages:       Number of pages (100 results/page)
            category:    Optional Muse category e.g. 'Data and Analytics',
                         'Software Engineer', 'Finance', 'HR & Recruiting'
            geo_resolve: Geocode each posting's location
        """
        all_jobs:  list[JobPosting] = []
        seen_ids:  set              = set()
        kw_lower = keyword.lower()

        for page in range(pages):
            params: dict = {"page": page, "descending": "true"}
            if category:
                params["category"] = category
            if location:
                params["location"] = location

            logger.info(f"  TheMuse p{page+1}/{pages}: '{keyword}' location='{location or 'global'}'")

            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"  TheMuse error p{page+1}: {e}")
                break

            results = data.get("results", [])
            if not results:
                logger.info(f"  TheMuse: no results at p{page+1}")
                break

            matched = 0
            for r in results:
                # Client-side keyword filter (API has no keyword param)
                name     = r.get("name", "")
                contents = r.get("contents", "")
                plain    = _strip_html(contents)          # strip HTML before matching
                if kw_lower and kw_lower not in name.lower() and kw_lower not in plain.lower():
                    continue

                jid = str(r.get("id", ""))
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)

                # Location: list of dicts [{name: "New York, NY"}]
                locs     = r.get("locations", [])
                loc_str  = locs[0].get("name", "") if locs else ""

                # Seniority from levels list
                levels   = [l.get("name", "").lower() for l in r.get("levels", [])]
                seniority = LEVEL_MAP.get(levels[0], levels[0].title()) if levels else ""

                # Published date
                pub_date = r.get("publication_date", "")[:10]

                company  = r.get("company", {}).get("name", "")
                job_url  = r.get("refs", {}).get("landing_page", "")

                job = JobPosting(
                    job_id        = f"themuse_{jid}",
                    title         = name.strip(),
                    company       = company.strip(),
                    location      = loc_str,
                    salary_raw    = "",         # Muse doesn't expose salary
                    currency      = "USD",
                    contract_type = seniority or "Full-time",
                    description   = plain[:500],
                    skills        = extract_skills(plain),
                    date_posted   = pub_date,
                    url           = job_url,
                    source        = self.source_name,
                )
                if geo_resolve:
                    apply_geo(job)
                all_jobs.append(job)
                matched += 1

            logger.info(f"  TheMuse p{page+1}: {matched} matched (total: {len(all_jobs)})")
            polite_delay(0.8, 1.5)

        logger.info(f"TheMuse complete: {len(all_jobs)} postings for '{keyword}'")
        return all_jobs


if __name__ == "__main__":
    import json
    s = TheMuseScraper()
    jobs = s.search(keyword="data analyst", pages=1)
    print(json.dumps([j.to_dict() for j in jobs[:2]], indent=2, default=str))
    print(f"✓ {len(jobs)} jobs")
