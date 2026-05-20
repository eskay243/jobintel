from __future__ import annotations

import logging
import smtplib
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


def _job_card(job: Job) -> None:
    region_tags = " ".join(_REGION_EMOJI.get(r, r) for r in (job.regions or []))
    date_str = f" · {job.published_at.strftime('%b %d, %Y')}" if job.published_at else ""
    snippet = (job.description_snippet or "").strip()[:220]
    if snippet and not snippet.endswith((".", "!", "?")):
        snippet += "…"

    with st.container(border=True):
        col_title, col_btn = st.columns([5, 1])
        with col_title:
            st.markdown(f"**{job.title or 'Untitled'}**")
            st.caption(f"{job.company or '—'} · `{job.source}`{date_str}")
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


def main() -> None:
    st.set_page_config(page_title="JobIntel", layout="wide", page_icon="🔍")
    st.title("🔍 JobIntel")

    if "results" not in st.session_state:
        st.session_state.results = None
        st.session_state.stats: dict[str, int] = {}
        st.session_state.errors: list[str] = []

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Regions")
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

        st.divider()
        st.header("Sources")
        selected_sources: list[tuple[str, object]] = []
        for name, fetcher, available in _SOURCE_DEFS:
            label = name if available else f"{name} *(no API key)*"
            checked = st.checkbox(label, value=available, disabled=not available, key=f"src_{name}")
            if checked and available:
                selected_sources.append((name, fetcher))

        st.divider()
        st.header("Options")
        dry_run = st.toggle("Dry run (don't save to DB)", value=True)
        has_smtp = bool(config.SMTP_USER and config.SMTP_PASSWORD)
        send_email = st.toggle(
            "Send email digest",
            value=False,
            disabled=not has_smtp,
            help="Set SMTP_USER + SMTP_PASSWORD in .env to enable" if not has_smtp else None,
        )

        st.divider()
        db_path_str = st.text_input("Database path", value=str(_DEFAULT_DB))
        db_path = Path(db_path_str)

        run_btn = st.button("▶  Run Pipeline", type="primary", use_container_width=True)

    # ── Run ───────────────────────────────────────────────────────────────
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
        c2.metric("After filters", f"{s.get('filtered', 0):,}")
        c3.metric("New jobs", f"{s.get('new', 0):,}")
        st.divider()

    # ── Results ───────────────────────────────────────────────────────────
    if st.session_state.results is not None:
        jobs = st.session_state.results
        if not jobs:
            st.info("No new jobs — all matches are already in the dedup store.")
        else:
            st.subheader(f"{len(jobs):,} New Jobs")
            pairs = list(zip(jobs[::2], jobs[1::2]))
            for lj, rj in pairs:
                col_a, col_b = st.columns(2)
                with col_a:
                    _job_card(lj)
                with col_b:
                    _job_card(rj)
            if len(jobs) % 2:
                col_a, _ = st.columns(2)
                with col_a:
                    _job_card(jobs[-1])
    else:
        st.info(
            "Configure regions and sources in the sidebar, "
            "then click **▶ Run Pipeline** to start."
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
