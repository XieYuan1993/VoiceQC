"""GCS audio storage helper — shared by apps/api (uploads, playback URLs)
and apps/worker (pipeline stages).

All functions are synchronous (google-cloud-storage is sync); async callers
wrap them in run_in_threadpool. Object layout (DESIGN.md §2):

    raw/{batch_id}/{recording_id}/{original_name}
    raw/{batch_id}/_zips/{name}            (pending expansion)
    normalized/{recording_id}/{broker|customer|mono}.flac
    stt-results/{recording_id}/...         (BatchRecognize GcsOutputConfig)
"""

from __future__ import annotations

import datetime
from functools import lru_cache
from typing import IO, BinaryIO

from google.cloud import storage

from voiceqa_shared.settings import SharedSettings

_settings = SharedSettings()


@lru_cache(maxsize=1)
def client() -> storage.Client:
    import os

    project = _settings.GOOGLE_CLOUD_PROJECT or None
    key_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key_file:
        try:
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                key_file,
                scopes=["https://www.googleapis.com/auth/devstorage.full_control"],
            )
            # Use self-signed JWTs so token exchange doesn't need oauth2.googleapis.com.
            if hasattr(creds, "with_always_use_jwt_access"):
                creds = creds.with_always_use_jwt_access(True)
            return storage.Client(project=project, credentials=creds)
        except Exception:
            pass
    return storage.Client(project=project)


def bucket() -> storage.Bucket:
    return client().bucket(_settings.GCS_BUCKET_AUDIO)


def to_uri(key: str) -> str:
    return f"gs://{_settings.GCS_BUCKET_AUDIO}/{key}"


def from_uri(uri: str) -> tuple[str, str]:
    """gs://bucket/key -> (bucket, key)."""
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// uri: {uri!r}")
    bucket_name, _, key = uri[len("gs://") :].partition("/")
    return bucket_name, key


def blob_for_uri(uri: str) -> storage.Blob:
    bucket_name, key = from_uri(uri)
    return client().bucket(bucket_name).blob(key)


def upload_fileobj(key: str, fileobj: IO[bytes] | BinaryIO, content_type: str | None = None) -> str:
    blob = bucket().blob(key)
    blob.upload_from_file(fileobj, content_type=content_type, rewind=True)
    return to_uri(key)


def upload_file(key: str, local_path: str, content_type: str | None = None) -> str:
    blob = bucket().blob(key)
    blob.upload_from_filename(local_path, content_type=content_type)
    return to_uri(key)


def download_uri_to_file(uri: str, local_path: str) -> None:
    blob_for_uri(uri).download_to_filename(local_path)


def read_uri_bytes(uri: str) -> bytes:
    return blob_for_uri(uri).download_as_bytes()


def object_size(uri: str) -> int:
    blob = blob_for_uri(uri)
    blob.reload()
    return int(blob.size)


def read_uri_range(uri: str, start: int, end: int) -> bytes:
    """Bytes [start, end] inclusive (matches HTTP Range semantics)."""
    return blob_for_uri(uri).download_as_bytes(start=start, end=end)


def list_keys(prefix: str) -> list[str]:
    return [b.name for b in client().list_blobs(_settings.GCS_BUCKET_AUDIO, prefix=prefix)]


def delete_key(key: str) -> None:
    bucket().blob(key).delete()


def delete_uri(uri: str) -> bool:
    """Delete the object at a gs:// uri. Returns False if already gone."""
    try:
        blob_for_uri(uri).delete()
        return True
    except Exception:
        return False


def signed_url(uri: str, minutes: int = 10) -> str | None:
    """V4 signed GET URL, or None when the credentials can't sign (user ADC
    without a private key). Callers fall back to streaming through the API.
    """
    try:
        return blob_for_uri(uri).generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=minutes),
            method="GET",
        )
    except Exception:
        return None


def signed_put_url(
    key: str,
    content_type: str,
    minutes: int = 15,
) -> str | None:
    """V4 signed PUT URL for browser direct uploads, or None when the
    credentials can't sign (user ADC without a private key).
    """
    try:
        return bucket().blob(key).generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(minutes=minutes),
            method="PUT",
            content_type=content_type,
        )
    except Exception:
        return None
