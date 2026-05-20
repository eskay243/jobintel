from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from jobintel.sources.adzuna import _REMOTE_RE
from jobintel.sources.arbeitnow import fetch_arbeitnow
from jobintel.sources.jobicy import fetch_jobicy
from jobintel.sources.remoteok import fetch_remoteok
from jobintel.sources.remotive import fetch_remotive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.headers = {}
    resp.raise_for_status = MagicMock()
    return resp


def _patched_client(data):
    """Return a context-manager-compatible mock client that returns data on GET."""
    client = MagicMock(spec=httpx.Client)
    client.get.return_value = _make_response(data)
    return client


# ---------------------------------------------------------------------------
# Remotive
# ---------------------------------------------------------------------------

class TestFetchRemotive:
    _SAMPLE = {
        "jobs": [
            {
                "title": "ML Engineer",
                "company_name": "Acme",
                "url": "https://remotive.com/job/1",
                "candidate_required_location": "Worldwide",
                "description": "Build ML models",
                "tags": ["python", "ml"],
                "category": "software",
                "publication_date": "2024-01-15T10:00:00",
            },
            {
                "title": "Backend Engineer",
                "company_name": "Euro Corp",
                "url": "https://remotive.com/job/2",
                "candidate_required_location": "Europe",
                "description": "Build APIs",
                "tags": [],
                "category": "software",
                "publication_date": "2024-01-14",
            },
        ]
    }

    def test_parses_jobs(self):
        with patch("jobintel.sources.remotive.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_remotive(client)
        assert len(jobs) == 2

    def test_worldwide_is_remote(self):
        with patch("jobintel.sources.remotive.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_remotive(client)
        worldwide_job = next(j for j in jobs if "Worldwide" in j.location_text)
        assert worldwide_job.is_remote is True
        assert "remote" in worldwide_job.regions

    def test_region_specific_location_not_hardcoded_remote(self):
        with patch("jobintel.sources.remotive.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_remotive(client)
        europe_job = next(j for j in jobs if j.location_text == "Europe")
        assert europe_job.is_remote is False
        assert "remote" not in europe_job.regions

    def test_skips_jobs_without_url_or_title(self):
        data = {"jobs": [{"title": "", "company_name": "X", "url": "https://x.com/job/1"}]}
        with patch("jobintel.sources.remotive.retry_get", return_value=_make_response(data)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_remotive(client)
        assert jobs == []


# ---------------------------------------------------------------------------
# ArbeitNow
# ---------------------------------------------------------------------------

class TestFetchArbeitnow:
    _SAMPLE = {
        "data": [
            {
                "slug": "ml-eng-at-acme",
                "title": "ML Engineer",
                "company_name": "Acme GmbH",
                "remote": True,
                "city": "Berlin",
                "country": "Germany",
                "description": "ML role",
                "tags": ["python"],
                "created_at": "2024-01-15T10:00:00Z",
            },
            {
                "slug": "pm-at-corp",
                "title": "Product Manager",
                "company_name": "Corp",
                "remote": False,
                "city": "Amsterdam",
                "country": "Netherlands",
                "description": "PM role",
                "tags": [],
                "created_at": 1705312800,
            },
        ],
        "meta": {"current_page": 1, "last_page": 1},
    }

    def test_parses_jobs(self):
        with patch("jobintel.sources.arbeitnow.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_arbeitnow(client)
        assert len(jobs) == 2

    def test_remote_flag_sets_region(self):
        with patch("jobintel.sources.arbeitnow.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_arbeitnow(client)
        remote_job = next(j for j in jobs if j.title == "ML Engineer")
        assert remote_job.is_remote is True
        assert "remote" in remote_job.regions

    def test_no_hardcoded_eu_region(self):
        with patch("jobintel.sources.arbeitnow.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_arbeitnow(client)
        non_remote_job = next(j for j in jobs if j.title == "Product Manager")
        # Should NOT have hardcoded "eu" — regions should be [] (infer_regions will derive it)
        assert non_remote_job.regions == []

    def test_url_constructed_from_slug(self):
        with patch("jobintel.sources.arbeitnow.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_arbeitnow(client)
        assert jobs[0].url == "https://arbeitnow.com/view/ml-eng-at-acme"


# ---------------------------------------------------------------------------
# Adzuna remote detection
# ---------------------------------------------------------------------------

class TestAdzunaRemoteDetection:
    def test_fully_remote_matches(self):
        assert _REMOTE_RE.search("Fully remote position")

    def test_remote_first_matches(self):
        assert _REMOTE_RE.search("We are a remote-first company")

    def test_wfh_matches(self):
        assert _REMOTE_RE.search("WFH available")

    def test_work_from_home_matches(self):
        assert _REMOTE_RE.search("Work from home opportunity")

    def test_remote_control_does_not_match(self):
        assert not _REMOTE_RE.search("Remote control specialist")

    def test_remote_access_does_not_match(self):
        assert not _REMOTE_RE.search("Remote access to servers required")

    def test_remote_desktop_does_not_match(self):
        assert not _REMOTE_RE.search("Remote desktop support engineer")

    def test_remove_bugs_does_not_match(self):
        assert not _REMOTE_RE.search("Help us remove bugs from the codebase")


# ---------------------------------------------------------------------------
# Remote OK
# ---------------------------------------------------------------------------

class TestFetchRemoteOK:
    _SAMPLE = [
        {"legal": True},  # metadata element — should be skipped
        {
            "position": "Senior ML Engineer",
            "company": "RemoteCo",
            "url": "https://remoteok.com/job/1",
            "tags": ["ml", "python"],
            "description": "Build ML stuff",
            "date": "2024-01-15T10:00:00Z",
        },
    ]

    def test_skips_metadata_element(self):
        with patch("jobintel.sources.remoteok.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_remoteok(client)
        assert len(jobs) == 1

    def test_all_jobs_marked_remote(self):
        with patch("jobintel.sources.remoteok.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_remoteok(client)
        assert jobs[0].is_remote is True
        assert "remote" in jobs[0].regions

    def test_source_is_remoteok(self):
        with patch("jobintel.sources.remoteok.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_remoteok(client)
        assert jobs[0].source == "remoteok"


# ---------------------------------------------------------------------------
# Jobicy
# ---------------------------------------------------------------------------

class TestFetchJobicy:
    _SAMPLE = {
        "jobs": [
            {
                "jobTitle": "Data Engineer",
                "companyName": "DataCo",
                "url": "https://jobicy.com/job/1",
                "jobGeo": "Worldwide",
                "jobIndustry": ["Engineering"],
                "pubDate": "2024-01-15 10:00:00",
                "jobExcerpt": "Build data pipelines",
            },
            {
                "jobTitle": "Frontend Dev",
                "companyName": "UICo",
                "url": "https://jobicy.com/job/2",
                "jobGeo": "USA Only",
                "jobIndustry": ["Engineering"],
                "pubDate": "2024-01-14 09:00:00",
                "jobExcerpt": "Build UIs",
            },
        ]
    }

    def test_parses_jobs(self):
        with patch("jobintel.sources.jobicy.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_jobicy(client)
        assert len(jobs) == 2

    def test_worldwide_maps_to_remote(self):
        with patch("jobintel.sources.jobicy.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_jobicy(client)
        ww = next(j for j in jobs if "Worldwide" in j.location_text)
        assert "remote" in ww.regions

    def test_usa_only_maps_to_us(self):
        with patch("jobintel.sources.jobicy.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_jobicy(client)
        us_job = next(j for j in jobs if "USA" in j.location_text)
        assert "us" in us_job.regions

    def test_all_jobs_marked_remote(self):
        with patch("jobintel.sources.jobicy.retry_get", return_value=_make_response(self._SAMPLE)):
            client = MagicMock(spec=httpx.Client)
            jobs = fetch_jobicy(client)
        assert all(j.is_remote for j in jobs)
