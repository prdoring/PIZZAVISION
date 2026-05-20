"""Vote storage adapter.

Two backends share one API, keyed by a stable client UUID rather than the
mutable band name. The factory picks Firestore when GOOGLE_CLOUD_PROJECT is
set (Cloud Run) and falls back to TinyDB on local dev.

Document shape (both backends):
    {client_id: str, user: str, rank: list[str], updated_at: iso8601-str}

In Firestore the document ID is client_id; in TinyDB rows are matched by
Query().client_id == <uuid>.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TinyDBVoteStore:
    def __init__(self, db_path: str):
        from tinydb import TinyDB, Query

        self._db = TinyDB(db_path)
        self._Q = Query()

    def all(self) -> list[dict]:
        return list(self._db.all())

    def get_by_client(self, client_id: str) -> Optional[dict]:
        rows = self._db.search(self._Q.client_id == client_id)
        return rows[0] if rows else None

    def upsert_rank(self, client_id: str, user: str, rank: list[str]) -> None:
        doc = {
            "client_id": client_id,
            "user": user,
            "rank": rank,
            "updated_at": _now_iso(),
        }
        if self._db.search(self._Q.client_id == client_id):
            self._db.update(doc, self._Q.client_id == client_id)
        else:
            self._db.insert(doc)

    def update_name(self, client_id: str, new_name: str) -> None:
        if self._db.search(self._Q.client_id == client_id):
            self._db.update(
                {"user": new_name, "updated_at": _now_iso()},
                self._Q.client_id == client_id,
            )
        else:
            self._db.insert(
                {
                    "client_id": client_id,
                    "user": new_name,
                    "rank": [],
                    "updated_at": _now_iso(),
                }
            )

    def upsert_user_profile(self, client_id: str, fields: dict) -> None:
        merged = {**fields, "client_id": client_id, "updated_at": _now_iso()}
        if self._db.search(self._Q.client_id == client_id):
            self._db.update(merged, self._Q.client_id == client_id)
        else:
            merged.setdefault("rank", [])
            self._db.insert(merged)

    def truncate(self) -> None:
        self._db.truncate()


class FirestoreVoteStore:
    COLLECTION = "pizzavision_votes"

    def __init__(self, project_id: str):
        self._project_id = project_id
        self._client = None

    def _coll(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=self._project_id)
        return self._client.collection(self.COLLECTION)

    def all(self) -> list[dict]:
        return [doc.to_dict() for doc in self._coll().stream()]

    def get_by_client(self, client_id: str) -> Optional[dict]:
        snap = self._coll().document(client_id).get()
        return snap.to_dict() if snap.exists else None

    def upsert_rank(self, client_id: str, user: str, rank: list[str]) -> None:
        self._coll().document(client_id).set(
            {
                "client_id": client_id,
                "user": user,
                "rank": rank,
                "updated_at": _now_iso(),
            }
        )

    def update_name(self, client_id: str, new_name: str) -> None:
        ref = self._coll().document(client_id)
        if ref.get().exists:
            ref.update({"user": new_name, "updated_at": _now_iso()})
        else:
            ref.set(
                {
                    "client_id": client_id,
                    "user": new_name,
                    "rank": [],
                    "updated_at": _now_iso(),
                }
            )

    def upsert_user_profile(self, client_id: str, fields: dict) -> None:
        payload = {**fields, "client_id": client_id, "updated_at": _now_iso()}
        self._coll().document(client_id).set(payload, merge=True)

    def truncate(self) -> None:
        coll = self._coll()
        batch = self._client.batch()
        n = 0
        for doc in coll.stream():
            batch.delete(doc.reference)
            n += 1
            if n % 400 == 0:
                batch.commit()
                batch = self._client.batch()
        if n % 400 != 0:
            batch.commit()


def get_vote_store():
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id:
        print(f"VoteStore: Firestore (project: {project_id})")
        return FirestoreVoteStore(project_id)

    from .utils import get_file_path

    db_path = get_file_path("db.json")
    print(f"VoteStore: TinyDB ({db_path})")
    return TinyDBVoteStore(db_path)
