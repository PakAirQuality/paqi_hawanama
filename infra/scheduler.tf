terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = "hawanama-2"
  region  = "asia-south1"
}

# IAM Service Account for Cloud Scheduler
resource "google_service_account" "scheduler_invoker" {
  account_id   = "scheduler-invoker"
  display_name = "Cloud Scheduler Invoker"
  description  = "Service account for Cloud Scheduler to invoke Cloud Run services"
}

# Grant the service account permission to invoke the public API (kept for any
# scheduler that targets hawanama; harmless if all jobs migrate to ingest).
resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  project  = "hawanama-2"
  location = "asia-south1"
  service  = "hawanama"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

# Grant the service account permission to invoke the ingestion worker.
# All scheduled jobs now POST to hawanama-ingest so they don't share resources
# with the public read API.
resource "google_cloud_run_service_iam_member" "scheduler_invoker_ingest" {
  project  = "hawanama-2"
  location = "asia-south1"
  service  = "hawanama-ingest"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

# Base URL for all scheduled task invocations. Switching this single locals
# value moves every scheduler job between services.
locals {
  ingest_base_url = "https://hawanama-ingest-152782825429.asia-south1.run.app"
}

# 1. Station Discovery - Twice Daily (2:00 AM and 2:00 PM UTC)
resource "google_cloud_scheduler_job" "station_discovery_2am" {
  name        = "station-discovery-2am"
  description = "Station discovery at 2:00 AM UTC (7:00 AM PKT)"
  schedule    = "0 2 * * *"  # 2:00 AM UTC
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/discover"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 3
    max_retry_duration = "3600s"  # 1 hour max retry duration
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

resource "google_cloud_scheduler_job" "station_discovery_2pm" {
  name        = "station-discovery-2pm"
  description = "Station discovery at 2:00 PM UTC (7:00 PM PKT)"
  schedule    = "0 14 * * *"  # 2:00 PM UTC
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/discover"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 3
    max_retry_duration = "3600s"
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# 2. Station Ingestion - Hourly at :15
resource "google_cloud_scheduler_job" "station_ingestion" {
  name        = "station-ingestion-hourly"
  description = "Station data ingestion every hour at :15"
  schedule    = "15 * * * *"  # Every hour at :15
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/ingest-stations"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "1800s"  # 30 minutes max retry duration
    min_backoff_duration = "30s"
    max_backoff_duration = "120s"
  }
}

# 3. City Ingestion - Hourly at :07
resource "google_cloud_scheduler_job" "city_ingestion" {
  name        = "city-ingestion-hourly"
  description = "City data ingestion every hour at :07"
  schedule    = "7 * * * *"  # Every hour at :07
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/ingest-cities"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "1800s"  # 30 minutes max retry duration
    min_backoff_duration = "30s"
    max_backoff_duration = "120s"
  }
}

# Hawanama Bot - Smart Budget Model (500 posts/month)
# Base Schedule: Data-only + LLM posts at fixed times (~330/month)
# Smart Triggers: Category changes, volatility, hotspots, airpocalypse (~170/month)

resource "google_cloud_scheduler_job" "hawanama_bot_hourly" {
  name        = "hawanama-bot-execution"
  description = "Hourly Hawanama Bot with Smart Budget Model - LLM + Twitter integration"
  schedule    = "30 * * * *"  # Every hour at :30 (after data ingestion at :15)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/bot/execute"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    body = base64encode(jsonencode({
      dry_run = false
    }))
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "1800s"  # 30 minutes max retry duration
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# Emergency Hawanama Bot Test (manual trigger via gcloud)
resource "google_cloud_scheduler_job" "hawanama_bot_test" {
  name        = "hawanama-bot-test"
  description = "Test Hawanama Bot execution (paused by default) - dry run mode"
  schedule    = "0 0 1 1 *"  # January 1st (effectively disabled)
  time_zone   = "UTC"
  paused      = true  # Start in paused state

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/bot/execute"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    body = base64encode(jsonencode({
      dry_run = true,
      force_post = true
    }))
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 1
    max_retry_duration = "1800s"  # 30 minutes max retry duration
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# 4. Punjab EPA Ingestion - Every hour at :45 (offset from main ingestion)
resource "google_cloud_scheduler_job" "punjab_epa_ingestion" {
  name        = "punjab-epa-ingestion"
  description = "Punjab EPA data ingestion every hour at :45"
  schedule    = "45 * * * *"  # Every hour at :45 (1:45, 2:45, 3:45, etc.)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/punjab/ingest/hourly"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "1800s"  # 30 minutes max retry duration
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# 4b. FIRMS Fire Data Ingestion - every 3 hours (VIIRS overpasses ~08 and ~20 UTC; FIRMS NRT latency ≤3 h)
resource "google_cloud_scheduler_job" "firms_fire_ingest" {
  name        = "firms-fire-ingest"
  description = "FIRMS VIIRS (NOAA-20/21, SNPP until 2026-11-01) fire detections, last 3 UTC days re-keyed to Pakistan days, every 3 h; recorded as ingest-fires, /health/freshness degrades after 540 min without a success"
  schedule    = "20 */3 * * *"
  time_zone   = "UTC"
  attempt_deadline = "300s"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/ops/analyst-desk/fires/ingest?window_days=3"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "600s"
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# 5. Daily Parquet Export to GCS - 3:00 AM UTC daily
resource "google_cloud_scheduler_job" "parquet_export_daily" {
  name        = "parquet-export-daily"
  description = "Daily Parquet export of all station readings to GCS at 3:00 AM UTC"
  schedule    = "0 3 * * *"  # 3:00 AM UTC daily (8:00 AM PKT)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/exports/publish/station-readings-hourly-parquet"

    headers = {
      "Content-Type" = "application/json"
    }

    body = base64encode(jsonencode({
      start_date = "2018-01-01",
      end_date   = "2026-12-31",
      parameters = "all",
      data_type  = "hourly"
    }))

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "3600s"  # 1 hour max retry duration
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}

# 5b. Hourly Partitioned Export - 3:30 AM UTC daily (writes per-date partitions needed by daily aggregation)
resource "google_cloud_scheduler_job" "hourly_partitioned_export" {
  name        = "hourly-partitioned-export"
  description = "Daily partitioned hourly export to GCS (last 3 days) at 3:30 AM UTC"
  schedule    = "30 3 * * *"  # 3:30 AM UTC daily (8:30 AM PKT)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/exports/publish/station-readings-hourly-parquet-partitioned?days_back=3"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "1800s"
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# 6. Daily Station Aggregation - 4:00 AM UTC daily (1 hour after hourly parquet export)
resource "google_cloud_scheduler_job" "station_daily_aggregation" {
  name        = "station-daily-aggregation"
  description = "Daily aggregation of hourly station readings to daily statistics at 4:00 AM UTC"
  schedule    = "0 4 * * *"  # 4:00 AM UTC daily (9:00 AM PKT)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/exports/publish/station-daily/parquet?days_back=7&only_missing=true&apply_qc=true"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "3600s"  # 1 hour max retry duration
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}

# 7. Daily Brief Generation - 4:30 and 10:30 AM UTC (9:30 AM and 3:30 PM PKT)
# A brief needs the day's prediction (NRT, ~18:00 UTC the same day) and its station daily
# means (station-daily-aggregation, 4:00 AM UTC), so 4:30 publishes it; 10:30 is a catch-up.
# days_back=7 catches any missed dates; already-cached briefs are skipped instantly.
resource "google_cloud_scheduler_job" "daily_brief_generation" {
  name        = "daily-brief-generation"
  description = "Generate daily AQ briefs for recent prediction dates (skips already-cached)"
  schedule    = "30 4,10 * * *"  # 4:30 and 10:30 AM UTC (9:30 AM and 3:30 PM PKT)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/ops/pipeline/generate-briefs?days_back=7"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 2
    max_retry_duration   = "3600s"
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}

# Optional: Emergency full pipeline job (manual trigger via gcloud)
resource "google_cloud_scheduler_job" "full_pipeline_emergency" {
  name        = "full-pipeline-emergency"
  description = "Emergency full pipeline execution (paused by default)"
  schedule    = "0 0 1 1 *"  # January 1st (effectively disabled)
  time_zone   = "UTC"
  paused      = true  # Start in paused state

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/full-pipeline"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count = 1
    max_retry_duration = "7200s"  # 2 hours max retry duration
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}
# ---------------------------------------------------------------------------
# 8. OpenAQ v3 (independent source, shadow mode). All three jobs start PAUSED:
#    unpause after OPENAQ_API_KEY exists in Secret Manager, OPENAQ_ENABLED=true is
#    deployed on hawanama-ingest, and a `discover?dry_run=true` inventory has been
#    reviewed (stream count vs OPENAQ_RATE_PER_HOUR). The lease on the ingest side
#    makes a scheduler retry of a live run a no-op.
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "openaq_discovery" {
  name        = "openaq-discover-daily"
  description = "OpenAQ: discover Pakistan locations → shadow stations + pm25 stream checkpoints (01:10 UTC)"
  schedule    = "10 1 * * *"
  time_zone   = "UTC"
  paused      = true

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/openaq/discover"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "1800s"
    min_backoff_duration = "300s"
    max_backoff_duration = "600s"
  }
}

# Hourly at :40 — away from the IQAir station run (:15), the bot (:30), Punjab (:45)
# and the 03:00–04:00 export jobs.
resource "google_cloud_scheduler_job" "openaq_ingestion" {
  name        = "openaq-ingest-hourly"
  description = "OpenAQ: fetch the next window per active pm25 stream (shadow readings, source='openaq')"
  schedule    = "40 * * * *"
  time_zone   = "UTC"
  paused      = true

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/openaq/ingest"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "1800s"
    min_backoff_duration = "300s"
    max_backoff_duration = "600s"
  }
}

resource "google_cloud_scheduler_job" "openaq_reconcile" {
  name        = "openaq-reconcile-daily"
  description = "OpenAQ: re-read older windows for late/revised data without moving checkpoints (05:10 UTC)"
  schedule    = "10 5 * * *"
  time_zone   = "UTC"
  paused      = true

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/openaq/reconcile"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "1800s"
    min_backoff_duration = "300s"
    max_backoff_duration = "600s"
  }
}

