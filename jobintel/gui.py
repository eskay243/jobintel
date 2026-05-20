from __future__ import annotations

import logging
import re
import smtplib
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import streamlit as st

from jobintel import config
from jobintel.emailer import send_digest
from jobintel.filters import filter_jobs
from jobintel.models import Job
from jobintel.sources.adzuna import fetch_adzuna_all
from jobintel.sources.arbeitnow import fetch_arbeitnow
from jobintel.sources.jobicy import fetch_jobicy
from jobintel.sources.remoteok import fetch_remoteok
from jobintel.sources.remotive import fetch_remotive
from jobintel.sources.themuse import fetch_themuse
from jobintel.storage import JobStore

log = logging.getLogger("jobintel.gui")

# ── Constants ─────────────────────────────────────────────────────────────────

_REGION_EMOJI: dict[str, str] = {
    "remote": "🌍",
    "uk": "🇬🇧",
    "us": "🇺🇸",
    "eu": "🇪🇺",
    "canada": "🇨🇦",
}

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "jobintel.sqlite"

_SOURCE_DEFS: list[tuple[str, object, bool]] = [
    ("Remotive", fetch_remotive, True),
    ("ArbeitNow", fetch_arbeitnow, True),
    ("Adzuna", fetch_adzuna_all, config.ADZUNA_ENABLED),
    ("The Muse", fetch_themuse, config.THEMUSE_ENABLED),
    ("Remote OK", fetch_remoteok, config.REMOTEOK_ENABLED),
    ("Jobicy", fetch_jobicy, True),
]

# Job-type detection — searched over title + description
_JOB_TYPE_RE: dict[str, re.Pattern[str]] = {
    "Full-time":  re.compile(r"\bfull[- ]?time\b", re.I),
    "Part-time":  re.compile(r"\bpart[- ]?time\b", re.I),
    "Contract":   re.compile(r"\b(contract(or)?|c2c|corp[- ]to[- ]corp|fixed[- ]term)\b", re.I),
    "Internship": re.compile(r"\bintern(ship)?\b", re.I),
    "Freelance":  re.compile(r"\bfreelance(r)?\b", re.I),
}

# Experience-level detection — searched over title
_SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead\b|director|vp\b|head of|architect|"
    r"distinguished|fellow|manager|cto|cpo|cio)\b",
    re.I,
)
_JUNIOR_RE = re.compile(
    r"\b(junior|jr\.?|entry[- ]level|entry[- ]level|associate\b|graduate|"
    r"intern(ship)?|trainee|new grad|0[- ]?[12][- ]year)\b",
    re.I,
)

_DATE_WINDOWS: dict[str, timedelta | None] = {
    "Any time":      None,
    "Last 24 hours": timedelta(hours=24),
    "Last 3 days":   timedelta(days=3),
    "Last 7 days":   timedelta(days=7),
    "Last 30 days":  timedelta(days=30),
}

_SORT_OPTIONS = ["Newest first", "Oldest first", "Company A–Z", "Title A–Z"]


# ── Detection helpers ─────────────────────────────────────────────────────────

def _detect_types(job: Job) -> list[str]:
    text = f"{job.title} {job.description_snippet}"
    return [t for t, pat in _JOB_TYPE_RE.items() if pat.search(text)]


def _detect_level(job: Job) -> str:
    text = f"{job.title} {job.description_snippet}"
    if _SENIOR_RE.search(job.title or ""):
        return "Senior"
    if _JUNIOR_RE.search(text):
        return "Junior"
    return "Mid-level"


def _naive(dt: datetime | None) -> datetime:
    """Strip tzinfo so naive and aware datetimes can be compared."""
    if dt is None:
        return datetime.min
    return dt.replace(tzinfo=None)


# ── Display-filter logic ──────────────────────────────────────────────────────

def _apply_display_filters(
    jobs: list[Job],
    keyword: str,
    date_window: timedelta | None,
    job_types: list[str],
    exp_levels: list[str],
    sort_by: str,
) -> list[Job]:
    result = list(jobs)

    # Keyword — title, company, description, location
    if keyword.strip():
        kw = keyword.strip().lower()
        result = [
            j for j in result
            if kw in (j.title or "").lower()
            or kw in (j.company or "").lower()
            or kw in (j.description_snippet or "").lower()
            or kw in (j.location_text or "").lower()
        ]

    # Date posted — jobs with unknown date are excluded when a window is active
    if date_window:
        cutoff = datetime.now() - date_window
        result = [
            j for j in result
            if j.published_at is not None and _naive(j.published_at) >= cutoff
        ]

    # Job type — undetected type is treated as Full-time
    if job_types:
        def _type_match(j: Job) -> bool:
            detected = _detect_types(j)
            if not detected:
                return "Full-time" in job_types
            return any(t in detected for t in job_types)
        result = [j for j in result if _type_match(j)]

    # Experience level
    if exp_levels:
        result = [j for j in result if _detect_level(j) in exp_levels]

    # Sort
    if sort_by == "Newest first":
        result.sort(key=lambda j: _naive(j.published_at), reverse=True)
    elif sort_by == "Oldest first":
        result.sort(key=lambda j: (j.published_at is None, _naive(j.published_at)))
    elif sort_by == "Company A–Z":
        result.sort(key=lambda j: (j.company or "").lower())
    elif sort_by == "Title A–Z":
        result.sort(key=lambda j: (j.title or "").lower())

    return result


