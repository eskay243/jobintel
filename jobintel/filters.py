from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Iterable

from jobintel.models import Job

# ---------------------------------------------------------------------------
# Hardcoded defaults — used when filters.toml is absent or incomplete
# ---------------------------------------------------------------------------

_DEFAULT_VERTICALS: dict[str, str] = {
    "ai": (
        r"\bai\b|\bml\b|machine learning|deep learning|llm|genai|generative|"
        r"data scientist|nlp|computer vision|pytorch|tensorflow|mlp|neural"
    ),
    "saas": (
        r"saas\b|software as a service|subscription[- ]based|product[- ]led|plg\b|"
        r"cloud (saas|software)|recurring revenue"
    ),
    "fintech": (
        r"fintech|open banking|payment(s)? (api|platform|infra)|"
        r"\bneobank\b|lending (platform|as a service)|\bdefi\b|wealth ?tech|insurtech"
    ),
    "health_tech": (
        r"health ?tech|healthcare|medtech|digital health|clinical|ehr|emr|"
        r"fda|hipaa|patient|pharma|biotech|life sciences"
    ),
}

_DEFAULT_REGIONS: dict[str, str] = {
    "remote": r"\bremote\b|work from home|\bwfh\b|fully distributed|remote[- ]first",
    "uk": r"\buk\b|united kingdom|england|scotland|wales|northern ireland|london|manchester",
    "us": r"\busa?\b|united states|u\.s\.|america|new york|san francisco|sf bay|seattle|austin\b",
    "eu": (
        r"\beu\b|europe|berlin|amsterdam|paris|dublin|madrid|barcelona|"
        r"munich|frankfurt|stockholm|helsinki|lisbon|warsaw|prague|vienna|milano|rome"
    ),
    "canada": r"\bcanada\b|toronto|vancouver|montreal|calgary|ottawa|waterloo",
}

# ---------------------------------------------------------------------------
# TOML loader — reads filters.toml from the project root if present
# ---------------------------------------------------------------------------

_TOML_PATH = Path(__file__).resolve().parent.parent / "filters.toml"


def _load_toml() -> dict:
    if _TOML_PATH.exists():
        with open(_TOML_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


def _build_vertical_patterns(cfg: dict) -> list[tuple[str, re.Pattern[str]]]:
    toml_verticals = cfg.get("verticals") or {}
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for name, default_pat in _DEFAULT_VERTICALS.items():
        if name in toml_verticals and toml_verticals[name].get("patterns"):
            combined = "|".join(toml_verticals[name]["patterns"])
        else:
            combined = default_pat
        patterns.append((name, re.compile(combined, re.I)))
    # Custom verticals defined only in TOML (not in defaults)
    for name, section in toml_verticals.items():
        if name not in _DEFAULT_VERTICALS and section.get("patterns"):
            combined = "|".join(section["patterns"])
            patterns.append((name, re.compile(combined, re.I)))
    return patterns


def _build_region_patterns(cfg: dict) -> dict[str, re.Pattern[str]]:
    toml_regions = cfg.get("regions") or {}
    out: dict[str, re.Pattern[str]] = {}
    for name, default_pat in _DEFAULT_REGIONS.items():
        if name in toml_regions and toml_regions[name].get("patterns"):
            combined = "|".join(toml_regions[name]["patterns"])
        else:
            combined = default_pat
        out[name] = re.compile(combined, re.I)
    for name, section in toml_regions.items():
        if name not in _DEFAULT_REGIONS and section.get("patterns"):
            combined = "|".join(section["patterns"])
            out[name] = re.compile(combined, re.I)
    return out


_cfg = _load_toml()
VERTICAL_PATTERNS: list[tuple[str, re.Pattern[str]]] = _build_vertical_patterns(_cfg)
_REGION_PATTERNS: dict[str, re.Pattern[str]] = _build_region_patterns(_cfg)


# ---------------------------------------------------------------------------
# Core filter logic
# ---------------------------------------------------------------------------


def _job_text(job: Job) -> str:
    parts = [job.title, job.company, job.location_text, job.description_snippet]
    tags = job.raw.get("tags")
    if isinstance(tags, list):
        parts.extend(str(t) for t in tags)
    elif isinstance(tags, str):
        parts.append(tags)
    return " \n ".join(p for p in parts if p)


def matches_vertical(job: Job) -> bool:
    text = _job_text(job)
    return any(p.search(text) for _, p in VERTICAL_PATTERNS)


def infer_regions(job: Job) -> list[str]:
    regions: list[str] = []
    text = _job_text(job)
    if job.is_remote:
        regions.append("remote")
    for name, pattern in _REGION_PATTERNS.items():
        if name == "remote":
            if not job.is_remote and pattern.search(text):
                regions.append("remote")
        elif pattern.search(text):
            regions.append(name)
    # Dedupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for r in regions:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def passes_region_filter(job: Job, want: Iterable[str] | None) -> bool:
    """If want is None/empty accept all. Else job must match at least one."""
    if not want:
        return True
    job_regions = set(job.regions) if job.regions else set(infer_regions(job))
    want_set = {w.lower().strip() for w in want}
    return bool(job_regions & want_set)


def filter_jobs(
    jobs: list[Job],
    *,
    regions: Iterable[str] | None = None,
) -> list[Job]:
    out: list[Job] = []
    for j in jobs:
        merged: list[str] = []
        for x in (j.regions or []) + infer_regions(j):
            if x not in merged:
                merged.append(x)
        j.regions = merged
        if not matches_vertical(j):
            continue
        if not passes_region_filter(j, regions):
            continue
        out.append(j)
    return out
