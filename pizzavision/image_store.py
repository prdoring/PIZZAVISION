"""Where generated band images live.

Two backends share one API:
    - Local disk (dev): pizzavision/static/generated/<client_id>/<idx>.png
    - Google Cloud Storage (prod): gs://$PV_GCS_BUCKET/generated/<client_id>/<idx>.png

The factory keys on GOOGLE_CLOUD_PROJECT — the same trigger vote_store.py
uses for Firestore vs TinyDB. PV_GCS_BUCKET is required when running on
Cloud Run; otherwise images would land in a runtime-ephemeral container fs.

Two operations:
    save_candidate(client_id, idx, image_bytes) -> url
        Stores one of the three candidate images, returns a URL the client
        can render directly (Flask static path locally, public GCS URL in
        prod).

    keep_chosen_delete_rest(client_id, chosen_idx) -> url
        Called when the user picks their final image. Returns the chosen
        URL (same one the client already had), and deletes the other two
        candidates so the storage doesn't accumulate garbage.

Both operations tolerate missing files / blobs (idempotent — guards
against races if the client double-taps Pick).
"""

from __future__ import annotations

import os
import time
from typing import Optional


# Candidate slots. Currently 2 -- keep in lockstep with the matching
# constants on the client and in routes._generate_prompt_then_fan_out.
_CANDIDATE_INDICES = (0, 1)


def _bust(url: str) -> str:
    """Append a ?v=<unix-seconds> cache-buster.

    The reroll flow overwrites a slot's file at the same path. Without a
    URL-level version, browsers happily keep showing the cached old PNG
    after a reroll and the user thinks the regenerate didn't fire.
    """
    sep = '&' if '?' in url else '?'
    return f"{url}{sep}v={int(time.time())}"


# ---------------------------------------------------------------
# Local-disk backend
# ---------------------------------------------------------------

class LocalImageStore:
    """Writes to pizzavision/static/generated/<client_id>/<idx>.png on dev."""

    def __init__(self) -> None:
        # __file__ is pizzavision/image_store.py; static/generated sits next to it.
        here = os.path.dirname(os.path.abspath(__file__))
        self._root = os.path.join(here, "static", "generated")

    def _dir_for(self, client_id: str) -> str:
        return os.path.join(self._root, client_id)

    def _path_for(self, client_id: str, idx: int) -> str:
        return os.path.join(self._dir_for(client_id), f"{idx}.png")

    def save_candidate(self, client_id: str, idx: int, image_bytes: bytes) -> str:
        dir_ = self._dir_for(client_id)
        os.makedirs(dir_, exist_ok=True)
        path = self._path_for(client_id, idx)
        with open(path, "wb") as fh:
            fh.write(image_bytes)
        # Matches the registered URL routing:
        #   app prefix /pizzavision (pizzavision.py)
        #   + blueprint static_url_path /voting/static (pizzavision/__init__.py)
        return _bust(f"/pizzavision/voting/static/generated/{client_id}/{idx}.png")

    def delete_candidate(self, client_id: str, idx: int) -> None:
        try:
            os.remove(self._path_for(client_id, idx))
        except FileNotFoundError:
            pass

    def keep_chosen_delete_rest(self, client_id: str, chosen_idx: int) -> str:
        for i in _CANDIDATE_INDICES:
            if i == chosen_idx:
                continue
            path = self._path_for(client_id, i)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        return _bust(f"/pizzavision/voting/static/generated/{client_id}/{chosen_idx}.png")


# ---------------------------------------------------------------
# GCS backend
# ---------------------------------------------------------------

class GCSImageStore:
    """Writes public-read PNGs to gs://<bucket>/generated/<client_id>/<idx>.png."""

    def __init__(self, project_id: str, bucket_name: str) -> None:
        self._project_id = project_id
        self._bucket_name = bucket_name
        self._bucket = None  # lazy

    def _get_bucket(self):
        if self._bucket is None:
            from google.cloud import storage

            client = storage.Client(project=self._project_id)
            self._bucket = client.bucket(self._bucket_name)
        return self._bucket

    def _blob_for(self, client_id: str, idx: int):
        return self._get_bucket().blob(f"generated/{client_id}/{idx}.png")

    def save_candidate(self, client_id: str, idx: int, image_bytes: bytes) -> str:
        blob = self._blob_for(client_id, idx)
        blob.upload_from_string(image_bytes, content_type="image/png")
        # Per-object public ACL so a plain <img src> renders in the browser
        # without authentication. Requires the bucket to be in fine-grained
        # access control mode (not Uniform).
        blob.make_public()
        return _bust(blob.public_url)

    def delete_candidate(self, client_id: str, idx: int) -> None:
        try:
            self._blob_for(client_id, idx).delete()
        except Exception:
            # 404 / already deleted — fine.
            pass

    def keep_chosen_delete_rest(self, client_id: str, chosen_idx: int) -> str:
        for i in _CANDIDATE_INDICES:
            if i == chosen_idx:
                continue
            blob = self._blob_for(client_id, i)
            try:
                blob.delete()
            except Exception:
                # 404 / already deleted — fine. Anything else, swallow too
                # rather than poison the user's onboarding completion over
                # a cleanup failure.
                pass
        return _bust(self._blob_for(client_id, chosen_idx).public_url)


# ---------------------------------------------------------------
# Factory
# ---------------------------------------------------------------

_store_singleton: Optional[object] = None


def get_image_store():
    """Return a singleton image store keyed on GOOGLE_CLOUD_PROJECT.

    GCS in prod (project ID + PV_GCS_BUCKET both set), local disk otherwise.
    Mirrors vote_store.get_vote_store().
    """
    global _store_singleton
    if _store_singleton is not None:
        return _store_singleton

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    bucket = os.environ.get("PV_GCS_BUCKET")
    if project_id and bucket:
        print(f"ImageStore: GCS (bucket: {bucket})")
        _store_singleton = GCSImageStore(project_id, bucket)
    else:
        if project_id and not bucket:
            print(
                "ImageStore: GOOGLE_CLOUD_PROJECT is set but PV_GCS_BUCKET is "
                "not — falling back to local disk. Set PV_GCS_BUCKET on "
                "Cloud Run to use GCS."
            )
        else:
            print("ImageStore: local disk (pizzavision/static/generated/)")
        _store_singleton = LocalImageStore()
    return _store_singleton
