import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.schemas.jobs import ACTIVE_STATUSES, JobCreate, JobStatus, JobView


class JobConflict(RuntimeError):
    pass


class JobStore:
    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, config TEXT NOT NULL, source_name TEXT NOT NULL,
                status TEXT NOT NULL, progress INTEGER NOT NULL, current_step TEXT NOT NULL,
                error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0
            )""")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=20)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def view(row: sqlite3.Row) -> JobView:
        values = dict(row)
        config = json.loads(values.pop("config"))
        return JobView.model_validate(config | values)

    def create(self, job_id: str, config: JobCreate, source_name: str) -> JobView:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id,
                    config.model_dump_json(),
                    source_name,
                    "queued",
                    0,
                    "ready",
                    None,
                    now,
                    now,
                    0,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> JobView:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self.view(row)

    def list(self, limit: int = 100, offset: int = 0) -> list[JobView]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [self.view(row) for row in rows]

    def schedule(self, job_id: str, retry: bool = False) -> JobView:
        expected = "failed" if retry else "queued"
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET status='queued', current_step='waiting', progress=0,
                error=NULL, updated_at=? WHERE id=? AND status=?
                AND (status='failed' OR current_step='ready')""",
                (datetime.now(UTC).isoformat(), job_id, expected),
            )
            if cursor.rowcount != 1:
                raise JobConflict(
                    "Job is already scheduled, running, or has an incompatible status"
                )
        return self.get(job_id)

    def claim(self, job_id: str) -> JobView | None:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE jobs SET current_step='input', attempt=attempt+1, updated_at=?
                WHERE id=? AND status='queued' AND current_step='waiting'""",
                (datetime.now(UTC).isoformat(), job_id),
            )
        return self.get(job_id) if cursor.rowcount else None

    def stage(self, job_id: str, status: JobStatus, progress: int, step: str) -> None:
        if not 0 <= progress <= 100:
            raise ValueError("Progress out of range")
        order = {
            status: index for index, status in enumerate(JobStatus) if status != JobStatus.failed
        }
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            current = JobStatus(row["status"])
            if current in {JobStatus.failed, JobStatus.completed}:
                raise JobConflict("Terminal job cannot advance")
            if (
                status == JobStatus.failed
                or order[status] < order[current]
                or progress < row["progress"]
            ):
                raise JobConflict("Job stages must move forward")
            connection.execute(
                "UPDATE jobs SET status=?, progress=?, current_step=?, updated_at=? WHERE id=?",
                (status.value, progress, step, datetime.now(UTC).isoformat(), job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET status='failed', error=?, current_step='failed', "
                "updated_at=? WHERE id=?",
                (error, datetime.now(UTC).isoformat(), job_id),
            )

    def recover(self) -> None:
        # No job resumes partially produced artifacts after a process restart.
        statuses = tuple(s.value for s in ACTIVE_STATUSES)
        with self.connect() as connection:
            connection.execute(
                f"""UPDATE jobs SET status='failed', current_step='interrupted',
                error=?, updated_at=?
                WHERE status IN ({",".join("?" for _ in statuses)})
                OR (status='queued' AND current_step IN ('input','waiting'))""",
                (
                    "Worker interrupted by application restart. Retry to run a fresh attempt.",
                    datetime.now(UTC).isoformat(),
                    *statuses,
                ),
            )

    def delete(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.status in ACTIVE_STATUSES or job.current_step in {"waiting", "input"}:
            raise JobConflict("Cannot delete a scheduled or running job")
        with self.connect() as connection:
            connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