# ── Pipeline runner ───────────────────────────────────────────────────────────

def _run_pipeline(
    selected_sources: list[tuple[str, object]],
    selected_regions: list[str],
    dry_run: bool,
    send_email: bool,
    db_path: Path,
) -> tuple[list[Job], dict[str, int], list[str]]:
    all_jobs: list[Job] = []
    errors: list[str] = []

    status = st.status("Fetching jobs…", expanded=True)
    with httpx.Client(
        timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT},
        follow_redirects=True,
    ) as client:
        for name, fetcher in selected_sources:
            status.write(f"Fetching {name}…")
            try:
                jobs = fetcher(client)  # type: ignore[operator]
                all_jobs.extend(jobs)
                status.write(f"  ✓ {name}: {len(jobs)} jobs")
            except (httpx.HTTPError, httpx.TransportError, OSError, ValueError) as e:
                errors.append(f"{name} failed: {e}")
                status.write(f"  ✗ {name}: {e}")

    status.write(f"Filtering {len(all_jobs)} raw jobs…")
    regions_arg = tuple(selected_regions) if selected_regions else None
    filtered = filter_jobs(all_jobs, regions=regions_arg)

    status.write(f"Deduplicating {len(filtered)} filtered jobs…")
    with JobStore(db_path) as store:
        new_jobs = store.filter_new(filtered)
        if not dry_run:
            store.insert_many(new_jobs)

    if send_email and not dry_run and new_jobs:
        status.write("Sending email digest…")
        try:
            send_digest(new_jobs)
            status.write("  ✓ Email sent")
        except (smtplib.SMTPException, OSError, RuntimeError) as e:
            errors.append(f"Email failed: {e}")
            status.write(f"  ✗ Email failed: {e}")

    status.update(label=f"Done — {len(new_jobs)} new jobs found", state="complete")
    stats: dict[str, int] = {
        "raw": len(all_jobs),
        "filtered": len(filtered),
        "new": len(new_jobs),
    }
    return new_jobs, stats, errors


# ── Job card ──────────────────────────────────────────────────────────────────

def _job_card(job: Job) -> None:
    region_tags = " ".join(_REGION_EMOJI.get(r, r) for r in (job.regions or []))
    date_str = f" · {job.published_at.strftime('%b %d, %Y')}" if job.published_at else ""
    snippet = (job.description_snippet or "").strip()[:220]
    if snippet and not snippet.endswith((".", "!", "?")):
        snippet += "…"

    # Detected badges
    level = _detect_level(job)
    types = _detect_types(job)
    type_str = " · ".join(types) if types else "Full-time"
    level_badge = {"Senior": "🔵", "Mid-level": "🟢", "Junior": "🟡"}.get(level, "")

    with st.container(border=True):
        col_title, col_btn = st.columns([5, 1])
        with col_title:
            st.markdown(f"**{job.title or 'Untitled'}**")
            st.caption(
                f"{job.company or '—'} · `{job.source}`{date_str} · "
                f"{level_badge} {level} · {type_str}"
            )
        with col_btn:
            st.link_button("Open →", job.url, use_container_width=True)
        meta_parts = []
        if region_tags:
            meta_parts.append(region_tags)
        if job.location_text:
            meta_parts.append(job.location_text)
        if meta_parts:
            st.markdown("  ·  ".join(meta_parts))
        if snippet:
            st.markdown(f"*{snippet}*")


