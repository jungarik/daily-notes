"""
Object storage for voice audio (S3-compatible: Railway bucket, Cloudflare R2, S3).

Audio bytes live in the bucket; the message row keeps only the object key. If S3
isn't configured, uploads are skipped (the bot still works, just without stored
audio).
"""

import uuid
import logging

import config

logger = logging.getLogger(__name__)

_client = None


def is_configured() -> bool:
    """True when all S3 credentials/bucket are present."""
    return bool(
        config.S3_BUCKET and config.S3_ACCESS_KEY_ID and config.S3_SECRET_ACCESS_KEY
    )


def missing_config() -> list[str]:
    """Names of the S3 settings that are still unset."""
    return [
        name
        for name, value in (
            ("S3_BUCKET", config.S3_BUCKET),
            ("S3_ACCESS_KEY_ID", config.S3_ACCESS_KEY_ID),
            ("S3_SECRET_ACCESS_KEY", config.S3_SECRET_ACCESS_KEY),
        )
        if not value
    ]


# Backwards-compatible alias.
_configured = is_configured


def _s3():
    """Lazily create a boto3 S3 client (works with any S3-compatible endpoint)."""
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        # For a custom endpoint (non-AWS: R2, MinIO, some Railway buckets) use
        # path-style addressing and disable the CRC checksums boto3 >= 1.36 sends
        # by default, which those providers reject. For real AWS S3 (no endpoint)
        # use the defaults.
        client_config = None
        if config.S3_ENDPOINT_URL:
            client_config = Config(
                signature_version="s3v4",
                s3={"addressing_style": config.S3_ADDRESSING_STYLE},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            )
        _client = boto3.client(
            "s3",
            endpoint_url=config.S3_ENDPOINT_URL or None,
            aws_access_key_id=config.S3_ACCESS_KEY_ID,
            aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
            region_name=config.S3_REGION,
            config=client_config,
        )
    return _client


def _put(prefix: str, data: bytes, content_type: str, ext: str) -> str | None:
    """Upload bytes under `prefix/` with a random key; return the object key, or
    None if storage is off / the upload failed."""
    if not _configured():
        logger.warning("S3 not configured; skipping %s upload", prefix)
        return None
    key = f"{prefix}/{uuid.uuid4().hex}.{ext}"
    try:
        _s3().put_object(
            Bucket=config.S3_BUCKET, Key=key, Body=data, ContentType=content_type
        )
        logger.info("Uploaded to s3://%s/%s", config.S3_BUCKET, key)
        return key
    except Exception as exc:
        logger.exception("Upload to %s failed: %s", prefix, exc)
        return None


def upload_audio(data: bytes, content_type: str = "audio/ogg", ext: str = "oga") -> str | None:
    """Upload voice audio bytes and return the object key, or None if off/failed."""
    return _put("voice", data, content_type, ext)


def upload_attachment(
    data: bytes, kind: str = "image", content_type: str = "application/octet-stream",
    ext: str = "bin",
) -> str | None:
    """Upload a note attachment (image/…) and return its object key, or None if
    storage is off / the upload failed. Keyed under attachments/{kind}/."""
    return _put(f"attachments/{kind}", data, content_type, ext)


def delete_object(key: str) -> bool:
    """Delete an object from the bucket (best-effort). Returns True on success.
    Used to clean up a note's media/audio when the note is deleted, so nothing is
    orphaned in storage."""
    if not key or not _configured():
        return False
    try:
        _s3().delete_object(Bucket=config.S3_BUCKET, Key=key)
        logger.info("Deleted s3://%s/%s", config.S3_BUCKET, key)
        return True
    except Exception as exc:
        logger.exception("Delete of %s failed: %s", key, exc)
        return False


def fetch_object(key: str) -> tuple[bytes, str | None] | None:
    """Download an object's bytes + content-type, so the API can proxy it to a
    client that can't reach the bucket directly. Returns (data, content_type), or
    None if storage is off / the object is missing."""
    if not key or not _configured():
        return None
    try:
        resp = _s3().get_object(Bucket=config.S3_BUCKET, Key=key)
        return resp["Body"].read(), resp.get("ContentType")
    except Exception as exc:
        logger.exception("Fetch of %s failed: %s", key, exc)
        return None


def presigned_url(key: str, ttl: int | None = None) -> str | None:
    """A short-lived signed GET URL for an object, so a client (the web-app
    carousel) can load it directly from the bucket without exposing credentials.
    Returns None if storage is off or signing fails."""
    if not key or not _configured():
        return None
    try:
        return _s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": config.S3_BUCKET, "Key": key},
            ExpiresIn=int(ttl or config.ATTACHMENT_URL_TTL_SECONDS),
        )
    except Exception as exc:
        logger.exception("Presigning %s failed: %s", key, exc)
        return None
