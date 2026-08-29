// Types for Ops Pipeline components

export interface StationReading {
  name: string
  city: string
  pm25: number
  lat: number
  lon: number
  latitude?: number
  longitude?: number
  valid_hours?: number | null
  complete?: boolean
}

export interface StationDailyResponse {
  date: string
  stations: StationReading[]
}

export interface ModelPointer {
  model_uri: string
  waterline: string
  reference_date: string
  cutoff_days: number
  created_at_utc: string
  git_commit: string
  source: string
}

export interface PredictionsPointer {
  last_published_date: string
  model_version: string
  updated_at: string
  cutoff_days: number
}

export interface RunReportDetails {
  station_data?: {
    status: boolean
    available: boolean
    n_stations: number
    n_obs: number
    pm25_min?: number
    pm25_max?: number
    pm25_mean?: number
    pm25_median?: number
    error?: string
  }
  feature_partitions?: {
    met?: { status: string; available?: boolean; missing_rate?: number; n_rows?: number; n_cols?: number; key_features_missing?: Record<string, number>; error?: string }
    aod?: { status: string; available?: boolean; missing_rate?: number; n_rows?: number; n_cols?: number; key_features_missing?: Record<string, number>; error?: string }
    tropomi?: { status: string; available?: boolean; missing_rate?: number; n_rows?: number; n_cols?: number; key_features_missing?: Record<string, number>; error?: string }
  }
  master_partition?: {
    status: string | boolean
    available?: boolean
    master_rows?: number
    n_features?: number
    total_missing_rate?: number
    missing_by_family?: { met: number; aod: number; tropomi: number }
  }
  inference?: {
    status: string | boolean
    available?: boolean
    error?: string
    n_grid_points?: number
    pred_min?: number
    pred_max?: number
    pred_mean?: number
    pred_median?: number
    pred_p95?: number
    pct_negative?: number
  }
  runtime_seconds?: number
}

export interface DataQuality {
  total_features: number
  missing_features: number
  available_features: number
  nan_fraction: number
  pakistan_cells: number
  stage_coverage: {
    met?: number
    aod?: number
    tropomi?: number
  }
  stage_nan_fraction?: {
    met?: number
    aod?: number
    tropomi?: number
  }
  stage_feature_count?: {
    met?: number
    aod?: number
    tropomi?: number
  }
}

export interface RunReport {
  schema_version: string
  git_commit: string
  date: string
  t_serve: string
  success: boolean
  model_version: string
  cutoff_days: number
  run_at: string
  model?: {
    uri: string
    waterline: string
    created_at: string
    source: string
  }
  data_quality?: DataQuality
  details?: RunReportDetails
}

export interface PipelineSummary {
  model_pointer: ModelPointer | null
  predictions_pointer: PredictionsPointer | null
  latest_run_report: RunReport | null
  derived_bucket: string
  region: string
  gcp_project: string
  jobs: {
    daily: string
    retrain: string
  }
}

export interface Execution {
  name: string
  uid: string
  createTime: string
  completionTime?: string
  job: string
  conditions?: Array<{
    type: string
    state: string
    message?: string
  }>
  succeededCount?: number
  failedCount?: number
  logUri?: string
}

export interface ExecutionsResponse {
  executions?: Execution[]
}

export interface RunsResponse {
  dates: string[]
  count: number
}

export interface PredictionData {
  date: string
  grid: {
    shape: number[]
    bounds: {
      west: number
      east: number
      south: number
      north: number
    }
    resolution: number
  }
  stats: {
    mean: number | null
    median: number | null
    min: number | null
    max: number | null
    p05: number | null
    p95: number | null
    std: number | null
    n_valid: number
    n_total: number
  }
  lats: number[]
  lons: number[]
  pm25: (number | null)[]
  colorscale: {
    name: string
    vmin: number
    vmax: number
  }
}

export interface PredictionsResponse {
  dates: string[]
  count: number
}

export interface TileDatesResponse {
  dates: string[]
  count: number
  tile_url_template: string
  tilejson_url_template: string
}

export type TabType = 'overview' | 'features' | 'executions' | 'results' | 'model-history' | 'daily-status'

export interface FeatureInfo {
  name: string
  stage: string
  unit: string
  vmin: number
  vmax: number
  colormap: string
}

export interface FeaturesListResponse {
  features: FeatureInfo[]
  count: number
}

export interface FeatureDatesResponse {
  dates: string[]
  count: number
  feature: string
}

export interface ModelHistoryEntry {
  schema_version: string
  training_mode: 'operational' | 'cv' | 'operational_waterline'
  reference_date: string
  waterline: string
  cutoff_days: number
  validation_days: number
  train_date_range: [string, string]
  val_date_range: [string, string]
  train_samples: number
  val_samples: number
  train_years: number[]
  n_features: number
  val_metrics: {
    rmse: number
    mae: number
    r2: number
    bias: number
    n_predictions?: number
    n_stations?: number
    skill_vs_station_month?: number
    skill_vs_yesterday?: number
  }
  val_monthly?: Record<string, {
    rmse: number
    mae: number
    r2: number
    bias: number
    n_predictions?: number
  }>
  lgbm_params_used?: Record<string, number | string | boolean>
  feature_importance_top30?: [string, number][]
  timestamp: string
  git_commit?: string
  created_at_utc?: string
}

export interface ModelHistoryResponse {
  reference_dates: string[]
  count: number
}

// Model training details - supports both operational and CV training formats
export interface ModelDetails {
  training_mode: 'operational' | 'cv'
  model_type: string
  waterline: string
  n_features: number
  train_samples: number
  timestamp: string

  // Operational waterline format
  reference_date?: string
  cutoff_days?: number
  validation_days?: number
  val_samples?: number
  train_date_range?: [string, string]
  val_date_range?: [string, string]
  train_years?: number[]
  val_metrics?: {
    rmse: number
    mae: number
    r2: number
    bias: number
    n_predictions: number
    n_stations: number
    skill_vs_station_month: number
    skill_vs_yesterday: number
  }
  val_monthly?: Record<string, {
    rmse: number
    mae: number
    r2: number
    bias: number
    n_predictions: number
  }>
  lgbm_params_used?: Record<string, number | string | boolean>

  // CV training format
  dev_samples?: number
  test_samples?: number
  best_params?: {
    max_depth: number
    num_leaves: number
    min_child_samples: number
    reg_lambda: number
    reg_alpha: number
    subsample: number
    colsample_bytree: number
    learning_rate: number
    min_split_gain: number
    n_estimators: number
    random_state: number
  }
  cv?: {
    folds: Record<string, {
      train_years: number[]
      val_year: number
      val_metrics: {
        rmse: number
        mae: number
        r2: number
        bias: number
        f1_150: number
        n_predictions: number
      }
    }>
    summary: {
      rmse: { mean: number; std: number }
      mae: { mean: number; std: number }
      r2: { mean: number; std: number }
      bias: { mean: number; std: number }
    }
  }
  final_model?: {
    dev_overall: {
      rmse: number
      mae: number
      r2: number
      bias: number
    }
    test_overall: {
      rmse: number
      mae: number
      r2: number
      bias: number
    }
  }
  feature_importance_top20?: [string, number][]
}
