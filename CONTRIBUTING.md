# Contributing to Hawanama

## Setup

The repo works on macOS, Linux and Windows. You need Python 3.11 and Node 22 or newer.

### API

```bash
cd apps/api
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

To run the tests you need no database, network or secrets, only placeholder settings:

```bash
export POSTGRES_SERVER=localhost POSTGRES_USER=test POSTGRES_PASSWORD=test POSTGRES_DB=test POSTGRES_PORT=5432
python -m pytest -m "not live"
```

`live` tests call the real Gemini API and need `GEMINI_API_KEY`. CI skips them.

Running the API itself needs real credentials. Keep any `.env` outside `apps/`: those files are excluded from Cloud Build uploads and Docker images on purpose.

### Dashboard (`apps/dashboard-frontend`)

The dashboard has no dev proxy, so point it at the API. Create `apps/dashboard-frontend/.env.development`:

```
NEXT_PUBLIC_API_URL=https://hawanama-152782825429.asia-south1.run.app
```

Then:

```bash
npm install
npm run dev    # http://localhost:3001
```

### Public website (`apps/web-next`)

```bash
npm install
npm run dev    # http://localhost:3000
```

In development, `/api/**` is proxied to the production API.

Both frontends need `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` in `.env.local` to draw maps. Mapbox tokens are restricted by domain, so ask a maintainer for one that allows localhost.

## Making a change

1. Branch from `main`.
2. Open a pull request. Direct pushes to `main` are blocked.
3. Merge once CI is green.

| Check | What it does |
|---|---|
| `api-tests` | Runs `pytest -m "not live"` |
| `docker-build` | Builds the API image |
| `dashboard-build`, `web-build` | Build each frontend |
| `repo-checks` | Rejects tracked files that match `.gitignore`, and `rm` in npm scripts |
| `windows-checkout` | Checks out the repo on Windows |

Use your GitHub noreply address for commits (`git config user.email`), because this repo is public and commit emails are visible to everyone.

## What stays out of the repo

- **Secrets.** They live in Google Secret Manager. GitHub rejects known token formats on push, but don't rely on that.
- **Generated output.** Manifests, run artifacts and build files belong in GCS or `.gitignore`.
- **Filenames Windows can't create.** No `:`, `<`, `>`, `"`, `|`, `?` or `*`. Timestamps in paths are the usual cause.

`apps/dashboard-frontend/src/data/station-ids.json` and `apps/web-next/src/static/*.json` are committed snapshots that `npm run build` refreshes. Leave those local changes out of your commits unless updating them is the point of your PR.

## Database rules

- Never alter the protected tables, enums or extensions: `readings`, `stations`, `cities`, `states`, `countries`, `providers`, `scope_type`, `forecast_kind`, `pollutant_code`, TimescaleDB, PostGIS and pg_trgm. If the API and database disagree, change the application code.
- New tables go in the `ops` schema as a numbered file in `db_schema/migrations/`. The application doesn't apply these, so a maintainer applies them by hand. See [the migrations README](db_schema/migrations/README.md).
- Apply migrations and `infra/` changes **before** merging the code that needs them.

## Deployment

| Target | Lives at | Deployed from |
|---|---|---|
| API (`hawanama`, `hawanama-ingest`, `hawanama-bam`) | Cloud Run, `hawanama-2` | `cloudbuild.yaml` |
| Dashboard | https://hawanama.org (Firebase site `hawanama-2`) | `apps/dashboard-frontend` |
| Public website | https://hawanama-dashboard.web.app (Firebase site `hawanama-dashboard`) | `apps/web-next` |

Never deploy `apps/web-next` to Firebase site `hawanama-2`: that site owns hawanama.org.

To confirm which revision is live, read `provenance.git_sha` from `/api/v1/health/`.

### Rollback

- **API:** send traffic back to the previous revision:
  ```bash
  gcloud run services update-traffic hawanama --to-revisions=REVISION=100 \
    --region asia-south1 --project hawanama-2
  ```
- **Frontends:** roll back to the previous release under Hosting in the Firebase console.