# ---------------------------------------------------------------------------
# ICIMOD Air Quality Watch — shadow provider pilot (ICIMOD_ENABLED on hawanama-ingest).
# One POST per run fetches the current UTC day for every Punjab station; :50 is a free
# minute slot, and the run's latest_label_age_min shows whether an earlier slot would do.
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "icimod_ingestion" {
  name             = "icimod-ingest-hourly"
  description      = "ICIMOD: hourly PM2.5 for the EPCCD Punjab stations (shadow provider pilot)"
  schedule         = "50 * * * *"
  time_zone        = "UTC"
  attempt_deadline = "300s"

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/icimod/ingest"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "600s"
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# ---------------------------------------------------------------------------
# Station registry: province links by one rule (city first, geography second).
# Weekly dry run only — the run's details in ops.ingest_runs list what the rule would
# change (e.g. a new import filed under the wrong province). Applying is a reviewed
# POST ...?dry_run=false by an operator. Starts paused (house rule).
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "registry_provinces_weekly" {
  name             = "registry-provinces-weekly"
  description      = "Registry: weekly dry run of the province reconcile (details in ops.ingest_runs)"
  schedule         = "20 2 * * 1"
  time_zone        = "UTC"
  attempt_deadline = "300s"
  paused           = true

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/registry/provinces?dry_run=true"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "600s"
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# ---------------------------------------------------------------------------
# FIRMS aggregate store: attributed, deduplicated detections and daily region rollups
# under hindcast/firms/agg/, rebuilt for changed day files after each fire ingest
# (ingest runs at :20 with a 300 s deadline). The one-time backfill is a manual
# POST ...?backfill=true. Starts paused until one clean incremental run is reviewed.
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "firms_fire_aggregate" {
  name             = "firms-fire-aggregate"
  description      = "FIRMS: update the fire aggregate store (hindcast/firms/agg) for changed day files"
  schedule         = "40 */3 * * *"
  time_zone        = "UTC"
  attempt_deadline = "600s"
  paused           = true

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/fires/aggregate?backfill=false"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 2
    max_retry_duration   = "1800s"
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}

# ---------------------------------------------------------------------------
# Smoke outlook: ECMWF forecast winds × the last two days' fires, per city, for D+0…D+3,
# written to forecasts/smoke_outlook/latest.json. Runs after the fire aggregate (:40).
# One log line per run ("SMOKE OUTLOOK: …") feeds the Cloud Monitoring policy. Starts paused.
# ---------------------------------------------------------------------------

# Trajectories: planned every six hours; stays paused until the Linux HYSPLIT build is in the image
# (the task is a dry run without it). Backward 72 h to Lahore and Delhi, forward from crop clusters.
resource "google_cloud_scheduler_job" "fires_trajectories" {
  name             = "fires-trajectories"
  description      = "Fires: HYSPLIT trajectories for Lahore and Delhi (dry run until the binary is installed)"
  schedule         = "10 */6 * * *"
  time_zone        = "UTC"
  attempt_deadline = "1200s"
  paused           = true

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/fires/trajectories?dry_run=false"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "900s"
    min_backoff_duration = "120s"
  }
}

resource "google_cloud_scheduler_job" "fires_smoke_outlook" {
  name             = "fires-smoke-outlook"
  description      = "Fires: smoke outlook per city from forecast winds and current fires"
  schedule         = "55 */3 * * *"
  time_zone        = "UTC"
  attempt_deadline = "600s"
  paused           = true

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/fires/outlook"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "900s"
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}

# Satellite column series: TROPOMI OFFL L3 columns (NO2, CO, SO2, O3, HCHO, aerosol index) and MAIAC AOD
# reduced on Earth Engine to the 24 regions in app/services/satellite_regions.py, written to
# satellite/series/<product>.parquet. Runs after the overpass products of D-1 (MAIAC) have landed;
# OFFL L3 days arrive 3–14 days later and stay "pending" until they do. Enabled 2026-11-07 after a
# dry run on hawanama-ingest (4f4ca69: EE ping ok, 30 days planned per kind).
resource "google_cloud_scheduler_job" "satellite_series_daily" {
  name             = "satellite-series-daily"
  description      = "Earth Engine: TROPOMI and MAIAC region series for missing and recent days (satellite/series)"
  schedule         = "35 1 * * *"
  time_zone        = "UTC"
  attempt_deadline = "1200s"
  paused           = false

  http_target {
    http_method = "POST"
    uri         = "${local.ingest_base_url}/api/v1/tasks/satellite/refresh?kind=all"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = local.ingest_base_url
    }
  }

  retry_config {
    retry_count          = 1
    max_retry_duration   = "1800s"
    min_backoff_duration = "300s"
    max_backoff_duration = "600s"
  }
}
