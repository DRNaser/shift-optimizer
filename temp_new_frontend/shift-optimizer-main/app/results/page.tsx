import { AppSidebar } from "@/components/app-sidebar"
import { AppHeader } from "@/components/app-header"
import { GanttChart } from "@/components/results/gantt-chart"
import { ResultsSummary } from "@/components/results/results-summary"
import { DriverDetailsTable } from "@/components/results/driver-details-table"
import { UncoveredTours } from "@/components/results/uncovered-tours"
import { Button } from "@/components/ui/button"
import { Download, Share2 } from "lucide-react"

export default function ResultsPage() {
  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1 ml-64">
        <AppHeader title="Results" />
        <div className="p-6 space-y-6">
          {/* Actions Bar */}
          <div className="flex justify-end gap-2">
            <Button variant="outline" className="border-border text-foreground hover:bg-secondary bg-transparent">
              <Share2 className="h-4 w-4 mr-2" />
              Share
            </Button>
            <Button className="bg-primary text-primary-foreground hover:bg-primary/90">
              <Download className="h-4 w-4 mr-2" />
              Export CSV
            </Button>
          </div>

          {/* Main Content */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
            {/* Gantt Chart - Full Width */}
            <div className="lg:col-span-3">
              <GanttChart />
            </div>

            {/* Summary Sidebar */}
            <div className="space-y-6">
              <ResultsSummary />
            </div>
          </div>

          {/* Bottom Row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <DriverDetailsTable />
            </div>
            <UncoveredTours />
          </div>
        </div>
      </main>
    </div>
  )
}
