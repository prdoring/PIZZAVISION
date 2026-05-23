"""Configuration storage adapter.

Two backends share one API, mirroring vote_store.py / image_store.py:
    - Local file (dev): reads/writes pizzavision/options.json directly.
    - Firestore (prod): file is the static seed; voting_state + options
      ordering live in a singleton Firestore doc that survives Cloud Run
      cold starts.

The factory keys on GOOGLE_CLOUD_PROJECT — same trigger as vote_store and
image_store. Without it (local dev), options.json is the source of truth.

Why this exists:
    Cloud Run container fs is ephemeral. Before this module, every admin
    write to options.json (voting_state, options reordering, restore)
    evaporated whenever the instance scaled to zero. Votes were already
    in Firestore via vote_store; this brings the rest of the runtime-
    mutable config along.

Year-update safety:
    When Patrick deploys a new year's lineup, the bands in options.json
    change but Firestore still holds last year's overlay. Rather than
    silently serving stale options, FirestoreConfigStore compares the
    label set of file vs overlay; on mismatch it ignores the overlay and
    serves file values. The admin "Restore Defaults" button (which writes
    the file's content back through this store) re-syncs both sides.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from .utils import get_file_path


OPTIONS_FILENAME = "options.json"

# Fields that the admin UI mutates at runtime. Everything else (votes,
# award_details, per-entry metadata) is static, baked into the image, and
# never overlaid from Firestore.
MUTABLE_FIELDS = ("voting_state", "options")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_file(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4, ensure_ascii=False)


class LocalConfigStore:
    """Reads/writes pizzavision/options.json directly. Used in local dev."""

    def __init__(self, options_path: str) -> None:
        self._path = options_path

    def load(self) -> dict:
        return _read_file(self._path)

    def save(self, data: dict) -> None:
        _write_file(self._path, data)


class FirestoreConfigStore:
    """File is the static seed; mutable fields overlay from a Firestore doc.

    Read path:
        1. Read options.json (static fields + defaults for mutable ones).
        2. Fetch the singleton config doc from Firestore.
        3. For each mutable field present in the overlay, replace the file
           value. Options gets a label-set sanity check first; on mismatch
           the overlay is ignored (year-update case).

    Write path:
        Persists only the mutable slice to Firestore. The file on the
        container is never touched — it's read-only image content.
    """

    COLLECTION = "pizzavision_config"
    DOC_ID = "singleton"

    def __init__(self, project_id: str, options_path: str) -> None:
        self._project_id = project_id
        self._path = options_path
        self._client = None

    def _doc_ref(self):
        if self._client is None:
            from google.cloud import firestore

            self._client = firestore.Client(project=self._project_id)
        return self._client.collection(self.COLLECTION).document(self.DOC_ID)

    def _fetch_overlay(self) -> dict:
        snap = self._doc_ref().get()
        return snap.to_dict() or {} if snap.exists else {}

    def load(self) -> dict:
        merged = _read_file(self._path)
        overlay = self._fetch_overlay()
        if not overlay:
            return merged

        if "voting_state" in overlay:
            merged["voting_state"] = overlay["voting_state"]

        if "options" in overlay:
            file_labels = {o["label"] for o in merged.get("options", [])}
            overlay_labels = {o["label"] for o in overlay["options"]}
            if file_labels == overlay_labels:
                merged["options"] = overlay["options"]
            else:
                # New year deploy: file shipped a different lineup than
                # what's in Firestore. Trust the file; let admin re-sync
                # by clicking "Restore Defaults" (which writes the file
                # back through save()).
                print(
                    f"[config_store] options label mismatch — file has "
                    f"{len(file_labels)} entries, Firestore has "
                    f"{len(overlay_labels)}. Ignoring Firestore overlay; "
                    f"click 'Restore Defaults' in admin to re-sync."
                )

        return merged

    def save(self, data: dict) -> None:
        payload = {f: data[f] for f in MUTABLE_FIELDS if f in data}
        payload["updated_at"] = _now_iso()
        self._doc_ref().set(payload)


_store_singleton: Optional[object] = None


def get_config_store():
    """Return a singleton config store keyed on GOOGLE_CLOUD_PROJECT.

    Firestore in prod, local file otherwise. Mirrors get_vote_store() and
    get_image_store().
    """
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton

    options_path = get_file_path(os.path.join("pizzavision", OPTIONS_FILENAME))
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if project_id:
        print(f"ConfigStore: Firestore (project: {project_id})")
        _store_singleton = FirestoreConfigStore(project_id, options_path)
    else:
        print(f"ConfigStore: local file ({options_path})")
        _store_singleton = LocalConfigStore(options_path)
    return _store_singleton
