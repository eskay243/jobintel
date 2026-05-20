from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from jobintel import config
from jobintel.config import HTTP_TIMEOUT, USER_AGENT
from jobintel.http_utils import retry_get
from jobintel.models import Job

JOBICY_URL = "https://jobicy.com/api/v2/remote-jobs"

# Map common jobGeo phrases to region tags so infer_regions gets a head start
_GEO_REGION: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\busa?\b|united states|north america", re.I), "us"),
    (re.compile(r"\buk\b|united kingdom|britain", re.I), "uk"),
    (re.compile(r"\beurope\b|eu\b", re.I), "eu"),
    (re.compile(r"\bcanada\b", re.I), "canada"),
]

log = logging.getLogger(__name__)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _geo_to_regions(geo: str) -> list[str]:
    regions: list[str] = []
    for pattern, label in _GEO_REGION:
        if pattern.search(geo):
            regions.append(label)
    return regions


def fetch_jobicy(client: httpx.Client | None = None) -> list[Job]:
    """Jobicy API — free, no auth, remote-only roles. count capped at 50."""
    own = client is None
    if own:
        client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        r = retry_get(client, JOBICY_URL, params={"count": config.JOBICY_COUNT})
        data: dict[str, Any] = r.json()
    finally:
        if own:
            client.close()

    jobs: list[Job] = []
    for row in data.get("jobs") or []:
        title = (row.get("jobTitle") or "").strip()
        company = (row.get("companyName") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url:
            continue
        geo = (row.get("jobGeo") or "").strip()
        loc_text = geo
        industries = row.get("jobIndustry") or []
        if isinstance(industries, str):
            industries = [industries]
        desc = (row.get("jobExcerpt") or "")[:500]
        pub = _parse_date(row.get("pubDate"))

        regions = _geo_to_regions(geo)
        if not regions or re.search(r"worldwide|anywhere|global", geo, re.I):
            regions = ["remote"]

        jobs.append(
            Job(
                title=title,
                company=company,
                url=url,
                source="jobicy",
                regions=regions,
                is_remote=True,
                location_text=loc_text,
                description_snippet=desc,
                published_at=pub,
                raw={"tags": list(industries)},
            )
        )
    log.debug("jobicy: %d jobs", len(jobs))
    return jobs
