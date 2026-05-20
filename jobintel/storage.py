from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from jobintel.dedupe import url_hash
from jobintel.models import Job


class JobStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        root = Path(__file__).resolve().parent.parent
        self._path = Path(db_path) if db_path else root / "data" / "jobintel.sqlite"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS seen (
                fingerprint TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                company TEXT,
                source TEXT,
                first_seen INTEGER NOT NULL,
                PRIMARY KEY (fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_seen_url ON seen(url_hash);
            """
        )
        self._conn.commit()

    def __enter__(self) -> "JobStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def is_new(self, job: Job) -> bool:
        fp = job.fingerprint()
        row = self._conn.execute("SELECT 1 FROM seen WHERE fingerprint = ?", (fp,)).fetchone()
        return row is None

    def filter_new(self, jobs: list[Job]) -> list[Job]:
        """Return only jobs not already in the store. Single batch query per check."""
        if not jobs:
            return []
        fp_map: dict[str, Job] = {j.fingerprint(): j for j in jobs}
        placeholders = ",".join("?" * len(fp_map))
        seen_fps = {
            row[0]
            for row in self._conn.execute(
                f"SELECT fingerprint FROM seen WHERE fingerprint IN ({placeholders})",
                list(fp_map),
            )
        }
        candidates = [j for fp, j in fp_map.items() if fp not in seen_fps]
        if not candidates:
            return []
        # secondary check: url_hash for jobs whose fingerprint came from the URL itself
        uh_map: dict[str, Job] = {url_hash(j.url): j for j in candidates}
        uh_placeholders = ",".join("?" * len(uh_map))
        seen_uhs = {
            row[0]
            for row in self._conn.execute(
                f"SELECT url_hash FROM seen WHERE url_hash IN ({uh_placeholders})",
                list(uh_map),
            )
        }
        return [j for uh, j in uh_map.items() if uh not in seen_uhs]

    def insert(self, job: Job) -> None:
        now = int(time.time())
        self._conn.execute(
            """INSERT OR IGNORE INTO seen
               (fingerprint, url_hash, url, title, company, source, first_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                job.fingerprint(),
                url_hash(job.url),
                job.url,
                job.title,
                job.company,
                job.source,
                now,
            ),
        )
        self._conn.commit()

    def insert_many(self, jobs: list[Job]) -> None:
        now = int(time.time())
        rows = [
            (
                j.fingerprint(),
                url_hash(j.url),
                j.url,
                j.title,
                j.company,
                j.source,
                now,
            )
            for j in jobs
        ]
        self._conn.executemany(
            """INSERT OR IGNORE INTO seen
               (fingerprint, url_hash, url, title, company, source, first_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
