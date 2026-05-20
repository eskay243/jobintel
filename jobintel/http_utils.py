from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)


def retry_get(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    max_attempts: int = 3,
    backoff_base: float = 1.5,
) -> httpx.Response:
    """GET with exponential backoff on transient errors and rate limits."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            resp = client.get(url, params=params)
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", backoff_base ** attempt))
                log.warning("Rate limited by %s — waiting %.1fs (attempt %d)", url, wait, attempt + 1)
                time.sleep(wait)
                last_exc = httpx.HTTPStatusError(
                    f"429 Too Many Requests", request=resp.request, response=resp
                )
                continue
            if resp.status_code >= 500:
                wait = backoff_base ** attempt
                log.warning(
                    "Server error %d from %s — retrying in %.1fs (attempt %d)",
                    resp.status_code, url, wait, attempt + 1,
                )
                time.sleep(wait)
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code} Server Error", request=resp.request, response=resp
                )
                continue
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            wait = backoff_base ** attempt
            log.warning(
                "Transport error fetching %s — retrying in %.1fs (attempt %d): %s",
                url, wait, attempt + 1, exc,
            )
            time.sleep(wait)
            last_exc = exc
    raise last_exc or RuntimeError(f"Failed to GET {url} after {max_attempts} attempts")
