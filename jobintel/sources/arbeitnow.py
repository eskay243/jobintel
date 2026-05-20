from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from jobintel.config import HTTP_TIMEOUT, USER_AGENT
from jobintel.http_utils import retry_get
from jobintel.models import Job

ARBEITNOW_URL = "https://arbeitnow.com/api/job-board-api"
_MAX_PAGES = 5

log = logging.getLogger(__name__)


def _parse_created(raw: object) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc)
        except (OSError, ValueError, OverflowError):
            return None
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _parse_page(payload: dict[str, Any]) -> tuple[list[Job], int]:
    """Return (jobs_on_page, last_page_number)."""
    meta = payload.get("meta") or {}
    last_page: int = int(meta.get("last_page") or 1)

    jobs: list[Job] = []
    for row in payload.get("data") or []:
        slug = (row.get("slug") or "").strip()
        url = f"https://arbeitnow.com/view/{slug}" if slug else ""
        title = (row.get("title") or "").strip()
        company = (row.get("company_name") or "").strip()
        if not title:
            continue
        if not url:
            # Skip jobs with no slug — the generic search URL is useless as a link
            continue
        remote = bool(row.get("remote"))
        loc_bits = [row.get("city"), row.get("state"), row.get("country")]
        loc = ", ".join(str(x) for x in loc_bits if x)
        desc = (row.get("description") or "")[:500]
        created = _parse_created(row.get("created_at"))
        tags = row.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]

        # regions=[] lets filter_jobs.infer_regions derive from location_text.
        # Only pre-set "remote" when the API explicitly flags the job as remote.
        regions: list[str] = ["remote"] if remote else []

        jobs.append(
            Job(
                title=title,
                company=company,
                url=url,
                source="arbeitnow",
                regions=regions,
                is_remote=remote,
                location_text=loc,
                description_snippet=desc,
                published_at=created,
                raw={"tags": list(tags)},
            )
        )
    return jobs, last_page


def fetch_arbeitnow(client: httpx.Client | None = None) -> list[Job]:
    own = client is None
    if own:
        client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    all_jobs: list[Job] = []
    try:
        page = 1
        last_page = 1
        while page <= min(last_page, _MAX_PAGES):
            r = retry_get(client, ARBEITNOW_URL, params={"page": page})
            payload: dict[str, Any] = r.json()
            jobs, last_page = _parse_page(payload)
            all_jobs.extend(jobs)
            log.debug("arbeitnow page %d/%d: %d jobs", page, last_page, len(jobs))
            page += 1
            if page <= min(last_page, _MAX_PAGES):
                time.sleep(0.5)
    finally:
        if own:
            client.close()
    return all_jobs
