"""Upload rendered slides to Cloudflare R2 and return public URLs.

This exists because **Meta's publish API fetches the image by URL** — it does
not accept a raw upload. So an image that only lives on disk in a Modal
container cannot be published at all, and R2 is not an optimisation here, it is
a hard dependency of the Facebook, Instagram and Pinterest paths.

The bucket's managed public URL had to be enabled explicitly: the S3 endpoint
returns `400 InvalidArgument: Authorization` to an unauthenticated GET, which is
what Meta would have received on every single post. Verified since — a fresh
object serves 200 unauthenticated from `R2_PUBLIC_BASE_URL`.

`r2.dev` is rate-limited and explicitly not for production traffic. It is fine
at this volume; a custom domain (`img.wizcodes.site`) is the upgrade when volume
justifies it.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

log = logging.getLogger("content_poster.r2")


class R2Error(RuntimeError):
    pass


def _client(config):
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=config.r2_bucket_endpoint,
        aws_access_key_id=config.r2_access_key_id,
        aws_secret_access_key=config.r2_secret_access_key,
        # R2 is S3-compatible but not S3. It has no regions, and the SDK's
        # default checksum behaviour has to be pinned or uploads intermittently
        # fail signature validation.
        region_name="auto",
        config=BotoConfig(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def upload(config, paths: list[Path], run_id: str) -> list[str]:
    """Upload images, return their public URLs in the same order.

    Order is load-bearing: a carousel's slides are published in list order, and
    a shuffled upload would publish a cover slide in the middle.
    """
    if not paths:
        return []
    if not config.has_image_hosting():
        raise R2Error("R2 is not fully configured; cannot publish an image by URL")

    client = _client(config)
    base = config.r2_public_base_url.rstrip("/")
    prefix = config.r2_key_prefix.strip("/")
    urls: list[str] = []

    for path in paths:
        key = f"{prefix}/{run_id}/{path.name}"
        content_type = mimetypes.guess_type(path.name)[0] or "image/png"
        try:
            client.upload_file(
                str(path),
                config.r2_bucket_name,
                key,
                ExtraArgs={
                    "ContentType": content_type,
                    # Meta may re-fetch; a long cache is free and reduces the
                    # chance of a rate-limited r2.dev miss during publishing.
                    "CacheControl": "public, max-age=31536000, immutable",
                },
            )
        except Exception as e:
            raise R2Error(f"upload failed for {path.name}: {e}") from e
        urls.append(f"{base}/{key}")

    log.info("uploaded %d image(s) to R2 under %s/%s/", len(urls), prefix, run_id)
    return urls


def verify_public(url: str, timeout: int = 20) -> bool:
    """Confirm the URL really is publicly readable before handing it to Meta.

    Worth one HEAD request: an image Meta cannot fetch fails the publish with an
    error that blames the image, not the bucket policy, and that is a long
    afternoon.
    """
    import requests

    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code == 200
    except Exception:
        return False
