"""
scheduler.py — runs the extraction pipeline every 12 hours.

Usage:
    python scheduler.py                          # all 16 keywords, gb/us/de/fr/au
    python scheduler.py --keywords "Data Analyst,DevOps Engineer"
    python scheduler.py --interval 6             # every 6 hours
    python scheduler.py --no-geo                 # skip geocoding (faster)

Stops cleanly on Ctrl+C / SIGTERM.
Logs to stdout and logs/scheduler.log (rotating, 5 × 10 MB).
"""
import logging
import os
import signal
import argparse
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import schedule

from pipeline import (
    run_pipeline,
    DEFAULT_KEYWORDS,
    REED_PAGES,
    ADZUNA_PAGES,
    THEMUSE_PAGES,
    ARBEITNOW_PAGES,
)

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

_root = logging.getLogger()
_root.setLevel(logging.INFO)
_fmt  = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                           datefmt="%H:%M:%S")
_fh   = RotatingFileHandler(LOG_DIR / "scheduler.log",
                             maxBytes=10 * 1024 * 1024, backupCount=5,
                             encoding="utf-8")
_fh.setFormatter(_fmt)
_root.addHandler(_fh)

logger = logging.getLogger("scheduler")

# ── Graceful shutdown ─────────────────────────────────────────────────────────

_shutdown = False

def _handle_signal(signum, _frame):
    global _shutdown
    logger.info(f"Signal {signum} received — stopping after current run.")
    _shutdown = True

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ── Job wrapper ───────────────────────────────────────────────────────────────

def _run_job(cfg: dict):
    start = datetime.utcnow()
    logger.info(f"\n{'='*64}")
    logger.info(f"SCHEDULED RUN  {start.strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info(f"{'='*64}")
    try:
        jobs    = run_pipeline(**cfg)
        elapsed = (datetime.utcnow() - start).total_seconds()
        logger.info(f"Run finished in {elapsed:.1f}s — {len(jobs):,} unique postings.")
    except Exception as e:
        logger.exception(f"Pipeline run failed: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scheduled recruitment pipeline — runs every N hours",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scheduler.py
  python scheduler.py --keywords "Data Analyst,DevOps Engineer" --countries gb,us
  python scheduler.py --interval 6 --no-geo
        """
    )
    parser.add_argument("--keywords",        default=None,
                        help="Comma-separated job titles (default: all 16)")
    parser.add_argument("--location",        default="")
    parser.add_argument("--countries",       default="gb,us,de,fr,au")
    parser.add_argument("--interval",        default=12, type=int,
                        help="Hours between runs (default: 12)")
    parser.add_argument("--reed-pages",      default=REED_PAGES,      type=int)
    parser.add_argument("--adzuna-pages",    default=ADZUNA_PAGES,    type=int)
    parser.add_argument("--themuse-pages",   default=THEMUSE_PAGES,   type=int)
    parser.add_argument("--arbeitnow-pages", default=ARBEITNOW_PAGES, type=int)
    parser.add_argument("--no-reed",         action="store_true")
    parser.add_argument("--no-adzuna",       action="store_true")
    parser.add_argument("--no-remote",       action="store_true")
    parser.add_argument("--no-themuse",      action="store_true")
    parser.add_argument("--no-arbeitnow",    action="store_true")
    parser.add_argument("--no-geo",          action="store_true")
    args = parser.parse_args()

    kw_list = ([k.strip() for k in args.keywords.split(",")]
               if args.keywords else DEFAULT_KEYWORDS)

    cfg = dict(
        keywords          = kw_list,
        location          = args.location,
        countries         = [c.strip() for c in args.countries.split(",")],
        reed_pages        = args.reed_pages,
        adzuna_pages      = args.adzuna_pages,
        themuse_pages     = args.themuse_pages,
        arbeitnow_pages   = args.arbeitnow_pages,
        reed_key          = os.getenv("REED_API_KEY"),
        adzuna_id         = os.getenv("ADZUNA_APP_ID"),
        adzuna_key        = os.getenv("ADZUNA_API_KEY"),
        include_reed      = not args.no_reed,
        include_adzuna    = not args.no_adzuna,
        include_remotive  = not args.no_remote,
        include_themuse   = not args.no_themuse,
        include_arbeitnow = not args.no_arbeitnow,
        geo_resolve       = not args.no_geo,
    )

    logger.info(f"Scheduler starting — interval: every {args.interval}h")
    logger.info(f"Keywords: {len(kw_list)}  Countries: {cfg['countries']}")

    # Run immediately on start
    _run_job(cfg)

    # Schedule recurring runs
    schedule.every(args.interval).hours.do(_run_job, cfg=cfg)
    logger.info(f"Next run in {args.interval} hour(s). Ctrl+C to stop.")

    while not _shutdown:
        schedule.run_pending()
        time.sleep(30)

    logger.info("Scheduler stopped cleanly.")


if __name__ == "__main__":
    main()