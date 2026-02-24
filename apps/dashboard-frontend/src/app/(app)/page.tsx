"use client";

import { InteractiveRegionalMap } from '@/components/dashboard/InteractivePakistanMap'
import { YearOverYearChart } from '@/components/charts/YearOverYearChart'
import { HeatmapChart } from '@/components/charts/HeatmapChart'

export default function AQIDashboard() {
  return (
    <div className="flex flex-col">
      {/* Full-bleed Map Hero */}
      <InteractiveRegionalMap />

      {/* Section: Year-over-Year PM2.5 Trends */}
      <section className="border-t border-slate-200">
        <div className="bg-white">
          <YearOverYearChart />
        </div>
      </section>

      {/* Section: PM2.5 Calendar Heatmap */}
      <section className="border-t border-slate-200">
        <div className="bg-slate-50">
          <HeatmapChart />
        </div>
      </section>
    </div>
  )
}
