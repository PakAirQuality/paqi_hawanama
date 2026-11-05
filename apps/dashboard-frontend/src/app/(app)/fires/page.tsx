'use client'

import { Suspense, useEffect, useMemo } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { pktToday, shiftDateOnly } from '@/lib/time'
import {
  fetchCities, fetchCityOutlook, fetchDistricts, fetchExposure, fetchFiresMeta, fetchPersistent, fetchPm25Link, fetchSeasons, fetchSplit, retryServerErrorsOnly,
} from '@/components/fires/api'
import { CardShell } from '@/components/fires/CardShell'
import { RegionChips } from '@/components/fires/RegionChips'
import { SeasonToggle } from '@/components/fires/SeasonToggle'
import { Headline } from '@/components/fires/Headline'
import { SeasonCurves } from '@/components/fires/SeasonCurves'
import { DistrictTable } from '@/components/fires/DistrictTable'
import { BorderSplit } from '@/components/fires/BorderSplit'
import { PersistentSources } from '@/components/fires/PersistentSources'
import { CityExposure } from '@/components/fires/CityExposure'
import { FirePm25Chart } from '@/components/fires/FirePm25Chart'
import { DataNotes } from '@/components/fires/DataNotes'
import { SmokeOutlook } from '@/components/fires/SmokeOutlook'
import { districtScope, regionLabel } from '@/components/fires/regions'
import { useFiresParams } from '@/components/fires/useFiresParams'

export default function FiresPage() {
  return (
    <Suspense fallback={<div className="mx-auto max-w-6xl"><div className="skeleton h-40 rounded-2xl" /></div>}>
      <FiresPageInner />
    </Suspense>
  )
}

