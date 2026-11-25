"""Find the most recent CSV under the export prefix and show a sample."""
from __future__ import annotations

import csv
import io
import os
from pathlib import Path

import boto3


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"].rstrip("/") + "/"
    file_prefix = os.environ["FILENAME_PREFIX"]
    region = os.environ.get("AWS_REGION", "eu-west-2")

    s3 = boto3.client("s3", region_name=region)

    paginator = s3.get_paginator("list_objects_v2")
    latest = None
    count = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".csv"):
                continue
            if file_prefix not in os.path.basename(key):
                continue
            count += 1
            if latest is None or obj["LastModified"] > latest["LastModified"]:
                latest = obj

    if latest is None:
        print(f"No CSV matching '{file_prefix}' under s3://{bucket}/{prefix}")
        return

    print(f"Matching files under s3://{bucket}/{prefix}: {count}")
    print(f"Latest key     : {latest['Key']}")
    print(f"LastModified   : {latest['LastModified'].isoformat()}")
    print(f"Size (bytes)   : {latest['Size']}")

    obj = s3.get_object(Bucket=bucket, Key=latest["Key"])
    body = obj["Body"].read().decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(body))
    rows = list(reader)
    print(f"Total rows (incl header): {len(rows)}")
    if not rows:
        return
    headers = rows[0]
    print(f"Columns ({len(headers)}):")
    for h in headers:
        print(f"  - {h}")

    print("\nFirst 3 data rows:")
    for r in rows[1:4]:
        for h, v in zip(headers, r):
            preview = v if len(v) <= 80 else v[:77] + "..."
            print(f"  {h:<24} = {preview!r}")
        print("  " + "-" * 40)


if __name__ == "__main__":
    main()
