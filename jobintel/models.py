from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Job:
    """Normalized job listing across sources."""

    title: str
    company: str
    url: str
    source: str
    regions: list[str] = field(default_factory=list)
    is_remote: bool = False
    location_text: str = ""
    description_snippet: str = ""
    published_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Stable id for dedupe (same role reposted across boards)."""
        from jobintel.dedupe import normalize_company, normalize_title, url_hash

        t = normalize_title(self.title)
        c = normalize_company(self.company)
        key = f"{t}|{c}"
        if key.strip("|").strip():
            return key
        return url_hash(self.url)
