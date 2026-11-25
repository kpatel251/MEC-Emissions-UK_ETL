"""Export one Mercedes campaign from Sendy (deduped SQL in sql/) to a local CSV,
mapping the Sendy 00ID (custom_fields) to the portal claim_id via Email_list_mer.csv.

Usage:
    python scripts/export_campaign_with_claim.py sql/mercedes_cle_emissions_dedup_937_105.sql
Output: mercedes_cle_emissions_dedup_<mc>_<list>_with_claim_<UTC ts>.csv in the project root.
Unmapped rows (internal / counsel seed addresses) keep a blank claim_id.
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from load_s3_to_legacy import load_dotenv  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    sql_path = Path(sys.argv[1])
    load_dotenv(ROOT / ".env")

    with open(ROOT / "Email_list_mer.csv", encoding="utf-8-sig") as f:
        id_map = {r["User_id"].strip(): r["claim_id"].strip() for r in csv.DictReader(f)}

    conn = pymysql.connect(
        host=os.environ["DB_HOST"], user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], database=os.environ.get("DB_NAME", "sendy"),
        port=int(os.environ.get("DB_PORT", "3306")), charset="utf8mb4",
        connect_timeout=10, read_timeout=600,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / f"{sql_path.stem}_with_claim_{ts}.csv"
    total = 0
    unmapped = []
    with conn.cursor() as cur, open(out, "w", newline="", encoding="utf-8") as fh:
        cur.execute(sql_path.read_text(encoding="utf-8"), ("1970-01-01 00:00:00",))
        cols = [d[0] for d in cur.description]
        writer = csv.writer(fh)
        writer.writerow(cols)
        ci, ri = cols.index("claim_id"), cols.index("recipient")
        for row in cur.fetchall():
            row = list(row)
            oo = str(row[ci]).strip() if row[ci] is not None else ""
            if oo in id_map:
                row[ci] = id_map[oo]
            else:
                row[ci] = ""
                unmapped.append((row[ri], oo))
            writer.writerow(row)
            total += 1
    conn.close()
    print(f"rows {total}, unmapped {len(unmapped)} -> {out}")
    for email, oo in unmapped:
        print(f"  unmapped: {email} (00ID {oo})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