# ── Main app ──────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(page_title="JobIntel", layout="wide", page_icon="🔍")
    st.title("🔍 JobIntel")

    if "results" not in st.session_state:
        st.session_state.results = None
        st.session_state.stats: dict[str, int] = {}
        st.session_state.errors: list[str] = []

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:

        # Pipeline filters
        st.header("Pipeline Filters")

        st.subheader("Regions")
        all_regions = ["remote", "uk", "us", "eu", "canada"]
        selected_regions = [
            r
            for r in all_regions
            if st.checkbox(
                f"{_REGION_EMOJI.get(r, '')} {r}",
                value=r in ("remote", "uk", "us"),
                key=f"region_{r}",
            )
        ]

        st.subheader("Sources")
        selected_sources: list[tuple[str, object]] = []
        for name, fetcher, available in _SOURCE_DEFS:
            label = name if available else f"{name} *(no key)*"
            checked = st.checkbox(label, value=available, disabled=not available, key=f"src_{name}")
            if checked and available:
                selected_sources.append((name, fetcher))

        st.subheader("Options")
        dry_run = st.toggle("Dry run (don't save to DB)", value=True)
        has_smtp = bool(config.SMTP_USER and config.SMTP_PASSWORD)
        send_email = st.toggle(
            "Send email digest",
            value=False,
            disabled=not has_smtp,
            help="Set SMTP_USER + SMTP_PASSWORD in .env to enable" if not has_smtp else None,
        )
        db_path_str = st.text_input("Database path", value=str(_DEFAULT_DB))
        db_path = Path(db_path_str)

        run_btn = st.button("▶  Run Pipeline", type="primary", use_container_width=True)

        st.divider()

        # Results filters (always visible; only meaningful after a run)
        with st.expander("🔎 Results Filters", expanded=bool(st.session_state.results)):
            keyword = st.text_input(
                "Keyword",
                placeholder="e.g. Python, startup, London…",
                key="kw",
            )
            date_label = st.selectbox(
                "Date posted",
                options=list(_DATE_WINDOWS.keys()),
                key="date_window",
            )
            job_types = st.multiselect(
                "Job type",
                options=list(_JOB_TYPE_RE.keys()),
                default=[],
                key="job_types",
                help="Unspecified postings are treated as Full-time.",
            )
            exp_levels = st.multiselect(
                "Experience level",
                options=["Senior", "Mid-level", "Junior"],
                default=[],
                key="exp_levels",
                help="Detected from job title keywords.",
            )
            sort_by = st.selectbox(
                "Sort by",
                options=_SORT_OPTIONS,
                key="sort_by",
            )
            if st.session_state.results is not None:
                if st.button("Clear filters", use_container_width=True):
                    for k in ("kw", "date_window", "job_types", "exp_levels", "sort_by"):
                        if k in st.session_state:
                            del st.session_state[k]
                    st.rerun()

    # ── Run pipeline ──────────────────────────────────────────────────────
    if run_btn:
        if not selected_sources:
            st.error("Select at least one source in the sidebar.")
        else:
            new_jobs, stats, errors = _run_pipeline(
                selected_sources, selected_regions, dry_run, send_email, db_path
            )
            st.session_state.results = new_jobs
            st.session_state.stats = stats
            st.session_state.errors = errors

    # ── Error banners ─────────────────────────────────────────────────────
    for err in st.session_state.errors:
        st.warning(err)

    # ── Metrics row ───────────────────────────────────────────────────────
    if st.session_state.stats:
        s = st.session_state.stats
        c1, c2, c3 = st.columns(3)
        c1.metric("Raw fetched", f"{s.get('raw', 0):,}")
        c2.metric("After pipeline filters", f"{s.get('filtered', 0):,}")
        c3.metric("New (not seen before)", f"{s.get('new', 0):,}")
        st.divider()

    # ── Results ───────────────────────────────────────────────────────────
    if st.session_state.results is not None:
        all_new = st.session_state.results

        # Apply display filters
        display_jobs = _apply_display_filters(
            all_new,
            keyword=st.session_state.get("kw", ""),
            date_window=_DATE_WINDOWS[st.session_state.get("date_window", "Any time")],
            job_types=st.session_state.get("job_types", []),
            exp_levels=st.session_state.get("exp_levels", []),
            sort_by=st.session_state.get("sort_by", "Newest first"),
        )

        if not all_new:
            st.info("No new jobs — all matches are already in the dedup store.")
        elif not display_jobs:
            st.warning(
                f"No jobs match the current filters "
                f"({len(all_new):,} new jobs exist — try relaxing the filters)."
            )
        else:
            count_label = (
                f"{len(display_jobs):,} of {len(all_new):,} new jobs"
                if len(display_jobs) != len(all_new)
                else f"{len(display_jobs):,} new jobs"
            )
            st.subheader(count_label)

            pairs = list(zip(display_jobs[::2], display_jobs[1::2]))
            for lj, rj in pairs:
                col_a, col_b = st.columns(2)
                with col_a:
                    _job_card(lj)
                with col_b:
                    _job_card(rj)
            if len(display_jobs) % 2:
                col_a, _ = st.columns(2)
                with col_a:
                    _job_card(display_jobs[-1])
    else:
        st.info(
            "Configure pipeline filters in the sidebar, "
            "then click **▶ Run Pipeline** to fetch jobs. "
            "Use **Results Filters** to narrow down what's displayed."
        )

    # ── Footer ────────────────────────────────────────────────────────────
    st.divider()
    try:
        with JobStore(db_path) as store:
            total = store.count()
        mode = "dry-run" if dry_run else "live"
        st.caption(f"`{db_path}` · **{total:,}** total tracked roles · mode: {mode}")
    except Exception:
        st.caption(f"`{db_path}` · database not yet initialised")


main()
