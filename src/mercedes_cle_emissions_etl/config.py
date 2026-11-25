from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Default SQL query path (relative to the installed package)
_DEFAULT_SQL_PATH = Path(__file__).parent.parent.parent / "sql" / "mercedes_cle_emissions.sql"


@dataclass(frozen=True)
class JobConfig:
    # Database
    db_host: str
    db_port: int
    db_name: str
    db_user: str
    db_password: str

    # S3
    s3_bucket: str
    s3_prefix: str
    filename_prefix: str
    aws_region: str
    watermark_key: str

    # SQL
    sql_path: Path

    @property
    def normalized_prefix(self) -> str:
        """Ensure the S3 prefix ends with a slash."""
        return self.s3_prefix.rstrip("/") + "/"

    @classmethod
    def from_env(cls, sql_path: Optional[Path] = None) -> "JobConfig":
        """
        Build a JobConfig from environment variables.

        Required:
            DB_HOST, DB_USER, DB_PASSWORD, S3_BUCKET

        Optional (all have sensible defaults):
            DB_PORT, DB_NAME, S3_PREFIX, FILENAME_PREFIX, AWS_REGION
        """
        missing = [
            name for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "S3_BUCKET")
            if not os.environ.get(name)
        ]
        if missing:
            raise EnvironmentError(
                f"Required environment variable(s) not set: {', '.join(missing)}"
            )

        resolved_sql_path = sql_path or _DEFAULT_SQL_PATH
        if not resolved_sql_path.exists():
            raise FileNotFoundError(
                f"SQL file not found: {resolved_sql_path}. "
                "Pass --sql-path to specify an alternative location."
            )

        s3_prefix = os.environ.get("S3_PREFIX", "redshift-exports/UK/")
        default_watermark_key = s3_prefix.rstrip("/") + "/_watermark.json"

        return cls(
            db_host=os.environ["DB_HOST"],
            db_port=int(os.environ.get("DB_PORT", "3306")),
            db_name=os.environ.get("DB_NAME", "sendy"),
            db_user=os.environ["DB_USER"],
            db_password=os.environ["DB_PASSWORD"],
            s3_bucket=os.environ["S3_BUCKET"],
            s3_prefix=s3_prefix,
            filename_prefix=os.environ.get("FILENAME_PREFIX", "mercedes_cle_emissions"),
            aws_region=os.environ.get("AWS_REGION", "eu-west-2"),
            watermark_key=os.environ.get("WATERMARK_KEY", default_watermark_key),
            sql_path=resolved_sql_path,
        )
