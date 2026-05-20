from __future__ import annotations

import argparse
import logging
import smtplib
import sys
from pathlib import Path

# Ensure package root on path when run as script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import httpx

from jobintel import config
from jobintel.emailer import send_digest
from jobintel.filters import filter_jobs
from jobintel.models import Job
from jobintel.sources import all_fetchers
from jobintel.storage import JobStore

log = logging.getLogger("jobintel")

DEFAULT_REGIONS = ("remote", "uk", "us", "eu", "canada")


def _collect_jobs() -> list[Job]:
    out: list[Job] = []
    with httpx.Client(
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True,
    ) as client:
        for fetch in all_fetchers():
            try:
                jobs = fetch(client)
                log.info("%s: fetched %d jobs", fetch.__name__, len(jobs))
                out.extend(jobs)
            except (httpx.HTTPError, httpx.TransportError, OSError, ValueError) as e:
                log.warning("%s failed: %s", fetch.__name__, e)
    return out


def cmd_run(args: argparse.Namespace) -> int:
    config.validate(email_required=not args.no_email and not args.dry_run)

    raw = _collect_jobs()
    log.info("Total raw jobs fetched: %d", len(raw))

    region_arg = None if args.all_regions else tuple(args.regions or DEFAULT_REGIONS)
    filtered = filter_jobs(raw, regions=region_arg)
    log.info("After vertical+region filter: %d", len(filtered))

    with JobStore(args.db) as store:
        new_jobs = store.filter_new(filtered)
        log.info("New (not yet seen): %d", len(new_jobs))

        if args.dry_run:
            for j in new_jobs:
                print(f"{j.title} @ {j.company} | {j.url}")
            print(
                f"\n{len(new_jobs)} new (of {len(filtered)} filtered, {len(raw)} raw)",
                file=sys.stderr,
            )
            return 0

        if not new_jobs:
            log.info("No new jobs — nothing to do.")
            return 0

        if not args.no_email:
            try:
                send_digest(new_jobs)
            except (RuntimeError, smtplib.SMTPException, OSError) as e:
                log.error("Email failed: %s — printing listings to stdout instead.", e)
                for j in new_jobs:
                    print(f"  {j.title} @ {j.company} — {j.url}")
        else:
            for j in new_jobs:
                print(f"{j.title} @ {j.company} | {j.url}")

        store.insert_many(new_jobs)
        log.info("Saved %d new jobs to store.", len(new_jobs))

    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    import subprocess

    gui_path = Path(__file__).parent / "gui.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(gui_path)], check=True)
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    import sqlite3

    p = Path(args.db) if args.db else _ROOT / "data" / "jobintel.sqlite"
    if not p.exists():
        print("No database yet. Run `run` first.")
        return 1
    conn = sqlite3.connect(p)
    n = conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
    conn.close()
    print(f"Tracked unique roles (fingerprint): {n}")
    return 0


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    ap = argparse.ArgumentParser(
        description="JobIntel — aggregate, filter, dedupe, email new roles.",
        epilog=(
            "Schedule (example): 0 7,12,18 * * *  cd /path/to/project && "
            ".venv/bin/python -m jobintel run"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Fetch sources, filter, email new only, persist.")
    p_run.add_argument("--dry-run", action="store_true", help="Do not save or email; print new matches.")
    p_run.add_argument("--no-email", action="store_true", help="Save new jobs but skip SMTP.")
    p_run.add_argument(
        "--regions",
        nargs="*",
        default=list(DEFAULT_REGIONS),
        help=f"Region filter (default: {' '.join(DEFAULT_REGIONS)}).",
    )
    p_run.add_argument("--all-regions", action="store_true", help="Skip region filter (verticals only).")
    p_run.add_argument("--db", type=str, default=None, help="SQLite path (default: ./data/jobintel.sqlite).")
    p_run.set_defaults(func=cmd_run)

    p_st = sub.add_parser("stats", help="Show how many roles are in the dedupe store.")
    p_st.add_argument("--db", type=str, default=None)
    p_st.set_defaults(func=cmd_stats)

    p_gui = sub.add_parser("gui", help="Launch the Streamlit web dashboard.")
    p_gui.set_defaults(func=cmd_gui)

    args = ap.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