function FiresPageInner() {
  const meta = useQuery({ queryKey: ['fires', 'meta'], queryFn: fetchFiresMeta, staleTime: 60 * 60 * 1000, retry: retryServerErrorsOnly })
  const { params, set } = useFiresParams(meta.data?.districts)
  const { region, season, date } = params
  const label = regionLabel(region, meta.data?.districts)
  const yesterday = shiftDateOnly(pktToday(), -1)

  useEffect(() => { document.title = 'Fire trends: Pakistan and the cross-border burning season | Hawanama' }, [])

  const seasons = useQuery({ queryKey: ['fires', 'seasons', region, season], queryFn: () => fetchSeasons(region, season),
    placeholderData: keepPreviousData, retry: retryServerErrorsOnly })
  const scope = districtScope(region)
  const districts = useQuery({ queryKey: ['fires', 'districts', season, scope], queryFn: () => fetchDistricts(season, scope ?? 'pakistan'),
    enabled: scope != null, placeholderData: keepPreviousData, retry: retryServerErrorsOnly })
  const split = useQuery({ queryKey: ['fires', 'split', season], queryFn: () => fetchSplit(season), placeholderData: keepPreviousData, retry: retryServerErrorsOnly })
  const persistent = useQuery({ queryKey: ['fires', 'persistent', region], queryFn: () => fetchPersistent(region), placeholderData: keepPreviousData, retry: retryServerErrorsOnly })
  const cities = useQuery({ queryKey: ['fires', 'cities'], queryFn: fetchCities, staleTime: 60 * 60 * 1000, retry: retryServerErrorsOnly })
  const cityList = useMemo(() => cities.data?.cities ?? [], [cities.data])
  const city = useMemo(() => {
    if (params.city) return params.city
    return cityList.find(c => c.name === 'Lahore')?.name ?? cityList[0]?.name ?? ''
  }, [params.city, cityList])
  const exposure = useQuery({ queryKey: ['fires', 'exposure', city, date], queryFn: () => fetchExposure(city, date), enabled: !!city,
    placeholderData: keepPreviousData, retry: retryServerErrorsOnly })
  const link = useQuery({ queryKey: ['fires', 'pm25link', city, date], queryFn: () => fetchPm25Link(city, date), enabled: !!city,
    placeholderData: keepPreviousData, retry: retryServerErrorsOnly })
  const outlook = useQuery({ queryKey: ['fires', 'outlook', city], queryFn: () => fetchCityOutlook(city), enabled: !!city,
    placeholderData: keepPreviousData, retry: retryServerErrorsOnly })

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Fire trends</p>
          <p className="text-[12px] text-slate-500">Crop-residue burning across Pakistan and the Indian plains, from NASA FIRMS satellite detections since 2020.</p>
        </div>
        <SeasonToggle value={season} onChange={s => set({ season: s })} />
      </div>
      <RegionChips value={region} onChange={r => set({ region: r })} districts={meta.data?.districts} />

      <CardShell id="season" isLoading={seasons.isPending} error={seasons.error} onRetry={() => seasons.refetch()} skeletonHeight={420}>
        {seasons.data && (
          <div className="space-y-5">
            <Headline data={seasons.data} regionLabel={label} />
            <SeasonCurves data={seasons.data} />
          </div>
        )}
      </CardShell>

      <div>
        <h2 className="mb-2 text-[15px] font-semibold tracking-tight text-slate-900">Where it burns</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="lg:row-span-2">
            <CardShell id="districts" title="Districts" subtitle={scope == null ? undefined : `${label === 'Pakistan' || label === 'Whole box' ? 'Pakistan' : label}, season to date`}
              isLoading={scope != null && districts.isPending} error={districts.error} onRetry={() => districts.refetch()} skeletonHeight={420}>
              {scope == null ? <p className="text-[13px] text-slate-600">District tables cover Pakistan only; pick Pakistan or a province.</p>
                : districts.data && <DistrictTable data={districts.data} date={date} />}
            </CardShell>
          </div>
          <CardShell id="split" title="Across the border" subtitle="Fires a day by country, whole season" isLoading={split.isPending} error={split.error} onRetry={() => split.refetch()} skeletonHeight={260}>
            {split.data && <BorderSplit data={split.data} />}
          </CardShell>
          <CardShell id="persistent" title="Persistent sources" subtitle="Cells burning on many of the last 30 days" isLoading={persistent.isPending} error={persistent.error} onRetry={() => persistent.refetch()} skeletonHeight={200}>
            {persistent.data && <PersistentSources data={persistent.data} date={yesterday} />}
          </CardShell>
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-[15px] font-semibold tracking-tight text-slate-900">Smoke and cities</h2>
        <div className="mb-4">
          <CardShell id="outlook" title={`Smoke outlook for ${city || 'the city'}`} subtitle="Forecast wind × the fires seen in the last two days, for today and the next three days"
            isLoading={!!city && outlook.isPending} error={outlook.error} onRetry={() => outlook.refetch()} skeletonHeight={160}>
            {outlook.data && <SmokeOutlook data={outlook.data} today={pktToday()} />}
          </CardShell>
        </div>
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <CardShell id="exposure" title="Fires around a city" subtitle="One Pakistan day: rings by country, wind, and the upwind cone"
            isLoading={cities.isPending || (!!city && exposure.isPending)} error={cities.error ?? exposure.error} onRetry={() => { cities.refetch(); exposure.refetch() }} skeletonHeight={360}>
            <CityExposure cities={cityList} city={city} date={date} maxDate={yesterday} onCity={c => set({ city: c })} onDate={d => set({ date: d })} data={exposure.data} />
          </CardShell>
          <CardShell id="link" title={`Fires and PM2.5 in ${city || 'the city'}`} subtitle="Last 60 days: upwind fire intensity against the city's daily PM2.5"
            isLoading={!!city && link.isPending} error={link.error} onRetry={() => link.refetch()} skeletonHeight={360}>
            {link.data && <FirePm25Chart data={link.data} />}
          </CardShell>
        </div>
      </div>

      <DataNotes meta={meta.data} season={season} />
    </div>
  )
}
