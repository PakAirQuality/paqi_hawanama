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

# Grant the service account permission to invoke Cloud Run
resource "google_cloud_run_service_iam_member" "scheduler_invoker" {
  project  = "hawanama-2"
  location = "asia-south1"
  service  = "hawanama"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

# 1. Station Discovery - Twice Daily (2:00 AM and 2:00 PM UTC)
resource "google_cloud_scheduler_job" "station_discovery_2am" {
  name        = "station-discovery-2am"
  description = "Station discovery at 2:00 AM UTC (7:00 AM PKT)"
  schedule    = "0 2 * * *"  # 2:00 AM UTC
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/tasks/discover"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/tasks/discover"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/tasks/ingest-stations"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/tasks/ingest-cities"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/bot/execute"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    body = base64encode(jsonencode({
      dry_run = false
    }))
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/bot/execute"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    body = base64encode(jsonencode({
      dry_run = true,
      force_post = true
    }))
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/punjab/ingest/hourly"
    
    headers = {
      "Content-Type" = "application/json"
    }
    
    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "1800s"  # 30 minutes max retry duration
    min_backoff_duration = "60s"
    max_backoff_duration = "300s"
  }
}

# 4b. FIRMS Fire Data Ingestion - 2:00 AM UTC daily
resource "google_cloud_scheduler_job" "firms_fire_ingest" {
  name        = "firms-fire-ingest"
  description = "Daily FIRMS VIIRS fire data fetch from NASA API at 2:00 AM UTC"
  schedule    = "0 2 * * *"  # 2:00 AM UTC daily (7:00 AM PKT)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/ops/analyst-desk/fires/ingest?days_back=3"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/publish/station-readings-hourly-parquet"

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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/publish/station-readings-hourly-parquet-partitioned?days_back=3"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/exports/publish/station-daily/parquet?start_date=2024-01-01&end_date=2026-12-31&only_missing=true&apply_qc=true"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  retry_config {
    retry_count = 2
    max_retry_duration = "3600s"  # 1 hour max retry duration
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}

# 7. Daily Brief Generation - 10:00 AM UTC (3:00 PM PKT)
# Runs after daily prediction pipeline has typically completed.
# days_back=7 catches any missed dates; already-cached briefs are skipped instantly.
resource "google_cloud_scheduler_job" "daily_brief_generation" {
  name        = "daily-brief-generation"
  description = "Generate daily AQ briefs for recent prediction dates (skips already-cached)"
  schedule    = "0 10 * * *"  # 10:00 AM UTC (3:00 PM PKT)
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/ops/pipeline/generate-briefs?days_back=7"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
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
    uri         = "https://hawanama-152782825429.asia-south1.run.app/api/v1/tasks/full-pipeline"

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  retry_config {
    retry_count = 1
    max_retry_duration = "7200s"  # 2 hours max retry duration
    min_backoff_duration = "120s"
    max_backoff_duration = "600s"
  }
}