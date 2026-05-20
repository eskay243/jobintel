from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from jobintel.config import HTTP_TIMEOUT, USER_AGENT
from jobintel.http_utils import retry_get
from jobintel.models import Job

REMOTEOK_URL = "https://remoteok.com/api"

log = logging.getLogger(__name__)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromtimestamp(int(s), tz=timezone.utc)
        except (ValueError, OSError):
            return None


def fetch_remoteok(client: httpx.Client | None = None) -> list[Job]:
    """Remote OK API — free, no auth, ~100 most recent remote-only roles."""
    own = client is None
    if own:
        client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        r = retry_get(client, REMOTEOK_URL)
        data: list[Any] = r.json()
    finally:
        if own:
            client.close()

    jobs: list[Job] = []
    # First element is a metadata dict — skip it
    for row in data[1:] if isinstance(data, list) else []:
        if not isinstance(row, dict):
            continue
        title = (row.get("position") or "").strip()
        company = (row.get("company") or "").strip()
        url = (row.get("url") or "").strip()
        if not title or not url:
            continue
        tags = row.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        desc = (row.get("description") or "")[:500]
        pub = _parse_date(row.get("date"))
        jobs.append(
            Job(
                title=title,
                company=company,
                url=url,
                source="remoteok",
                regions=["remote"],
                is_remote=True,
                location_text="",
                description_snippet=desc,
                published_at=pub,
                raw={"tags": list(tags)},
            )
        )
    log.debug("remoteok: %d jobs", len(jobs))
    return jobs
