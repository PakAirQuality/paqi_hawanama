"use client"

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import {
  fetchPipelineSummary,
  fetchExecutions,
  triggerJob,
  fetchTileDates,
  fetchPredictionData,
  fetchModelHistory,
  fetchModelHistoryEntry,
  fetchFeaturesList,
  fetchFeatureDates,
  fetchRuns,
  fetchRunReport,
  getExecutionStatus,
  type TabType,
} from '@/components/ops-pipeline'

import { HealthAlert } from '@/components/ops-pipeline/StatusBadges'
import { OverviewTab } from '@/components/ops-pipeline/OverviewTab'
import { FeaturesTab } from '@/components/ops-pipeline/FeaturesTab'
import { ExecutionsTab } from '@/components/ops-pipeline/ExecutionsTab'
import { ResultsTab } from '@/components/ops-pipeline/ResultsTab'
import { ModelHistoryTab } from '@/components/ops-pipeline/ModelHistoryTab'
import { DailyStatusTab } from '@/components/ops-pipeline/DailyStatusTab'

export default function OpsPipelinePage() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabType>('overview')
  const [selectedPredDate, setSelectedPredDate] = useState<string | null>(null)
  const [selectedModelRefDate, setSelectedModelRefDate] = useState<string | null>(null)
  const [selectedFeature, setSelectedFeature] = useState<string | null>(null)
  const [selectedFeatureDate, setSelectedFeatureDate] = useState<string | null>(null)
  const [selectedRunDate, setSelectedRunDate] = useState<string | null>(null)

  // Queries
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["ops-pipeline-summary"],
    queryFn: fetchPipelineSummary,
    refetchInterval: 30000,
  })

  const { data: featuresList, isLoading: featuresListLoading } = useQuery({
    queryKey: ["ops-pipeline-features-list"],
    queryFn: fetchFeaturesList,
    enabled: activeTab === 'features',
  })

  const { data: featureDates, isLoading: featureDatesLoading } = useQuery({
    queryKey: ["ops-pipeline-feature-dates", selectedFeature],
    queryFn: () => selectedFeature ? fetchFeatureDates(selectedFeature, 365) : null,
    enabled: !!selectedFeature && activeTab === 'features',
  })

  const { data: dailyExecs, isLoading: dailyExecsLoading } = useQuery({
    queryKey: ["ops-pipeline-executions-daily"],
    queryFn: () => fetchExecutions('daily'),
    refetchInterval: 10000,
  })

  const { data: retrainExecs } = useQuery({
    queryKey: ["ops-pipeline-executions-retrain"],
    queryFn: () => fetchExecutions('retrain'),
    refetchInterval: 10000,
  })

  const { data: tileDates, isLoading: tileDatesLoading } = useQuery({
    queryKey: ["ops-pipeline-tile-dates"],
    queryFn: () => fetchTileDates(365),
    enabled: activeTab === 'results',
  })

  const { data: predictionData, isLoading: predictionDataLoading, error: predictionError } = useQuery({
    queryKey: ["ops-pipeline-prediction-data", selectedPredDate],
    queryFn: () => selectedPredDate ? fetchPredictionData(selectedPredDate) : null,
    enabled: !!selectedPredDate && activeTab === 'results',
  })

  const { data: modelHistory, isLoading: modelHistoryLoading } = useQuery({
    queryKey: ["ops-pipeline-model-history"],
    queryFn: () => fetchModelHistory(30),
    enabled: activeTab === 'model-history',
  })

  const { data: selectedModelEntry, isLoading: selectedModelEntryLoading } = useQuery({
    queryKey: ["ops-pipeline-model-history-entry", selectedModelRefDate],
    queryFn: () => selectedModelRefDate ? fetchModelHistoryEntry(selectedModelRefDate) : null,
    enabled: !!selectedModelRefDate && activeTab === 'model-history',
  })

  const { data: runs, isLoading: runsLoading } = useQuery({
    queryKey: ["ops-pipeline-runs"],
    queryFn: () => fetchRuns(90),
    enabled: activeTab === 'daily-status',
  })

  const { data: selectedRun, isLoading: selectedRunLoading } = useQuery({
    queryKey: ["ops-pipeline-run-report", selectedRunDate],
    queryFn: () => selectedRunDate ? fetchRunReport(selectedRunDate) : null,
    enabled: !!selectedRunDate && activeTab === 'daily-status',
  })

  // Mutations
  const triggerRetrainMutation = useMutation({
    mutationFn: () => triggerJob('retrain'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["ops-pipeline-executions-retrain"] })
    }
  })

  // Check for running retrain job
  const hasRunningRetrain = retrainExecs?.executions?.some(e => getExecutionStatus(e) === 'running')

  // Health checks - only show critical alerts
  const latestRun = summary?.latest_run_report
  const healthAlerts = [
    { condition: latestRun?.success === false, message: "Latest pipeline run failed" },
    { condition: (latestRun?.details?.feature_partitions?.aod?.missing_rate ?? 0) > 0.9, message: "AOD missing rate > 90%" },
    { condition: (latestRun?.details?.master_partition?.total_missing_rate ?? 0) > 0.3, message: "Master partition missing rate > 30%" },
  ].filter(a => a.condition)

  return (
    <div className="space-y-4">
      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <nav className="flex space-x-6">
          {[
            { id: 'overview', name: 'Overview' },
            { id: 'model-history', name: 'Model History' },
            { id: 'executions', name: 'Executions' },
            { id: 'daily-status', name: 'Daily Status' },
            { id: 'features', name: 'Features' },
            { id: 'results', name: 'Results' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as TabType)}
              className={`py-2 px-1 border-b-2 font-medium text-xs transition-colors ${
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
            <HealthAlert key={i} message={alert.message} />
          ))}
        </div>
      )}

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <OverviewTab
          summary={summary}
          summaryLoading={summaryLoading}
          triggerRetrainMutation={triggerRetrainMutation}
          hasRunningRetrain={hasRunningRetrain || false}
        />
      )}

      {activeTab === 'model-history' && (
        <ModelHistoryTab
          history={modelHistory}
          historyLoading={modelHistoryLoading}
          selectedRefDate={selectedModelRefDate}
          setSelectedRefDate={setSelectedModelRefDate}
          selectedEntry={selectedModelEntry}
          selectedEntryLoading={selectedModelEntryLoading}
        />
      )}

      {activeTab === 'features' && (
        <FeaturesTab
          featuresList={featuresList}
          featuresListLoading={featuresListLoading}
          selectedFeature={selectedFeature}
          setSelectedFeature={setSelectedFeature}
          featureDates={featureDates}
          featureDatesLoading={featureDatesLoading}
          selectedFeatureDate={selectedFeatureDate}
          setSelectedFeatureDate={setSelectedFeatureDate}
        />
      )}

      {activeTab === 'executions' && (
        <ExecutionsTab
          dailyExecs={dailyExecs}
          dailyExecsLoading={dailyExecsLoading}
          retrainExecs={retrainExecs}
        />
      )}

      {activeTab === 'daily-status' && (
        <DailyStatusTab
          runs={runs}
          runsLoading={runsLoading}
          selectedRunDate={selectedRunDate}
          setSelectedRunDate={setSelectedRunDate}
          selectedRun={selectedRun}
          selectedRunLoading={selectedRunLoading}
        />
      )}

      {activeTab === 'results' && (
        <ResultsTab
          tileDates={tileDates}
          tileDatesLoading={tileDatesLoading}
          selectedPredDate={selectedPredDate}
          setSelectedPredDate={setSelectedPredDate}
          predictionData={predictionData}
          predictionDataLoading={predictionDataLoading}
          predictionError={predictionError as Error | null}
        />
      )}
    </div>
  )
}
