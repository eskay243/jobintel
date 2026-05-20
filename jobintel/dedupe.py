from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKD", title or "")
    # Strip combining marks (accents) so they don't become spaces via the punct regex
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_company(company: str) -> str:
    c = unicodedata.normalize("NFKD", company or "")
    c = c.lower()
    # longest alternatives first to avoid partial matches (e.g. "incorporated" before "inc")
    c = re.sub(
        r"\b(incorporated|corporation|limited|gmbh|sarl|pty|ltd|llc|inc|corp|plc|ag|bv|nv|s\.a\.?|co)\b\.?",
        "",
        c,
    )
    c = re.sub(r"[^\w\s]", " ", c)
    c = re.sub(r"\s+", " ", c).strip()
    c = c.rstrip(".,").strip()
    return c


def url_hash(url: str) -> str:
    return hashlib.sha256((url or "").strip().encode()).hexdigest()[:32]
