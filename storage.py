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


def public_url(key: str | None) -> str | None:
    """Build a public URL for an object key, or None."""
    if not key:
        return None
    if config.S3_PUBLIC_BASE_URL:
        return f"{config.S3_PUBLIC_BASE_URL.rstrip('/')}/{key}"
    if config.S3_ENDPOINT_URL:
        return f"{config.S3_ENDPOINT_URL.rstrip('/')}/{config.S3_BUCKET}/{key}"
    return f"https://{config.S3_BUCKET}.s3.{config.S3_REGION}.amazonaws.com/{key}"


def upload_audio(data: bytes, content_type: str = "audio/ogg", ext: str = "oga") -> str | None:
    """Upload audio bytes and return the object key, or None if storage is off/failed."""
    if not _configured():
        logger.warning("S3 not configured; skipping audio upload")
        return None
    key = f"voice/{uuid.uuid4().hex}.{ext}"
    try:
        _s3().put_object(
            Bucket=config.S3_BUCKET, Key=key, Body=data, ContentType=content_type
        )
        logger.info("Uploaded voice audio to s3://%s/%s", config.S3_BUCKET, key)
        return key
    except Exception as exc:
        logger.exception("Audio upload failed: %s", exc)
        return None
