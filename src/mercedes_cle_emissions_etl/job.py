from __future__ import annotations

import argparse
import csv
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3
import pymysql
from botocore.exceptions import ClientError

from .config import JobConfig

LOGGER = logging.getLogger(__name__)

EPOCH_WATERMARK = "1970-01-01 00:00:00"
WATERMARK_FORMAT = "%Y-%m-%d %H:%M:%S"


def _connect(config: JobConfig) -> pymysql.connections.Connection:
    LOGGER.info("Connecting to %s:%s/%s", config.db_host, config.db_port, config.db_name)
    return pymysql.connect(
        host=config.db_host,
        user=config.db_user,
        password=config.db_password,
        database=config.db_name,
        port=config.db_port,
        cursorclass=pymysql.cursors.SSCursor,
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=300,
        write_timeout=300,
    )


def read_watermark(s3_client, bucket: str, key: str) -> str:
    """Fetch the high-water-mark from S3, or epoch if it doesn't exist yet."""
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            LOGGER.info(
                "No watermark at s3://%s/%s; defaulting to %s (full export)",
                bucket, key, EPOCH_WATERMARK,
            )
            return EPOCH_WATERMARK
        raise
    payload = json.loads(obj["Body"].read().decode("utf-8"))
    value = payload.get("max_notification_timestamp", EPOCH_WATERMARK)
    LOGGER.info("Loaded watermark from s3://%s/%s: %s", bucket, key, value)
    return value


def write_watermark(s3_client, bucket: str, key: str, value: str) -> None:
    body = json.dumps(
        {"max_notification_timestamp": value, "updated_at": datetime.now(tz=timezone.utc).isoformat()},
        indent=2,
    ).encode("utf-8")
    s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json")
    LOGGER.info("Wrote watermark to s3://%s/%s: %s", bucket, key, value)


def stream_query_to_csv(
    connection: pymysql.connections.Connection,
    sql_text: str,
    destination: Path,
    since: str,
) -> tuple[int, Optional[datetime]]:
    """Stream the query result set to CSV and return (row_count, max_notification_timestamp)."""
    row_count = 0
    max_ts: Optional[datetime] = None
    with connection.cursor() as cursor, destination.open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        cursor.execute(sql_text, (since,))
        headers = [description[0] for description in cursor.description]
        ts_idx = headers.index("notification_timestamp")
        writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)

        for row in cursor:
            writer.writerow(row)
            row_count += 1
            ts = row[ts_idx]
            if ts is not None and (max_ts is None or ts > max_ts):
                max_ts = ts
    return row_count, max_ts


def run_export(
    config: JobConfig,
    *,
    sql_override: Optional[str] = None,
    since_override: Optional[str] = None,
) -> dict:
    """
    Run an incremental ETL cycle:
      1. Read watermark from S3 (or use --since override).
      2. Run SQL with `e.date_updated > :since`.
      3. Stream results to a temp CSV and upload to S3.
      4. On success, write the new watermark = max(notification_timestamp).
    """
    sql_text = sql_override or config.sql_path.read_text(encoding="utf-8")
    s3_client = boto3.client("s3", region_name=config.aws_region)

    since = since_override or read_watermark(
        s3_client, config.s3_bucket, config.watermark_key
    )

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{config.filename_prefix}_{timestamp}.csv"
    s3_key = f"{config.normalized_prefix}{filename}"

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / filename
        LOGGER.info("Writing query results to %s (since=%s)", csv_path, since)
        with _connect(config) as connection:
            row_count, max_ts = stream_query_to_csv(connection, sql_text, csv_path, since)

        if row_count == 0:
            LOGGER.info("No new rows since %s; skipping upload and watermark update.", since)
            return {
                "rows_exported": 0,
                "s3_location": None,
                "filename": None,
                "since": since,
                "new_watermark": since,
            }

        LOGGER.info(
            "Uploading %s rows to s3://%s/%s", row_count, config.s3_bucket, s3_key
        )
        s3_client.upload_file(str(csv_path), config.s3_bucket, s3_key)

    new_watermark = max_ts.strftime(WATERMARK_FORMAT) if max_ts else since
    if max_ts:
        write_watermark(s3_client, config.s3_bucket, config.watermark_key, new_watermark)
    else:
        LOGGER.warning(
            "Exported %s rows but max(notification_timestamp) is NULL; watermark unchanged.",
            row_count,
        )

    return {
        "rows_exported": row_count,
        "s3_location": f"s3://{config.s3_bucket}/{s3_key}",
        "filename": filename,
        "since": since,
        "new_watermark": new_watermark,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export Mercedes CLE emissions report to S3 (incremental)."
    )
    parser.add_argument(
        "--sql-path",
        type=Path,
        default=None,
        help="Override path to SQL file (defaults to bundled query).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help=(
            "Override watermark for this run (format 'YYYY-MM-DD HH:MM:SS'). "
            "If omitted, the watermark is read from S3."
        ),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        help="Runtime log level.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    config = JobConfig.from_env(sql_path=args.sql_path)
    result = run_export(config, since_override=args.since)
    LOGGER.info(
        "Export complete - %s rows (since=%s, new_watermark=%s) -> %s",
        result["rows_exported"],
        result["since"],
        result["new_watermark"],
        result["s3_location"] or "<no upload>",
    )


if __name__ == "__main__":
    main()
