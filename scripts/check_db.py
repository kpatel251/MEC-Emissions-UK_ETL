from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pymysql


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def test_connection() -> None:
    host = os.environ.get("DB_HOST")
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    database = os.environ.get("DB_NAME", "sendy")
    port = int(os.environ.get("DB_PORT", "3306"))

    missing = [
        name
        for name, value in (
            ("DB_HOST", host),
            ("DB_USER", user),
            ("DB_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")

    print(f"Connecting to {host}:{port}/{database} as {user}...")
    connection = pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
        connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            print(f"MySQL connection OK. SELECT 1 => {row}")
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check MySQL connectivity for this ETL.")
    parser.add_argument(
        "--dotenv",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
        help="Path to .env file (default: project root .env)",
    )
    args = parser.parse_args()

    load_dotenv(args.dotenv)

    try:
        test_connection()
        return 0
    except Exception as exc:
        print(f"Connection FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
