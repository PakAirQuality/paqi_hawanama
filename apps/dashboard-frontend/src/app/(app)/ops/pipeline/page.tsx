"use client";

import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  Play,
  RefreshCw,
  CheckCircle2,
  XCircle,
  Clock,
  AlertTriangle,
  ExternalLink,
  Loader2,
  GitCommit,
  Database,
  Cpu,
  Calendar
} from 'lucide-react'

const API_BASE = "https://hawanama-152782825429.asia-south1.run.app";
const API_TOKEN = "***REMOVED***"; // TODO: Move to env/auth

// Types
interface ModelPointer {
  model_uri: string
  waterline: string
  reference_date: string
  cutoff_days: number
  created_at_utc: string
  git_commit: string
  source: string
}

interface PredictionsPointer {
  last_published_date: string
  model_version: string
  updated_at: string
  cutoff_days: number
}

interface RunReportDetails {
  station_data?: {
    status: boolean
    available: boolean
    n_stations: number
    n_obs: number
  }
  feature_partitions?: {
    met?: { status: string; available?: boolean; missing_rate?: number }
    aod?: { status: string; available?: boolean; missing_rate?: number }
    tropomi?: { status: string; available?: boolean; missing_rate?: number }
  }
  master_partition?: {
    status: string | boolean
    available?: boolean
    master_rows?: number
    n_features?: number
    total_missing_rate?: number
  }
  inference?: {
    status: string | boolean
    available?: boolean
    error?: string
  }
  runtime_seconds?: number
}

interface RunReport {
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
  details?: RunReportDetails
}

interface PipelineSummary {
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

interface Execution {
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

interface ExecutionsResponse {
  executions?: Execution[]
}

interface RunsResponse {
  dates: string[]
  count: number
}

// API Functions
async function fetchPipelineSummary(): Promise<PipelineSummary> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/summary`, {
    headers: { Authorization: `Bearer ${API_TOKEN}` },
    cache: 'no-store'
  });
  if (!res.ok) throw new Error("Failed to load pipeline summary");
  return res.json();
}

async function fetchRuns(limit: number = 30): Promise<RunsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/runs?limit=${limit}`, {
    headers: { Authorization: `Bearer ${API_TOKEN}` },
    cache: 'no-store'
  });
  if (!res.ok) throw new Error("Failed to load runs");
  return res.json();
}

async function fetchRunReport(date: string): Promise<RunReport> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/runs/${date}`, {
    headers: { Authorization: `Bearer ${API_TOKEN}` },
    cache: 'no-store'
  });
  if (!res.ok) throw new Error(`Failed to load run report for ${date}`);
  return res.json();
}

async function fetchExecutions(which: 'daily' | 'retrain'): Promise<ExecutionsResponse> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/executions/${which}?page_size=10`, {
    headers: { Authorization: `Bearer ${API_TOKEN}` },
    cache: 'no-store'
  });
  if (!res.ok) throw new Error(`Failed to load ${which} executions`);
  return res.json();
}

async function triggerJob(which: 'daily' | 'retrain'): Promise<{ job: string; status: string }> {
  const res = await fetch(`${API_BASE}/api/v1/ops/pipeline/run/${which}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${API_TOKEN}` },
  });
  if (!res.ok) throw new Error(`Failed to trigger ${which} job`);
  return res.json();
}

