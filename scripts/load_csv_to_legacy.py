"""Load a local *_with_claim_*.csv into dejf_claim_admin.SG_email_notifications_stag
(the PHP portal table). Refuses to run if that campaign's subject is already loaded.

Usage:
    python scripts/load_csv_to_legacy.py mercedes_cle_emissions_dedup_937_105_with_claim_<ts>.csv
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from load_s3_to_legacy import INSERT_COLUMNS, load_dotenv, transform  # noqa: E402

TABLE = "dejf_claim_admin.SG_email_notifications_stag"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    load_dotenv(ROOT / ".env")
    csv.field_size_limit(sys.maxsize)
    with open(sys.argv[1], encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    subjects = {r["reminder_subject"] for r in rows}
    if len(subjects) != 1:
        print(f"ABORT: expected one campaign subject, got {subjects}")
        return 2
    subject = subjects.pop()
    print(f"rows {len(rows)}, blank claim_id {sum(not r['claim_id'] for r in rows)}, subject {subject!r}")

    conn = pymysql.connect(
        host=os.environ["LEGACY_DB_HOST"], user=os.environ["LEGACY_DB_USER"],
        password=os.environ["LEGACY_DB_PASSWORD"], port=int(os.environ.get("LEGACY_DB_PORT", "3306")),
        database="dejf_claim_admin", charset="utf8mb4", connect_timeout=10,
        read_timeout=900, write_timeout=900, autocommit=False,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {TABLE} WHERE reminder_subject=%s", (subject,))
            existing = cur.fetchone()[0]
            if existing:
                print(f"ABORT: {existing} rows already loaded for this subject")
                return 2
            sql = (f"INSERT INTO {TABLE} ({', '.join(INSERT_COLUMNS)}) "
                   f"VALUES ({', '.join(['%s'] * len(INSERT_COLUMNS))})")
            data = [transform(r) for r in rows]
            for i in range(0, len(data), 500):
                cur.executemany(sql, data[i:i + 500])
            conn.commit()
            cur.execute(
                f"SELECT COUNT(*), SUM(claim_id IS NULL), SUM(opened), SUM(clicked), SUM(bounced), "
                f"SUM(complaint), MIN(id), MAX(id) FROM {TABLE} WHERE reminder_subject=%s",
                (subject,),
            )
            print("loaded (count, null_claim, opened, clicked, bounced, complaint, min_id, max_id):",
                  cur.fetchone())
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
