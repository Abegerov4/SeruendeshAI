"""Operator-only S3 photo publishing. No public upload API or remote URL fetch."""
import argparse
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import time
import warnings

MAX_BYTES = 12 * 1024 * 1024


def client():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT_URL"],
                        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                      connect_timeout=5, read_timeout=30,
                                      retries={"max_attempts": 3}))


def wait_ready(s3, attempts=60, pause=2):
    """Wait for a signed S3 request, not just an open TCP port."""
    from botocore.exceptions import ClientError, ConnectionError, HTTPClientError
    for attempt in range(attempts):
        try:
            s3.list_buckets()
            return
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) < 500:
                raise  # Wrong credentials/configuration must fail closed.
            if attempt == attempts - 1:
                raise
        except (ConnectionError, HTTPClientError):
            if attempt == attempts - 1:
                raise
        time.sleep(pause)


def initialize(s3, bucket):
    from botocore.exceptions import ClientError
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
        region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        options = {} if region == "us-east-1" else {"CreateBucketConfiguration": {"LocationConstraint": region}}
        s3.create_bucket(Bucket=bucket, **options)
    # Only public card images: no anonymous listing, writes or other prefixes.
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps({
        "Version": "2012-10-17", "Statement": [{
            "Effect": "Allow", "Principal": "*",
            "Action": ["s3:GetObject"], "Resource": [f"arn:aws:s3:::{bucket}/cards/*"]}]}))


def prepare_image(path):
    from PIL import Image, ImageOps
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Photo exceeds the 12 MiB upload limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as original:
            if original.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Only JPEG, PNG and WebP photos are accepted")
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1920, 1920))
            out = BytesIO()
            # Re-encode without EXIF/GPS or arbitrary input metadata.
            image.save(out, format="JPEG", quality=85)
            return out.getvalue(), image.width, image.height


@contextmanager
def locked_manifest(path):
    # The tool runs in Linux containers; serialize writers across docker runs.
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def publish(s3, bucket, args, manifest):
    payload, width, height = prepare_image(Path(args.file))
    key = f"cards/{hashlib.sha256(payload).hexdigest()}.jpg"
    with locked_manifest(manifest):
        entries = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
        s3.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="image/jpeg",
                      CacheControl="public, max-age=31536000, immutable")
        entries[args.poi_id] = {"key": key, "width": width, "height": height,
                                "author": args.author, "license": args.license,
                                "source": args.source, "page": args.page}
        # Upload first, then atomically publish the reference. Failed uploads
        # leave the last working card intact; readers never see half-written JSON.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=manifest.parent,
                                         delete=False) as out:
            temporary = Path(out.name)
            json.dump(entries, out, ensure_ascii=False, indent=2)
        try:
            temporary.replace(manifest)
        finally:
            temporary.unlink(missing_ok=True)
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    upload = commands.add_parser("upload")
    upload.add_argument("--poi-id", required=True, help="Exact ID in the active POI snapshot")
    upload.add_argument("--file", required=True)
    upload.add_argument("--author", required=True)
    upload.add_argument("--license", required=True)
    upload.add_argument("--source", default="Team upload")
    upload.add_argument("--page", help="Source or attribution page URL")
    args = parser.parse_args()
    s3, bucket = client(), os.environ["S3_BUCKET"]
    if args.command == "init":
        wait_ready(s3)
        initialize(s3, bucket)
        print("Card photo bucket ready")
    else:
        key = publish(s3, bucket, args, Path(os.environ["CARD_PHOTOS_FILE"]))
        print(f"Published {args.poi_id}: {key}. Restart the app to reload cards.")


if __name__ == "__main__":
    main()
