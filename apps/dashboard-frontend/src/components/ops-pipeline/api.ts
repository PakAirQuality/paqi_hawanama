// API functions for Ops Pipeline

import type {
  PipelineSummary,
  RunsResponse,
  RunReport,
  ExecutionsResponse,
  PredictionsResponse,
  PredictionData,
  TileDatesResponse,
  ModelDetails,
  ModelHistoryResponse,
  ModelHistoryEntry,
} from './types'

export const API_BASE = "https://hawanama-152782825429.asia-south1.run.app"
export const API_TOKEN = "***REMOVED***" // TODO: Move to env/auth

const headers = {
  Authorization: `Bearer ${API_TOKEN}`,
}

export async function fetchPipelineSummary(): Promise<PipelineSummary> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/summary`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load pipeline summary")
  return res.json()
}

export async function fetchRuns(limit: number = 30): Promise<RunsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/runs?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load runs")
  return res.json()
}

export async function fetchRunReport(date: string): Promise<RunReport> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/runs/${date}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load run report for ${date}`)
  return res.json()
}

export async function fetchExecutions(which: 'daily' | 'retrain'): Promise<ExecutionsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/executions/${which}?page_size=10`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load ${which} executions`)
  return res.json()
}

export async function triggerJob(which: 'daily' | 'retrain'): Promise<{ job: string; status: string }> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/run/${which}`, {
    method: 'POST',
    headers,
  })
  if (!res.ok) throw new Error(`Failed to trigger ${which} job`)
  return res.json()
}

export async function fetchPredictions(limit: number = 30): Promise<PredictionsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/predictions?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load predictions list")
  return res.json()
}

export async function fetchPredictionData(date: string): Promise<PredictionData> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/predictions/${date}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load prediction data for ${date}`)
  return res.json()
}

export async function fetchTileDates(limit: number = 365): Promise<TileDatesResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/tiles/dates?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load tile dates")
  return res.json()
}

export function getTileJsonUrl(date: string): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/${date}/tilejson`
}

export function getTileUrl(date: string, z: number, x: number, y: number): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/${date}/${z}/${x}/${y}.png`
}

export function getPointQueryUrl(date: string, lat: number, lon: number): string {
  return `${API_BASE}/api/v1/ops/pipeline/tiles/${date}/point?lat=${lat}&lon=${lon}`
}

export async function fetchModelDetails(): Promise<ModelDetails> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/model-details`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load model details")
  return res.json()
}

export async function fetchModelHistory(limit: number = 30): Promise<ModelHistoryResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/model-history?limit=${limit}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error("Failed to load model history")
  return res.json()
}

export async function fetchModelHistoryEntry(referenceDate: string): Promise<ModelHistoryEntry> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/model-history/${referenceDate}`, {
    headers,
    cache: 'no-store'
  })
  if (!res.ok) throw new Error(`Failed to load model history for ${referenceDate}`)
  return res.json()
}
