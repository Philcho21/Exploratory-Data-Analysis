"""
reed_scraper.py — Reed.co.uk job scraper via their official Partner API
Docs: https://www.reed.co.uk/developers/jobseeker
Auth: HTTP Basic — API key as username, empty string as password.
Note: Reed is UK-only; geo_resolve gives lat/lon for each posting.
"""
import os
import requests
import logging
from datetime import datetime as dt
from utils import JobPosting, parse_salary, normalise_date, extract_skills, polite_delay, apply_geo

logger = logging.getLogger("scraper.reed")


class ReedScraper:
    BASE_URL    = "https://www.reed.co.uk/api/1.0"
    source_name = "Reed"
    _DEFAULT_KEY = "5a0eae8b-7e33-45a5-bc0b-c8d567d5e94a"

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("REED_API_KEY") or self._DEFAULT_KEY
        self.session = requests.Session()
        self.session.auth = (self.api_key, "")
        self.session.headers.update({"Accept": "application/json"})
        logger.info(f"ReedScraper initialised  key=...{self.api_key[-8:]}")

    def _check_key(self):
        try:
            resp = self.session.get(
                f"{self.BASE_URL}/search",
                params={"keywords": "test", "resultsToTake": 1},
                timeout=10,
            )
            if resp.status_code == 401:
                raise ValueError("Reed API: 401 Unauthorized — key rejected.")
            if resp.status_code == 403:
                raise ValueError("Reed API: 403 Forbidden — key inactive or pending approval.")
            resp.raise_for_status()
            logger.info("  Reed key validated ✓")
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"  Reed key preflight inconclusive: {e}")

    def search(
        self,
        keyword:        str,
        location:       str,
        pages:          int  = 3,
        distance_miles: int  = 15,
        geo_resolve:    bool = True,
    ) -> list[JobPosting]:
        self._check_key()

        all_jobs: list[JobPosting] = []
        seen_ids: set = set()

        for page in range(pages):
            logger.info(f"  Reed p{page+1}/{pages}: '{keyword}' near '{location}'")
            params = {
                "keywords":             keyword,
                "location":             location,
                "distancefromLocation": distance_miles,
                "resultsToSkip":        page * 100,
                "resultsToTake":        100,
            }
            try:
                resp = self.session.get(f"{self.BASE_URL}/search", params=params, timeout=15)
                if resp.status_code == 401:
                    raise ValueError("Reed API: 401 mid-search — aborting.")
                resp.raise_for_status()
                data = resp.json()
            except ValueError:
                raise
            except Exception as e:
                logger.warning(f"  Reed error on p{page+1}: {e}")
                break

            results = data.get("results", [])
            if not results:
                logger.info(f"  Reed: no more results at p{page+1}")
                break

            for r in results:
                jid = str(r.get("jobId", ""))
                if jid in seen_ids:
                    continue
                seen_ids.add(jid)

                sal_raw = r.get("salary", "")
                sal_min, sal_max, currency = parse_salary(sal_raw)
                if sal_min is None:
                    sal_min = r.get("minimumSalary")
                if sal_max is None:
                    sal_max = r.get("maximumSalary")

                raw_date = r.get("date", "")
                try:
                    posted = str(dt.strptime(raw_date, "%d/%m/%Y").date())
                except (ValueError, TypeError):
                    posted = normalise_date(raw_date)

                desc    = r.get("jobDescription", "")
                loc_str = r.get("locationName", "").strip()

                job = JobPosting(
                    job_id        = f"reed_{jid}",
                    title         = r.get("jobTitle",     "").strip(),
                    company       = r.get("employerName", "").strip(),
                    location      = loc_str,
                    salary_raw    = sal_raw,
                    salary_min    = sal_min,
                    salary_max    = sal_max,
                    currency      = currency,
                    contract_type = "Part-time" if r.get("partTime") else "Full-time",
                    description   = desc[:500],
                    skills        = extract_skills(desc),
                    date_posted   = posted,
                    url           = r.get("jobUrl", ""),
                    source        = self.source_name,
                )
                if geo_resolve:
                    apply_geo(job)
                all_jobs.append(job)

            logger.info(f"  Reed p{page+1}: +{len(results)} jobs (total: {len(all_jobs)})")
            polite_delay(0.7, 1.5)

        logger.info(f"Reed complete: {len(all_jobs)} unique postings")
        return all_jobs


if __name__ == "__main__":
    import json
    scraper = ReedScraper()
    jobs = scraper.search(keyword="Data Analyst", location="London", pages=1)
    if jobs:
        print(json.dumps([j.to_dict() for j in jobs[:2]], indent=2, default=str))
        print(f"\n✓ {len(jobs)} live Reed jobs fetched")
    else:
        print("No jobs returned.")
