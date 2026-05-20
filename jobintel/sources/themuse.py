from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx

from jobintel.config import HTTP_TIMEOUT, USER_AGENT
from jobintel.http_utils import retry_get
from jobintel.models import Job

THEMUSE_URL = "https://www.themuse.com/api/public/jobs"
_MAX_PAGES = 5
_STRIP_TAGS = re.compile(r"<[^>]+>")

log = logging.getLogger(__name__)


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", _STRIP_TAGS.sub(" ", html)).strip()


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch_themuse(client: httpx.Client | None = None) -> list[Job]:
    """The Muse public API — free, no auth, US-focused tech/startup roles."""
    own = client is None
    if own:
        client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    all_jobs: list[Job] = []
    try:
        for page in range(_MAX_PAGES):
            r = retry_get(
                client,
                THEMUSE_URL,
                params={"page": page, "page_size": 100, "descending": "true"},
            )
            data: dict[str, Any] = r.json()
            results: list[dict] = data.get("results") or []
            if not results:
                break
            for row in results:
                title = (row.get("name") or "").strip()
                company_obj = row.get("company") or {}
                company = (
                    company_obj.get("name") if isinstance(company_obj, dict) else ""
                ) or ""
                url = (
                    (row.get("refs") or {}).get("landing_page") or ""
                ).strip()
                if not title or not url:
                    continue
                locs: list[str] = [
                    loc.get("name") or ""
                    for loc in (row.get("locations") or [])
                    if isinstance(loc, dict)
                ]
                loc_text = "; ".join(l for l in locs if l)
                contents = row.get("contents") or ""
                desc = _strip_html(contents)[:500]
                pub = _parse_date(row.get("publication_date"))
                cats: list[str] = [
                    c.get("name") or ""
                    for c in (row.get("categories") or [])
                    if isinstance(c, dict)
                ]
                all_jobs.append(
                    Job(
                        title=title,
                        company=company,
                        url=url,
                        source="themuse",
                        regions=[],
                        is_remote=False,
                        location_text=loc_text,
                        description_snippet=desc,
                        published_at=pub,
                        raw={"tags": cats},
                    )
                )
            log.debug("themuse page %d: %d jobs", page, len(results))
            if len(results) < 100:
                break
            if page < _MAX_PAGES - 1:
                time.sleep(0.3)
    finally:
        if own:
            client.close()
    return all_jobs
