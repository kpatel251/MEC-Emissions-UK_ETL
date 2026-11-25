"""Quick connectivity check for the legacy PHP MySQL cluster."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pymysql


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    host = os.environ["LEGACY_DB_HOST"]
    port = int(os.environ.get("LEGACY_DB_PORT", "3306"))
    user = os.environ["LEGACY_DB_USER"]
    password = os.environ["LEGACY_DB_PASSWORD"]
    database = os.environ.get("LEGACY_DB_NAME") or None

    print(f"Connecting to {user}@{host}:{port} (db={database or '<none>'})...")
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=10,
        read_timeout=30,
        charset="utf8mb4",
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), CURRENT_USER(), DATABASE()")
            version, current_user, current_db = cur.fetchone()
            print(f"  server_version : {version}")
            print(f"  current_user   : {current_user}")
            print(f"  current_db     : {current_db}")

            cur.execute("SHOW DATABASES")
            dbs = [row[0] for row in cur.fetchall()]
            print(f"  databases ({len(dbs)}): {', '.join(dbs)}")
    finally:
        conn.close()
    print("OK - connection successful.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
