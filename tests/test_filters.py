from __future__ import annotations

import pytest

from jobintel.filters import filter_jobs, infer_regions, matches_vertical, passes_region_filter
from jobintel.models import Job


def _job(title="", company="", location="", snippet="", tags=None, is_remote=False):
    return Job(
        title=title,
        company=company,
        url="https://example.com/job/1",
        source="test",
        location_text=location,
        description_snippet=snippet,
        is_remote=is_remote,
        raw={"tags": tags or []},
    )


class TestMatchesVertical:
    def test_ai_matches_machine_learning(self):
        assert matches_vertical(_job(title="Machine Learning Engineer"))

    def test_ai_matches_llm(self):
        assert matches_vertical(_job(title="LLM Platform Engineer"))

    def test_ai_matches_data_scientist(self):
        assert matches_vertical(_job(title="Senior Data Scientist"))

    def test_saas_matches_saas(self):
        assert matches_vertical(_job(title="SaaS Growth Engineer"))

    def test_saas_matches_product_led(self):
        assert matches_vertical(_job(snippet="product-led growth company"))

    def test_fintech_matches_fintech(self):
        assert matches_vertical(_job(title="Fintech Backend Engineer"))

    def test_fintech_matches_payments(self):
        assert matches_vertical(_job(title="Payments Platform Engineer"))

    def test_fintech_matches_defi(self):
        assert matches_vertical(_job(title="DeFi Protocol Engineer"))

    def test_health_matches_healthtech(self):
        assert matches_vertical(_job(title="HealthTech Product Manager"))

    def test_health_matches_telehealth(self):
        assert matches_vertical(_job(snippet="telehealth platform for patients"))

    def test_no_match_generic_job(self):
        assert not matches_vertical(_job(title="Office Manager", snippet="We need an office manager"))

    def test_matches_via_tags(self):
        assert matches_vertical(_job(tags=["machine learning", "python"]))

    def test_matches_via_snippet(self):
        assert matches_vertical(_job(snippet="We build LLM-powered products for healthcare"))


class TestInferRegions:
    def test_is_remote_adds_remote(self):
        j = _job(is_remote=True)
        assert "remote" in infer_regions(j)

    def test_uk_detected_from_location(self):
        j = _job(location="London, UK")
        assert "uk" in infer_regions(j)

    def test_us_detected_from_location(self):
        j = _job(location="San Francisco, CA")
        assert "us" in infer_regions(j)

    def test_eu_detected_from_location(self):
        j = _job(location="Berlin, Germany")
        assert "eu" in infer_regions(j)

    def test_canada_detected_from_location(self):
        j = _job(location="Toronto, Ontario")
        assert "canada" in infer_regions(j)

    def test_multiple_regions(self):
        j = _job(location="London or New York")
        regions = infer_regions(j)
        assert "uk" in regions
        assert "us" in regions

    def test_no_region_for_unknown_location(self):
        j = _job(location="Timbuktu")
        regions = infer_regions(j)
        assert "uk" not in regions
        assert "us" not in regions


class TestPassesRegionFilter:
    def test_none_want_accepts_all(self):
        j = _job(location="London")
        j.regions = ["uk"]
        assert passes_region_filter(j, None)

    def test_empty_want_accepts_all(self):
        j = _job(location="London")
        j.regions = ["uk"]
        assert passes_region_filter(j, [])

    def test_matching_region_passes(self):
        j = _job()
        j.regions = ["uk", "remote"]
        assert passes_region_filter(j, ["uk"])

    def test_non_matching_region_fails(self):
        j = _job()
        j.regions = ["uk"]
        assert not passes_region_filter(j, ["us"])

    def test_case_insensitive(self):
        j = _job()
        j.regions = ["uk"]
        assert passes_region_filter(j, ["UK"])


class TestFilterJobs:
    def test_filters_by_vertical(self):
        jobs = [
            _job(title="ML Engineer"),
            _job(title="Office Manager"),
        ]
        result = filter_jobs(jobs)
        assert len(result) == 1
        assert result[0].title == "ML Engineer"

    def test_filters_by_region(self):
        jobs = [
            _job(title="Data Scientist", location="London"),
            _job(title="Data Scientist", location="Toronto"),
        ]
        result = filter_jobs(jobs, regions=["uk"])
        assert len(result) == 1
        assert "uk" in result[0].regions

    def test_all_regions_passes_all_verticals(self):
        jobs = [
            _job(title="ML Engineer", location="Tokyo"),
            _job(title="Fintech Dev", location="Singapore"),
        ]
        result = filter_jobs(jobs, regions=None)
        assert len(result) == 2
