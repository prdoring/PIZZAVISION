"""Vote storage adapter.

Two backends share one API, keyed by a stable client UUID rather than the
mutable band name. The factory picks Firestore when GOOGLE_CLOUD_PROJECT is
set (Cloud Run) and falls back to TinyDB on local dev.

Document shape (both backends):
    {client_id: str, user: str, rank: list[str],
     created_at: iso8601-str,        # set once on first insert
     updated_at: iso8601-str,        # bumped on any write
     rank_updated_at: iso8601-str}   # bumped only on rank changes

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
        now = _now_iso()
        if self._db.search(self._Q.client_id == client_id):
            self._db.update(
                {"user": user, "rank": rank, "updated_at": now, "rank_updated_at": now},
                self._Q.client_id == client_id,
            )
        else:
            self._db.insert({
                "client_id": client_id,
                "user": user,
                "rank": rank,
                "created_at": now,
                "updated_at": now,
                "rank_updated_at": now,
            })

    def update_name(self, client_id: str, new_name: str) -> None:
        now = _now_iso()
        if self._db.search(self._Q.client_id == client_id):
            self._db.update(
                {"user": new_name, "updated_at": now},
                self._Q.client_id == client_id,
            )
        else:
            self._db.insert({
                "client_id": client_id,
                "user": new_name,
                "rank": [],
                "created_at": now,
                "updated_at": now,
            })

    def upsert_user_profile(self, client_id: str, fields: dict) -> None:
        now = _now_iso()
        if self._db.search(self._Q.client_id == client_id):
            self._db.update(
                {**fields, "updated_at": now},
                self._Q.client_id == client_id,
            )
        else:
            merged = {
                **fields,
                "client_id": client_id,
                "created_at": now,
                "updated_at": now,
            }
            merged.setdefault("rank", [])
            self._db.insert(merged)

    def delete_by_client(self, client_id: str) -> int:
        removed = self._db.remove(self._Q.client_id == client_id)
        return len(removed)

    def clear_rank_by_client(self, client_id: str) -> bool:
        if not self._db.search(self._Q.client_id == client_id):
            return False
        now = _now_iso()
        self._db.update(
            {"rank": [], "updated_at": now, "rank_updated_at": None},
            self._Q.client_id == client_id,
        )
        return True

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
        now = _now_iso()
        ref = self._coll().document(client_id)
        if ref.get().exists:
            ref.update({
                "user": user,
                "rank": rank,
                "updated_at": now,
                "rank_updated_at": now,
            })
        else:
            ref.set({
                "client_id": client_id,
                "user": user,
                "rank": rank,
                "created_at": now,
                "updated_at": now,
                "rank_updated_at": now,
            })

    def update_name(self, client_id: str, new_name: str) -> None:
        now = _now_iso()
        ref = self._coll().document(client_id)
        if ref.get().exists:
            ref.update({"user": new_name, "updated_at": now})
        else:
            ref.set({
                "client_id": client_id,
                "user": new_name,
                "rank": [],
                "created_at": now,
                "updated_at": now,
            })

    def upsert_user_profile(self, client_id: str, fields: dict) -> None:
        now = _now_iso()
        ref = self._coll().document(client_id)
        if ref.get().exists:
            ref.update({**fields, "updated_at": now})
        else:
            ref.set({
                **fields,
                "client_id": client_id,
                "created_at": now,
                "updated_at": now,
            })

    def delete_by_client(self, client_id: str) -> int:
        ref = self._coll().document(client_id)
        if not ref.get().exists:
            return 0
        ref.delete()
        return 1

    def clear_rank_by_client(self, client_id: str) -> bool:
        ref = self._coll().document(client_id)
        if not ref.get().exists:
            return False
        now = _now_iso()
        ref.update({"rank": [], "updated_at": now, "rank_updated_at": None})
        return True

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
