from __future__ import annotations

import pytest

from jobintel.dedupe import normalize_company, normalize_title, url_hash
from jobintel.models import Job


class TestNormalizeTitle:
    def test_lowercase(self):
        assert normalize_title("Senior Software Engineer") == "senior software engineer"

    def test_unicode_diacritics(self):
        assert normalize_title("Développeur Python") == "developpeur python"

    def test_punctuation_removed(self):
        assert normalize_title("Sr. Software Engineer") == "sr software engineer"

    def test_parens_removed(self):
        assert normalize_title("Software Engineer (Python)") == "software engineer python"

    def test_slash_removed(self):
        assert normalize_title("AI/ML Engineer") == "ai ml engineer"

    def test_empty_string(self):
        assert normalize_title("") == ""

    def test_none_like(self):
        assert normalize_title(None) == ""  # type: ignore[arg-type]

    def test_collapse_whitespace(self):
        assert normalize_title("  Data   Scientist  ") == "data scientist"


class TestNormalizeCompany:
    def test_strips_inc(self):
        assert normalize_company("Acme Inc.") == "acme"

    def test_strips_llc(self):
        assert normalize_company("Widget LLC") == "widget"

    def test_strips_ltd(self):
        assert normalize_company("Startup Ltd") == "startup"

    def test_strips_limited(self):
        assert normalize_company("OpenAI Limited") == "openai"

    def test_strips_corporation(self):
        assert normalize_company("IBM Corporation") == "ibm"

    def test_strips_gmbh(self):
        assert normalize_company("DeepMind GmbH") == "deepmind"

    def test_strips_plc(self):
        assert normalize_company("ARM Holdings PLC") == "arm holdings"

    def test_strips_sarl(self):
        assert normalize_company("Eiffel SARL") == "eiffel"

    def test_strips_ag(self):
        assert normalize_company("SAP AG") == "sap"

    def test_strips_incorporated(self):
        assert normalize_company("Apple Incorporated") == "apple"

    def test_ampersand_becomes_space(self):
        result = normalize_company("AT&T")
        assert "at" in result and "t" in result

    def test_trailing_comma_stripped(self):
        assert normalize_company("Some Corp,") == "some"

    def test_empty_string(self):
        assert normalize_company("") == ""


class TestUrlHash:
    def test_returns_32_chars(self):
        h = url_hash("https://example.com/job/123")
        assert len(h) == 32

    def test_deterministic(self):
        url = "https://example.com/job/123"
        assert url_hash(url) == url_hash(url)

    def test_different_urls_different_hash(self):
        assert url_hash("https://a.com/1") != url_hash("https://a.com/2")

    def test_empty_url(self):
        assert len(url_hash("")) == 32


class TestFingerprint:
    def _job(self, title="", company="", url="https://example.com/job/1"):
        return Job(title=title, company=company, url=url, source="test")

    def test_normal_fingerprint(self):
        j = self._job("Software Engineer", "Acme Inc.")
        fp = j.fingerprint()
        assert fp == "software engineer|acme"

    def test_empty_title_and_company_falls_back_to_url(self):
        j = self._job("", "", "https://example.com/job/xyz")
        fp = j.fingerprint()
        assert fp == url_hash("https://example.com/job/xyz")

    def test_same_job_different_company_suffix(self):
        j1 = self._job("Data Scientist", "DeepMind Limited")
        j2 = self._job("Data Scientist", "DeepMind Ltd")
        assert j1.fingerprint() == j2.fingerprint()

    def test_same_job_different_url_still_matches(self):
        j1 = self._job("ML Engineer", "OpenAI Inc", "https://board1.com/job/1")
        j2 = self._job("ML Engineer", "OpenAI Inc.", "https://board2.com/job/2")
        assert j1.fingerprint() == j2.fingerprint()