// Helper functions
function getExecutionStatus(execution: Execution): 'running' | 'succeeded' | 'failed' {
  const completedCondition = execution.conditions?.find(c => c.type === 'Completed');
  if (!completedCondition || completedCondition.state === 'CONDITION_PENDING') {
    return 'running';
  }
  if (completedCondition.state === 'CONDITION_SUCCEEDED') {
    return 'succeeded';
  }
  return 'failed';
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs}s`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}

// Components
function StatusBadge({ success }: { success: boolean }) {
  return (
    <Badge className={`text-xs ${
      success
        ? 'bg-green-100 text-green-700 border-green-200'
        : 'bg-red-100 text-red-700 border-red-200'
    }`}>
      {success ? (
        <><CheckCircle2 className="w-3 h-3 mr-1" /> Success</>
      ) : (
        <><XCircle className="w-3 h-3 mr-1" /> Failed</>
      )}
    </Badge>
  );
}

function ExecutionStatusBadge({ status }: { status: 'running' | 'succeeded' | 'failed' }) {
  const config = {
    running: { bg: 'bg-blue-100 text-blue-700 border-blue-200', icon: Loader2, text: 'Running' },
    succeeded: { bg: 'bg-green-100 text-green-700 border-green-200', icon: CheckCircle2, text: 'Succeeded' },
    failed: { bg: 'bg-red-100 text-red-700 border-red-200', icon: XCircle, text: 'Failed' }
  };
  const { bg, icon: Icon, text } = config[status];
  return (
    <Badge className={`text-xs ${bg}`}>
      <Icon className={`w-3 h-3 mr-1 ${status === 'running' ? 'animate-spin' : ''}`} />
      {text}
    </Badge>
  );
}

function HealthAlert({ condition, message }: { condition: boolean; message: string }) {
  if (!condition) return null;
  return (
    <div className="flex items-center space-x-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
      <AlertTriangle className="w-4 h-4 text-amber-600" />
      <span className="text-sm text-amber-800">{message}</span>
    </div>
  );
}

export default function OpsPipelinePage() {
  const queryClient = useQueryClient();
  const [selectedRunDate, setSelectedRunDate] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'runs' | 'executions'>('overview');

  // Queries
  const { data: summary, isLoading: summaryLoading, refetch: refetchSummary } = useQuery({
    queryKey: ["ops-pipeline-summary"],
    queryFn: fetchPipelineSummary,
    refetchInterval: 30000, // Auto-refresh every 30s
  });

  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ["ops-pipeline-runs"],
    queryFn: () => fetchRuns(30),
  });

  const { data: dailyExecs, isLoading: dailyExecsLoading, refetch: refetchDailyExecs } = useQuery({
    queryKey: ["ops-pipeline-executions-daily"],
    queryFn: () => fetchExecutions('daily'),
    refetchInterval: 10000, // Poll every 10s for live status
  });

  const { data: retrainExecs } = useQuery({
    queryKey: ["ops-pipeline-executions-retrain"],
    queryFn: () => fetchExecutions('retrain'),
    refetchInterval: 10000,
  });

  const { data: selectedRun, isLoading: selectedRunLoading } = useQuery({
    queryKey: ["ops-pipeline-run", selectedRunDate],
    queryFn: () => selectedRunDate ? fetchRunReport(selectedRunDate) : null,
    enabled: !!selectedRunDate,
  });

  // Mutations
  const triggerDailyMutation = useMutation({
    mutationFn: () => triggerJob('daily'),
    onSuccess: () => {
      refetchDailyExecs();
      setTimeout(() => refetchSummary(), 5000);
    }
  });

  const triggerRetrainMutation = useMutation({
    mutationFn: () => triggerJob('retrain'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ops-pipeline-executions-retrain"] });
    }
  });

  // Check for running jobs
  const hasRunningDaily = dailyExecs?.executions?.some(e => getExecutionStatus(e) === 'running');
  const hasRunningRetrain = retrainExecs?.executions?.some(e => getExecutionStatus(e) === 'running');

  // Health checks
  const latestRun = summary?.latest_run_report;
  const healthAlerts = [
    { condition: latestRun?.success === false, message: "Latest run failed" },
    { condition: (latestRun?.details?.feature_partitions?.aod?.missing_rate ?? 0) > 0.8, message: "AOD missing rate > 80%" },
    { condition: (latestRun?.details?.station_data?.n_stations ?? 0) < 10, message: "Less than 10 stations available" },
    { condition: (latestRun?.details?.master_partition?.total_missing_rate ?? 0) > 0.2, message: "Master partition missing rate > 20%" },
  ].filter(a => a.condition);

  return (
    <div className="space-y-6">
      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-8">
          {[
            { id: 'overview', name: 'Overview' },
            { id: 'runs', name: 'Run History' },
            { id: 'executions', name: 'Job Executions' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`py-3 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-600 hover:text-gray-900 hover:border-gray-300'
              }`}
            >
              {tab.name}
            </button>
          ))}
        </nav>
      </div>

      {/* Health Alerts */}
      {healthAlerts.length > 0 && (
        <div className="space-y-2">
          {healthAlerts.map((alert, i) => (
            <HealthAlert key={i} condition={true} message={alert.message} />
          ))}
        </div>
      )}

      {activeTab === 'overview' && (
        <>
          {/* Action Buttons */}
          <div className="flex items-center space-x-4">
            <button
              onClick={() => triggerDailyMutation.mutate()}
              disabled={triggerDailyMutation.isPending || hasRunningDaily}
              className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {(triggerDailyMutation.isPending || hasRunningDaily) ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              <span>{hasRunningDaily ? 'Daily Running...' : 'Run Daily Pipeline'}</span>
            </button>

            <button
              onClick={() => triggerRetrainMutation.mutate()}
              disabled={triggerRetrainMutation.isPending || hasRunningRetrain}
              className="flex items-center space-x-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {(triggerRetrainMutation.isPending || hasRunningRetrain) ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              <span>{hasRunningRetrain ? 'Retraining...' : 'Run Model Retrain'}</span>
            </button>

            <button
              onClick={() => refetchSummary()}
              className="flex items-center space-x-2 px-3 py-2 text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Refresh</span>
            </button>
          </div>

          {/* Status Cards */}
          <div className="grid gap-4 md:grid-cols-4">
            {/* Last Published */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <Calendar className="w-4 h-4 text-gray-500" />
                  <h3 className="text-sm font-medium text-gray-600">Last Published</h3>
                </div>
                {summaryLoading ? (
                  <div className="h-8 bg-gray-200 rounded animate-pulse"></div>
                ) : (
                  <div className="text-2xl font-bold text-gray-900">
                    {summary?.predictions_pointer?.last_published_date || 'N/A'}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Latest Run Status */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <Cpu className="w-4 h-4 text-gray-500" />
                  <h3 className="text-sm font-medium text-gray-600">Latest Run</h3>
                </div>
                {summaryLoading ? (
                  <div className="h-8 bg-gray-200 rounded animate-pulse"></div>
                ) : latestRun ? (
                  <div className="space-y-1">
                    <StatusBadge success={latestRun.success} />
                    <div className="text-sm text-gray-500">
                      {latestRun.date} ({formatDuration(latestRun.details?.runtime_seconds ?? 0)})
                    </div>
                  </div>
                ) : (
                  <div className="text-gray-400">No runs</div>
                )}
              </CardContent>
            </Card>

            {/* Model Waterline */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <Database className="w-4 h-4 text-gray-500" />
                  <h3 className="text-sm font-medium text-gray-600">Model Waterline</h3>
                </div>
                {summaryLoading ? (
                  <div className="h-8 bg-gray-200 rounded animate-pulse"></div>
                ) : (
                  <div className="text-2xl font-bold text-gray-900">
                    {summary?.model_pointer?.waterline || 'N/A'}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Git Commit */}
            <Card>
              <CardContent className="p-6">
                <div className="flex items-center space-x-2 mb-2">
                  <GitCommit className="w-4 h-4 text-gray-500" />
                  <h3 className="text-sm font-medium text-gray-600">Git Commit</h3>
                </div>
                {summaryLoading ? (
                  <div className="h-8 bg-gray-200 rounded animate-pulse"></div>
                ) : (
                  <div className="text-lg font-mono text-gray-900">
                    {summary?.model_pointer?.git_commit || 'N/A'}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* Model & Predictions Details */}
          <div className="grid gap-6 lg:grid-cols-2">
            {/* Model Pointer */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                  <Database className="w-5 h-5" />
                  <span>Current Model</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {summaryLoading ? (
                  <div className="space-y-3">
                    {[...Array(4)].map((_, i) => (
                      <div key={i} className="h-4 bg-gray-200 rounded animate-pulse"></div>
                    ))}
                  </div>
                ) : summary?.model_pointer ? (
                  <div className="space-y-3">
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">Model URI</span>
                      <span className="text-sm font-mono text-gray-900 truncate max-w-xs" title={summary.model_pointer.model_uri}>
                        ...{summary.model_pointer.model_uri.split('/').slice(-1)[0]}
                      </span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">Waterline</span>
                      <span className="text-sm font-medium text-gray-900">{summary.model_pointer.waterline}</span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">Cutoff Days</span>
                      <span className="text-sm font-medium text-gray-900">{summary.model_pointer.cutoff_days}</span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">Created</span>
                      <span className="text-sm text-gray-900">{formatDate(summary.model_pointer.created_at_utc)}</span>
                    </div>
                    <div className="flex justify-between py-2">
                      <span className="text-sm text-gray-600">Source</span>
                      <Badge variant="outline" className="text-xs">{summary.model_pointer.source}</Badge>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-8 text-gray-500">No model pointer found</div>
                )}
              </CardContent>
            </Card>

            {/* Latest Run Details */}
            <Card>
              <CardHeader>
                <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                  <Cpu className="w-5 h-5" />
                  <span>Latest Run Details</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {summaryLoading ? (
                  <div className="space-y-3">
                    {[...Array(5)].map((_, i) => (
                      <div key={i} className="h-4 bg-gray-200 rounded animate-pulse"></div>
                    ))}
                  </div>
                ) : latestRun?.details ? (
                  <div className="space-y-3">
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">Stations</span>
                      <span className="text-sm font-medium text-gray-900">
                        {latestRun.details.station_data?.n_stations ?? 0} stations / {latestRun.details.station_data?.n_obs ?? 0} obs
                      </span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">MET Status</span>
                      <Badge variant="outline" className={`text-xs ${
                        latestRun.details.feature_partitions?.met?.status === 'exists' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                      }`}>
                        {latestRun.details.feature_partitions?.met?.status ?? 'unknown'}
                      </Badge>
                    </div>
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">AOD Missing Rate</span>
                      <span className="text-sm font-medium text-gray-900">
                        {((latestRun.details.feature_partitions?.aod?.missing_rate ?? 0) * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="flex justify-between py-2 border-b border-gray-100">
                      <span className="text-sm text-gray-600">Master Rows</span>
                      <span className="text-sm font-medium text-gray-900">
                        {latestRun.details.master_partition?.master_rows?.toLocaleString() ?? 'N/A'}
                      </span>
                    </div>
                    <div className="flex justify-between py-2">
                      <span className="text-sm text-gray-600">Runtime</span>
                      <span className="text-sm font-medium text-gray-900">
                        {formatDuration(latestRun.details.runtime_seconds ?? 0)}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-8 text-gray-500">No run details available</div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {activeTab === 'runs' && (
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Runs List */}
          <Card className="lg:col-span-1">
            <CardHeader>
              <CardTitle className="text-lg font-semibold">Run History</CardTitle>
            </CardHeader>
            <CardContent>
              {runsLoading ? (
                <div className="space-y-2">
                  {[...Array(10)].map((_, i) => (
                    <div key={i} className="h-10 bg-gray-200 rounded animate-pulse"></div>
                  ))}
                </div>
              ) : (
                <div className="space-y-1 max-h-[500px] overflow-y-auto">
                  {runs?.dates?.slice().reverse().map((date) => (
                    <button
                      key={date}
                      onClick={() => setSelectedRunDate(date)}
                      className={`w-full text-left px-3 py-2 rounded-lg text-sm transition-colors ${
                        selectedRunDate === date
                          ? 'bg-blue-100 text-blue-700'
                          : 'hover:bg-gray-100 text-gray-700'
                      }`}
                    >
                      {date}
                    </button>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Selected Run Details */}
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-lg font-semibold">
                {selectedRunDate ? `Run: ${selectedRunDate}` : 'Select a run'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!selectedRunDate ? (
                <div className="text-center py-12 text-gray-500">
                  Select a run from the list to view details
                </div>
              ) : selectedRunLoading ? (
                <div className="space-y-4">
                  {[...Array(6)].map((_, i) => (
                    <div key={i} className="h-6 bg-gray-200 rounded animate-pulse"></div>
                  ))}
                </div>
              ) : selectedRun ? (
                <div className="space-y-4">
                  <div className="flex items-center space-x-4">
                    <StatusBadge success={selectedRun.success} />
                    <span className="text-sm text-gray-500">
                      {formatDate(selectedRun.run_at)}
                    </span>
                    <Badge variant="outline" className="text-xs">
                      {selectedRun.git_commit}
                    </Badge>
                  </div>

                  <div className="grid gap-4 md:grid-cols-2 mt-4">
                    <div className="p-4 bg-gray-50 rounded-lg">
                      <h4 className="font-medium text-gray-700 mb-2">Station Data</h4>
                      <div className="space-y-1 text-sm">
                        <div className="flex justify-between">
                          <span className="text-gray-600">Stations</span>
                          <span>{selectedRun.details?.station_data?.n_stations}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-600">Observations</span>
                          <span>{selectedRun.details?.station_data?.n_obs}</span>
                        </div>
                      </div>
                    </div>

                    <div className="p-4 bg-gray-50 rounded-lg">
                      <h4 className="font-medium text-gray-700 mb-2">Feature Partitions</h4>
                      <div className="space-y-1 text-sm">
                        {['met', 'aod', 'tropomi'].map((feature) => {
                          const data = selectedRun.details?.feature_partitions?.[feature as keyof typeof selectedRun.details.feature_partitions];
                          return (
                            <div key={feature} className="flex justify-between">
                              <span className="text-gray-600 uppercase">{feature}</span>
                              <Badge variant="outline" className={`text-xs ${
                                data?.status === 'exists' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'
                              }`}>
                                {data?.status ?? 'N/A'}
                              </Badge>
                            </div>
                          );
                        })}
                      </div>
                    </div>

                    <div className="p-4 bg-gray-50 rounded-lg">
                      <h4 className="font-medium text-gray-700 mb-2">Master Partition</h4>
                      <div className="space-y-1 text-sm">
                        <div className="flex justify-between">
                          <span className="text-gray-600">Rows</span>
                          <span>{selectedRun.details?.master_partition?.master_rows?.toLocaleString()}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-600">Features</span>
                          <span>{selectedRun.details?.master_partition?.n_features}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-600">Missing Rate</span>
                          <span>{((selectedRun.details?.master_partition?.total_missing_rate ?? 0) * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                    </div>

                    <div className="p-4 bg-gray-50 rounded-lg">
                      <h4 className="font-medium text-gray-700 mb-2">Inference</h4>
                      <div className="space-y-1 text-sm">
                        <div className="flex justify-between">
                          <span className="text-gray-600">Status</span>
                          <span>{String(selectedRun.details?.inference?.status)}</span>
                        </div>
                        {selectedRun.details?.inference?.error && (
                          <div className="text-red-600 text-xs mt-2">
                            {selectedRun.details.inference.error}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="pt-4 border-t border-gray-200">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">Runtime</span>
                      <span className="font-medium">{formatDuration(selectedRun.details?.runtime_seconds ?? 0)}</span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-center py-12 text-gray-500">
                  Failed to load run details
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {activeTab === 'executions' && (
        <div className="grid gap-6 lg:grid-cols-2">
          {/* Daily Executions */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                <Play className="w-5 h-5" />
                <span>Daily Pipeline Executions</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {dailyExecsLoading ? (
                <div className="space-y-3">
                  {[...Array(5)].map((_, i) => (
                    <div key={i} className="h-16 bg-gray-200 rounded animate-pulse"></div>
                  ))}
                </div>
              ) : dailyExecs?.executions?.length ? (
                <div className="space-y-3">
                  {dailyExecs.executions.map((exec) => {
                    const status = getExecutionStatus(exec);
                    return (
                      <div key={exec.uid} className="p-3 bg-gray-50 rounded-lg">
                        <div className="flex items-start justify-between">
                          <div className="space-y-1">
                            <div className="flex items-center space-x-2">
                              <ExecutionStatusBadge status={status} />
                              <span className="text-xs text-gray-500 font-mono">
                                {exec.name.split('/').pop()}
                              </span>
                            </div>
                            <div className="text-xs text-gray-600">
                              Started: {formatDate(exec.createTime)}
                              {exec.completionTime && (
                                <> | Completed: {formatDate(exec.completionTime)}</>
                              )}
                            </div>
                          </div>
                          {exec.logUri && (
                            <a
                              href={exec.logUri}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-blue-600 hover:text-blue-800"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500">
                  No executions found
                </div>
              )}
            </CardContent>
          </Card>

          {/* Retrain Executions */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg font-semibold flex items-center space-x-2">
                <RefreshCw className="w-5 h-5" />
                <span>Model Retrain Executions</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {retrainExecs?.executions?.length ? (
                <div className="space-y-3">
                  {retrainExecs.executions.map((exec) => {
                    const status = getExecutionStatus(exec);
                    return (
                      <div key={exec.uid} className="p-3 bg-gray-50 rounded-lg">
                        <div className="flex items-start justify-between">
                          <div className="space-y-1">
                            <div className="flex items-center space-x-2">
                              <ExecutionStatusBadge status={status} />
                              <span className="text-xs text-gray-500 font-mono">
                                {exec.name.split('/').pop()}
                              </span>
                            </div>
                            <div className="text-xs text-gray-600">
                              Started: {formatDate(exec.createTime)}
                              {exec.completionTime && (
                                <> | Completed: {formatDate(exec.completionTime)}</>
                              )}
                            </div>
                          </div>
                          {exec.logUri && (
                            <a
                              href={exec.logUri}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-blue-600 hover:text-blue-800"
                            >
                              <ExternalLink className="w-4 h-4" />
                            </a>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500">
                  No retrain executions found
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
