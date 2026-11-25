"""One-time load of the latest Mercedes CLE emissions CSV from S3
into dejf_claim_admin.SG_email_notifications_stag on the legacy PHP cluster.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, Optional

import boto3
import pymysql

LOGGER = logging.getLogger("load_s3_to_legacy")

DDL_PATH = Path(__file__).resolve().parent.parent / "sql" / "create_sg_email_notifications_stag.sql"
TARGET_SCHEMA = "dejf_claim_admin"
TARGET_TABLE = "SG_email_notifications_stag"

INSERT_COLUMNS = (
    "notification_type", "notification_subtype", "recipient", "notification_timestamp",
    "message_status", "message_action", "diagnosticCode", "original_timestamp",
    "messageId", "claim_id", "user_id", "claim_status", "reminder_type",
    "reminder_subject", "message_body", "url",
    "opened", "clicked", "bounced", "complaint",
)

BATCH_SIZE = 200


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def find_latest_s3_key(s3, bucket: str, prefix: str, file_prefix: str) -> dict:
    paginator = s3.get_paginator("list_objects_v2")
    latest = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".csv"):
                continue
            if file_prefix not in os.path.basename(key):
                continue
            if latest is None or obj["LastModified"] > latest["LastModified"]:
                latest = obj
    if latest is None:
        raise FileNotFoundError(
            f"No CSV matching '{file_prefix}' under s3://{bucket}/{prefix}"
        )
    return latest


def _nullify(value: str) -> Optional[str]:
    return value if value != "" else None


def _x_to_bool(value: str) -> int:
    return 1 if value.strip().upper() == "X" else 0


def _datetime_or_null(value: str) -> Optional[str]:
    # CSV already carries 'YYYY-MM-DD HH:MM:SS'; MySQL accepts it as DATETIME.
    return value if value else None


def transform(row: dict) -> tuple:
    return (
        "SES",                                  # notification_type (hardcoded)
        _nullify(row.get("notification_subtype", "")),
        _nullify(row.get("recipient", "")),
        _datetime_or_null(row.get("notification_timestamp", "")),
        _nullify(row.get("message_status", "")),
        _nullify(row.get("message_action", "")),
        _nullify(row.get("diagnosticCode", "")),
        _datetime_or_null(row.get("original_timestamp", "")),
        _nullify(row.get("messageId", "")),
        _nullify(row.get("claim_id", "")),
        _nullify(row.get("user_id", "")),
        _nullify(row.get("claim_status", "")),
        _nullify(row.get("reminder_type", "")),
        _nullify(row.get("reminder_subject", "")),
        _nullify(row.get("message_body", "")),
        _nullify(row.get("url", "")),
        _x_to_bool(row.get("opened", "")),
        _x_to_bool(row.get("clicked", "")),
        _x_to_bool(row.get("bounced", "")),
        _x_to_bool(row.get("complaint", "")),
    )


def iter_csv_rows(path: Path) -> Iterable[dict]:
    # CSV can have very large message_body fields; bump the field size limit.
    csv.field_size_limit(sys.maxsize)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def run_ddl(conn: pymysql.connections.Connection) -> None:
    ddl = DDL_PATH.read_text(encoding="utf-8")
    LOGGER.info("Applying DDL from %s", DDL_PATH)
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()


def count_rows(conn: pymysql.connections.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {TARGET_SCHEMA}.{TARGET_TABLE}")
        return cur.fetchone()[0]


def load_batches(conn: pymysql.connections.Connection, csv_path: Path) -> int:
    placeholders = ", ".join(["%s"] * len(INSERT_COLUMNS))
    col_list = ", ".join(INSERT_COLUMNS)
    sql = (
        f"INSERT INTO {TARGET_SCHEMA}.{TARGET_TABLE} ({col_list}) VALUES ({placeholders})"
    )

    batch: list[tuple] = []
    total = 0
    started = time.time()
    with conn.cursor() as cur:
        for row in iter_csv_rows(csv_path):
            batch.append(transform(row))
            if len(batch) >= BATCH_SIZE:
                cur.executemany(sql, batch)
                total += len(batch)
                batch.clear()
                if total % 2000 == 0:
                    elapsed = time.time() - started
                    LOGGER.info(
                        "inserted %d rows (%.1f rows/sec)",
                        total, total / elapsed if elapsed else 0,
                    )
        if batch:
            cur.executemany(sql, batch)
            total += len(batch)
    conn.commit()
    elapsed = time.time() - started
    LOGGER.info("load complete: %d rows in %.1fs", total, elapsed)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load latest matching CSV from S3 into the legacy staging table."
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append even if the target table already has rows (skip the one-time-load guard).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"].rstrip("/") + "/"
    file_prefix = os.environ["FILENAME_PREFIX"]
    region = os.environ.get("AWS_REGION", "eu-west-2")

    legacy_host = os.environ["LEGACY_DB_HOST"]
    legacy_port = int(os.environ.get("LEGACY_DB_PORT", "3306"))
    legacy_user = os.environ["LEGACY_DB_USER"]
    legacy_password = os.environ["LEGACY_DB_PASSWORD"]

    s3 = boto3.client("s3", region_name=region)
    latest = find_latest_s3_key(s3, bucket, prefix, file_prefix)
    LOGGER.info(
        "latest object: s3://%s/%s (%.1f MB, modified %s)",
        bucket, latest["Key"], latest["Size"] / 1_048_576,
        latest["LastModified"].isoformat(),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / Path(latest["Key"]).name
        LOGGER.info("downloading to %s", csv_path)
        s3.download_file(bucket, latest["Key"], str(csv_path))

        LOGGER.info(
            "connecting to %s@%s:%d", legacy_user, legacy_host, legacy_port,
        )
        conn = pymysql.connect(
            host=legacy_host,
            port=legacy_port,
            user=legacy_user,
            password=legacy_password,
            database=TARGET_SCHEMA,
            charset="utf8mb4",
            connect_timeout=10,
            read_timeout=600,
            write_timeout=600,
            autocommit=False,
        )
        try:
            run_ddl(conn)
            before = count_rows(conn)
            LOGGER.info("row count before load: %d", before)
            if before > 0 and not args.append:
                LOGGER.warning(
                    "target table already has %d rows; aborting to avoid duplicate "
                    "one-time load. Re-run with --append to add rows, or truncate it "
                    "manually if you want a clean reload.",
                    before,
                )
                return 2
            if before > 0 and args.append:
                LOGGER.info(
                    "target table has %d rows; --append set, adding new rows on top.",
                    before,
                )
            inserted = load_batches(conn, csv_path)
            after = count_rows(conn)
            LOGGER.info("row count after load : %d (delta %d)", after, after - before)
            if after - before != inserted:
                LOGGER.warning(
                    "inserted count (%d) != delta (%d)", inserted, after - before,
                )
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
