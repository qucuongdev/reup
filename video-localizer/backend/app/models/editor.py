import json
from datetime import UTC, datetime
from uuid import uuid4

from app.models.store import JobConflict, JobStore
from app.schemas.editor import DraftSave


class EditorStore:
    def __init__(self, jobs: JobStore):
        self.jobs = jobs
        with jobs.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS editor_drafts (
                job_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                clips TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS editor_exports (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL, plan TEXT NOT NULL,
                status TEXT NOT NULL, progress INTEGER NOT NULL, current_step TEXT NOT NULL,
                error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    def draft(self, job_id: str) -> dict | None:
        with self.jobs.connect() as db:
            row = db.execute("SELECT * FROM editor_drafts WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        return {"revision": row["revision"], "clips": json.loads(row["clips"])}

    def save(self, job_id: str, draft: DraftSave) -> dict:
        with self.jobs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM editor_drafts WHERE job_id=?", (job_id,)
            ).fetchone()
            if (row["revision"] if row else 0) != draft.revision:
                raise JobConflict("Timeline changed elsewhere. Reload before saving.")
            db.execute(
                "INSERT OR REPLACE INTO editor_drafts VALUES (?,?,?,?)",
                (
                    job_id,
                    draft.revision + 1,
                    json.dumps([clip.model_dump(mode="json") for clip in draft.clips]),
                    datetime.now(UTC).isoformat(),
                ),
            )
        return self.draft(job_id)

    def enqueue(self, job_id: str, revision: int) -> dict:
        with self.jobs.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM editor_drafts WHERE job_id=?", (job_id,)).fetchone()
            if not row or row["revision"] != revision:
                raise JobConflict("Save the current timeline before exporting")
            identifier, now = str(uuid4()), datetime.now(UTC).isoformat()
            plan = {"revision": revision, "clips": json.loads(row["clips"])}
            db.execute(
                "INSERT INTO editor_exports VALUES (?,?,?,?,?,?,?,?,?)",
                (identifier, job_id, json.dumps(plan), "queued", 0, "waiting", None, now, now),
            )
        return self.export(identifier)

    def export(self, identifier: str) -> dict:
        with self.jobs.connect() as db:
            row = db.execute("SELECT * FROM editor_exports WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError(identifier)
        values = dict(row)
        values["plan"] = json.loads(values["plan"])
        return values

    def exports(self, job_id: str) -> list[dict]:
        with self.jobs.connect() as db:
            rows = db.execute(
                "SELECT id FROM editor_exports WHERE job_id=? ORDER BY created_at DESC LIMIT 30",
                (job_id,),
            ).fetchall()
        return [self.export(row["id"]) for row in rows]

    def update(
        self, identifier: str, status: str, progress: int, step: str, error: str | None = None
    ):
        with self.jobs.connect() as db:
            db.execute(
                "UPDATE editor_exports SET status=?,progress=?,current_step=?,error=?,updated_at=? "
                "WHERE id=?",
                (status, progress, step, error, datetime.now(UTC).isoformat(), identifier),
            )

    def recover(self):
        with self.jobs.connect() as db:
            db.execute(
                "UPDATE editor_exports SET status='failed', current_step='interrupted', error=?, "
                "updated_at=? WHERE status IN ('queued','rendering')",
                (
                    "Export interrupted. Export the saved timeline again.",
                    datetime.now(UTC).isoformat(),
                ),
            )

    def assert_source_idle(self, job_id: str):
        with self.jobs.connect() as db:
            rows = db.execute(
                "SELECT job_id,plan FROM editor_exports WHERE status IN ('queued','rendering')"
            ).fetchall()
        for row in rows:
            if row["job_id"] == job_id or any(
                clip["job_id"] == job_id for clip in json.loads(row["plan"])["clips"]
            ):
                raise JobConflict("A queued/running timeline export uses this video")
        with self.jobs.connect() as db:
            drafts = db.execute(
                "SELECT clips FROM editor_drafts WHERE job_id != ?", (job_id,)
            ).fetchall()
        if any(clip["job_id"] == job_id for row in drafts for clip in json.loads(row["clips"])):
            raise JobConflict("Remove this video from other saved timelines before deleting it")

    def delete_project(self, job_id: str):
        with self.jobs.connect() as db:
            db.execute("DELETE FROM editor_exports WHERE job_id=?", (job_id,))
            db.execute("DELETE FROM editor_drafts WHERE job_id=?", (job_id,))
