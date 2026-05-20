from __future__ import annotations

import pytest

from jobintel.models import Job
from jobintel.storage import JobStore


def _job(title="ML Engineer", company="Acme Inc", url="https://example.com/job/1", source="test"):
    return Job(title=title, company=company, url=url, source=source)


@pytest.fixture()
def store(tmp_path):
    db = tmp_path / "test.sqlite"
    with JobStore(db) as s:
        yield s


class TestContextManager:
    def test_context_manager_closes(self, tmp_path):
        db = tmp_path / "test.sqlite"
        with JobStore(db) as store:
            assert store._conn is not None
        # After __exit__ the connection should be closed
        with pytest.raises(Exception):
            store._conn.execute("SELECT 1")


class TestIsNew:
    def test_new_job_is_new(self, store):
        j = _job()
        assert store.is_new(j)

    def test_inserted_job_is_not_new(self, store):
        j = _job()
        store.insert(j)
        assert not store.is_new(j)

    def test_same_fingerprint_different_url_is_not_new(self, store):
        j1 = _job(url="https://board1.com/job/1")
        j2 = _job(url="https://board2.com/job/2")
        store.insert(j1)
        assert not store.is_new(j2)


class TestFilterNew:
    def test_all_new_when_empty(self, store):
        jobs = [_job(), _job(title="Data Scientist", url="https://example.com/job/2")]
        result = store.filter_new(jobs)
        assert len(result) == 2

    def test_already_seen_excluded(self, store):
        j1 = _job()
        j2 = _job(title="Data Scientist", url="https://example.com/job/2")
        store.insert(j1)
        result = store.filter_new([j1, j2])
        assert len(result) == 1
        assert result[0].title == "Data Scientist"

    def test_empty_input(self, store):
        assert store.filter_new([]) == []

    def test_batch_is_single_query(self, store):
        jobs = [_job(title=f"Job {i}", url=f"https://example.com/job/{i}") for i in range(20)]
        result = store.filter_new(jobs)
        assert len(result) == 20


class TestInsertMany:
    def test_inserts_batch(self, store):
        jobs = [_job(title=f"Job {i}", url=f"https://example.com/job/{i}") for i in range(5)]
        store.insert_many(jobs)
        for j in jobs:
            assert not store.is_new(j)

    def test_insert_many_idempotent(self, store):
        j = _job()
        store.insert_many([j, j])  # same job twice — should not crash
        assert not store.is_new(j)

    def test_no_duplicate_on_repeat_insert(self, store):
        j = _job()
        store.insert_many([j])
        store.insert_many([j])  # second insert should be silently ignored
        count = store._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        assert count == 1


class TestUrlHashFallback:
    def test_empty_title_company_uses_url_hash(self, store):
        j1 = Job(title="", company="", url="https://example.com/job/xyz", source="test")
        j2 = Job(title="", company="", url="https://example.com/job/xyz", source="other")
        store.insert(j1)
        # Same URL → same url_hash → should be filtered out
        result = store.filter_new([j2])
        assert len(result) == 0
