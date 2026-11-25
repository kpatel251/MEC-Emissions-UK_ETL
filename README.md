# Mercedes CLE Emissions ETL

This standalone project runs the Mercedes CLE emissions query against the Sendy MySQL cluster and writes a timestamped CSV file to Amazon S3. It is designed to run locally for validation and as a Glue Python Shell job for daily scheduling.

## Layout

```
mercedes_cle_emissions_etl/
├── README.md
├── requirements.txt
├── sql/
│   └── mercedes_cle_emissions.sql
└── src/
    └── mercedes_cle_emissions_etl/
        ├── __init__.py
        ├── config.py
        └── job.py
```

- `config.py` loads runtime settings from environment variables (DB/S3/filename/region).
- `job.py` connects to MySQL, streams the SQL result set to CSV, and uploads it to S3.
- `sql/mercedes_cle_emissions.sql` holds the query so it can be edited without changing code.

## Environment variables

| Name | Description | Default |
| --- | --- | --- |
| `DB_HOST` | MySQL endpoint | required (Sendy read replica endpoint) |
| `DB_PORT` | MySQL port | `3306` |
| `DB_NAME` | Database/schema | `sendy` |
| `DB_USER` | Username | required |
| `DB_PASSWORD` | Password (required) | — |
| `S3_BUCKET` | Destination bucket | required |
| `S3_PREFIX` | Key prefix | `redshift-exports/UK/` |
| `FILENAME_PREFIX` | CSV basename | `mercedes_cle_emissions` |
| `AWS_REGION` | S3 region | `eu-west-2` |

## Local run

```bash
cd mercedes_cle_emissions_etl
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the values
export AWS_REGION=eu-west-2
PYTHONPATH=src python -m mercedes_cle_emissions_etl.job --log-level DEBUG
```

Make sure you are on the VPN (`ANG-UK.ovpn`) so the RDS hostname resolves before running locally.

## Glue packaging

```bash
cd mercedes_cle_emissions_etl
rm -rf build/glue && mkdir -p build/glue/python
pip install --target build/glue/python -r requirements.txt
cp -R src build/glue/python/
cp -R sql build/glue/python/
cd build/glue && zip -r mercedes_cle_emissions_job.zip python
aws s3 cp mercedes_cle_emissions_job.zip s3://<artifacts-bucket>/jobs/
```

Glue job (Python Shell 3.10):
1. Point script path to the uploaded ZIP and pass the same ZIP in `--extra-py-files`.
2. Set job parameters like `--ENV_DB_PASSWORD=<secret>` so the script receives environment variables.
3. Attach an IAM role that can reach the RDS cluster (VPC/subnet/SG), read secrets, and write to the destination S3 bucket.

## Scheduling

- **Glue Trigger**: Add a scheduled trigger with cron `0 2 * * ? *` for 02:00 UTC daily.
- **EventBridge**: Create a rule with the same cron targeting the Glue job, useful if you manage schedules centrally.

## Monitoring

- CloudWatch logs for the Glue job capture all logging output.
- Add CloudWatch alarms or EventBridge state-change rules so failures notify your team.
- S3 keys are timestamped (`<prefix>/mercedes_cle_emissions_YYYYMMDDTHHMMSSZ.csv`) for easy downstream processing.

Update the SQL or configuration as needed, rebuild the ZIP, and redeploy to Glue whenever requirements change.

## New campaign → PHP portal (manual runbook)

Each time a new Mercedes Emissions UK email campaign goes out (Jira ADT-xxxx), its results are loaded into the PHP portal table `dejf_claim_admin.SG_email_notifications_stag` on the legacy cluster (connection details in `.env`, see `LEGACY_DB_*`).

1. **Find the campaign in Sendy**: `sendy.campaigns` where `case_name = 'Mercedes CLE Emissions'` → note `master_campaign_id`. Then find the live list from `campaign_events_results` → `subscribers.list` (skip the small test-send list).
2. **Copy the dedup SQL** from the last campaign, e.g. `sql/mercedes_cle_emissions_dedup_937_105.sql`, and change the master campaign and list IDs.
3. **Export with claim_id mapping** (needs VPN + `Email_list_mer.csv`, not in git because it contains PII):
   `.venv/bin/python scripts/export_campaign_with_claim.py sql/mercedes_cle_emissions_dedup_<mc>_<list>.sql`
   Only internal/counsel seed addresses should come out unmapped. They load with a NULL claim_id.
4. **Load into the portal**:
   `.venv/bin/python scripts/load_csv_to_legacy.py mercedes_cle_emissions_dedup_<mc>_<list>_with_claim_<ts>.csv`
   It stops if that campaign's subject is already loaded.

| Campaign | Master campaign / list | Loaded |
| --- | --- | --- |
| July 2026 | 924 / 61+63 | 2026-07-13 |
| September 2026 (Appeal update) | 933 / 87 | 2026-09-30 |
| Nov 2026 Appeal & Quantum Trial (ADT-3640) | 937 / 105 | 2026-11-25 (ids 62249–74577) |
