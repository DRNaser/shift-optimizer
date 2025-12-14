import { AppSidebar } from "@/components/app-sidebar"
import { AppHeader } from "@/components/app-header"
import { BlockMixComparison } from "@/components/style/block-mix-comparison"
import { TimeDistributionChart } from "@/components/style/time-distribution-chart"
import { PolicyMetrics } from "@/components/style/policy-metrics"
import { StyleDeviationTable } from "@/components/style/style-deviation-table"
import { OverallStyleScore } from "@/components/style/overall-style-score"

export default function StylePage() {
  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1 ml-64">
        <AppHeader title="Style Analysis" />
        <div className="p-6 space-y-6">
          {/* Top Row - Score and Metrics */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            <OverallStyleScore />
            <div className="lg:col-span-3">
              <PolicyMetrics />
            </div>
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <BlockMixComparison />
            <TimeDistributionChart />
          </div>

          {/* Deviation Table */}
          <StyleDeviationTable />
        </div>
      </main>
    </div>
  )
}
