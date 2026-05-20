from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx

from jobintel import config
from jobintel.config import HTTP_TIMEOUT, USER_AGENT
from jobintel.http_utils import retry_get
from jobintel.models import Job

# Adzuna country codes: https://developer.adzuna.com/docs/search
_ADZUNA_COUNTRIES: list[tuple[str, str]] = [
    ("gb", "uk"),
    ("us", "us"),
    ("ca", "canada"),
]

_MAX_PAGES = 3

# Require explicit remote phrasing — avoids matching "remote control", "remote access", etc.
_REMOTE_RE = re.compile(
    r"\b(fully remote|remote[- ]first|remote only|100%\s*remote|work from home|wfh|distributed team)\b",
    re.I,
)

log = logging.getLogger(__name__)


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch_country(
    client: httpx.Client,
    country_code: str,
    region_label: str,
    what: str,
    page: int = 1,
) -> list[Job]:
    base = f"https://api.adzuna.com/v1/api/jobs/{country_code}/search/{page}"
    params = {
        "app_id": config.ADZUNA_APP_ID,
        "app_key": config.ADZUNA_APP_KEY,
        "results_per_page": 50,
        "what": what,
        "content-type": "application/json",
    }
    r = retry_get(client, base, params=params)
    data: dict[str, Any] = r.json()
    jobs: list[Job] = []
    for row in data.get("results") or []:
        url = (row.get("redirect_url") or row.get("url") or "").strip()
        title = (row.get("title") or "").strip()
        company = (
            row.get("company", {}).get("display_name")
            if isinstance(row.get("company"), dict)
            else ""
        ) or ""
        company = str(company).strip()
        if not title or not url:
            continue
        loc = row.get("location", {}) or {}
        if isinstance(loc, dict):
            loc_text = ", ".join(
                str(x)
                for x in (loc.get("display_name"), loc.get("area"), loc.get("city"))
                if x
            )
        else:
            loc_text = str(loc)
        desc = (row.get("description") or "")[:500]
        created = _parse_date(row.get("created"))
        combined = f"{title} {desc} {loc_text}"
        is_remote = bool(_REMOTE_RE.search(combined))
        jobs.append(
            Job(
                title=title,
                company=company,
                url=url,
                source=f"adzuna_{region_label}",
                regions=[region_label],
                is_remote=is_remote,
                location_text=loc_text,
                description_snippet=desc,
                published_at=created,
                raw={
                    "adzuna": row.get("category", {}).get("label")
                    if isinstance(row.get("category"), dict)
                    else None
                },
            )
        )
    return jobs


def fetch_adzuna_all(client: httpx.Client | None = None) -> list[Job]:
    """UK, US, Canada via Adzuna. Requires ADZUNA_APP_ID and ADZUNA_APP_KEY."""
    if not config.ADZUNA_ENABLED:
        return []
    query = "software OR engineer OR product OR data OR designer OR AI OR fintech OR health"
    own = client is None
    if own:
        client = httpx.Client(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    all_jobs: list[Job] = []
    try:
        for cc, label in _ADZUNA_COUNTRIES:
            for page in range(1, _MAX_PAGES + 1):
                try:
                    jobs = _fetch_country(client, cc, label, query, page=page)
                    all_jobs.extend(jobs)
                    log.debug("adzuna_%s page %d: %d jobs", label, page, len(jobs))
                    if len(jobs) < 50:
                        break  # last page has fewer results
                    if page < _MAX_PAGES:
                        time.sleep(0.25)
                except (httpx.HTTPError, httpx.TransportError) as exc:
                    log.warning("adzuna_%s page %d failed: %s", label, page, exc)
                    break
    finally:
        if own:
            client.close()
    return all_jobs
