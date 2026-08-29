# Data in this repository

This is the application code for [Hawanama](https://hawanama.org), PAQI's air-quality
platform for Pakistan. The code is MIT-licensed (see `LICENSE`). The data it runs on is
mostly **not** in this repository, deliberately.

## What is included

- **Administrative boundaries** (`pak_boundaries/`, and copies under `apps/*/public/` and
  `apps/api/data/`): geoBoundaries (Runfola et al., 2020), CC-BY-4.0.
  Attribution: "geoBoundaries — https://www.geoboundaries.org".
- **Brick-kiln inventory** (`apps/dashboard-frontend/public/brick_kilns.geojson`): ~10,600 kilns
  with district, fuel, capacity and estimated PM2.5/PM10/SO2 emissions. Coordinates are rounded
  to 0.1° (about 10 km) — it locates kilns to a district, not a site — and it carries no owner
  information. It is served by the public dashboard already.
- **City station-count polygons** (`apps/web-next/public/city_station_polygons.geojson`):
  derived, aggregated shapes carrying only a city name, a station *count* and an area. No
  station locations.

## What is excluded, and why

- **Station manifests and raw provider responses** (`apps/*/artifacts/`,
  `apps/worker/tasks/raw_api_data/`, `apps/worker/tasks/city_raw_api_data/`). These hold
  per-station coordinates and owner-supplied station names from the IQAir/AirVisual network,
  a number of which are private residences or businesses. They are excluded for the privacy
  of contributors and because redistributing provider station data is outside the provider's
  API terms. The pipeline regenerates them at runtime from the provider API into the
  configured storage bucket.
- **Partner monitor host lists** (`external_data/`): names of the institutions hosting AirGradient
  and Urban Unit monitors. No coordinates, but not needed to run the code, so kept out.
- **Ground observations.** The PAQI ground-station PM2.5 archive is not public; see the
  `DATA.md` in `PakAirQuality/pak_quality_estimation` for the terms under which a derived,
  anonymised validation table is available.
- **Model artefacts, features, predictions and forecasts** live in GCS buckets configured
  through the `OPS_*_BUCKET` environment variables, not in git.
- **Credentials.** Every provider key (IQAir, OpenAQ, NASA, Mapbox, Gemini, Twitter) and the
  API secrets are read from the environment. There are no defaults. Copy `.env.example` where
  present and fill it locally; never commit a `.env`.

## Running it

The `docker-compose.yml` passwords are for a local development stack only. Production
deployment uses Google Secret Manager via `cloudbuild.yaml` (`--set-secrets`).
