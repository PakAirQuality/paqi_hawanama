# ops schema migrations

These files create the `ops` schema used for ingestion run accounting, shared
provider quotas, leases, raw-payload provenance and stream checkpoints. They
never touch any table in `public` (`readings`, `stations`, `providers`, ...).

The application does **not** apply them. Apply by hand, in order, after review:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_schema/migrations/001_ops_ingestion.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_schema/migrations/002_ops_provenance.sql
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_schema/migrations/003_openaq_streams.sql
```

Each file is idempotent (`IF NOT EXISTS`) and wrapped in one transaction. If the
application's database role does not own the schema, uncomment the `GRANT`
lines at the end of each file and fill in the role first.

Deployment order matters: apply `001` before deploying the first ingestion-
hardening release, because the ingest service refuses to run unmetered when
`ops.provider_quota` is missing (`OPS_TABLES_REQUIRED=true`).
