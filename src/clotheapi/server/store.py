"""工作紀錄存在本機 SQLite，圖片存在資料夾。重開機後仍可查。"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Job:
    id: str
    status: str
    engine: str
    error: str | None
    result_path: str | None


class JobStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.data_dir / "jobs.sqlite3", check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                engine TEXT NOT NULL,
                error TEXT,
                result_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._db.commit()

    def create(self, engine: str) -> Job:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "INSERT INTO jobs (id, status, engine) VALUES (?, 'pending', ?)",
                (job_id, engine),
            )
            self._db.commit()
        return Job(id=job_id, status="pending", engine=engine, error=None, result_path=None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, status, engine, error, result_path FROM jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return Job(id=row[0], status=row[1], engine=row[2], error=row[3], result_path=row[4])

    def update(self, job_id: str, *, status: str, error: str | None = None, result_path: str | None = None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE jobs SET status = ?, error = ?, result_path = ? WHERE id = ?",
                (status, error, result_path, job_id),
            )
            self._db.commit()

    def save_upload(self, job_id: str, name: str, data: bytes) -> Path:
        path = self.data_dir / f"{job_id}-{name}"
        path.write_bytes(data)
        return path

    def result_file(self, job_id: str) -> Path:
        return self.data_dir / f"{job_id}-result.png"
