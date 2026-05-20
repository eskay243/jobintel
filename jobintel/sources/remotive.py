from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from jobintel.config import HTTP_TIMEOUT, USER_AGENT
from jobintel.http_utils import retry_get
from jobintel.models import Job

REMOTIVE_URL = "https://remotive.com/api/remote-jobs"

# Locations that mean the role is globally remote (not region-specific)
_TRULY_REMOTE = re.compile(r"^(worldwide|anywhere|global|remote|)$", re.I)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def fetch_remotive(client: httpx.Client | None = None) -> list[Job]:
    """Remote-first board; infers region from candidate_required_location. ~few req/day."""
    own = client is None
    if own:
        client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        r = retry_get(client, REMOTIVE_URL, params={"limit": 200})
        data: dict[str, Any] = r.json()
    finally:
        if own:
            client.close()

    jobs: list[Job] = []
    for row in data.get("jobs") or []:
        url = (row.get("url") or "").strip()
        title = (row.get("title") or "").strip()
        company = (row.get("company_name") or "").strip()
        if not url or not title:
            continue
        loc = (row.get("candidate_required_location") or "").strip()
        desc = (row.get("description") or "")[:500]
        pub = _parse_date(row.get("publication_date"))
        tags = row.get("tags") or []

        # Only mark as globally remote if location is empty / generic.
        # Region-specific locations (e.g. "USA Only") are left for infer_regions.
        is_remote = bool(_TRULY_REMOTE.match(loc))
        regions: list[str] = ["remote"] if is_remote else []

        jobs.append(
            Job(
                title=title,
                company=company,
                url=url,
                source="remotive",
                regions=regions,
                is_remote=is_remote,
                location_text=loc,
                description_snippet=desc,
                published_at=pub,
                raw={"tags": tags, "category": row.get("category")},
            )
        )
    return jobs
