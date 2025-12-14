import { AppSidebar } from "@/components/app-sidebar"
import { AppHeader } from "@/components/app-header"
import { KpiCard } from "@/components/kpi-card"
import { TourCoverageChart } from "@/components/dashboard/tour-coverage-chart"
import { DriverUtilizationChart } from "@/components/dashboard/driver-utilization-chart"
import { RecentJobsTable } from "@/components/dashboard/recent-jobs-table"
import { BlockMixChart } from "@/components/dashboard/block-mix-chart"
import { Truck, Users, CheckCircle2, Clock } from "lucide-react"

export default function DashboardPage() {
  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1 ml-64">
        <AppHeader title="Dashboard" />
        <div className="p-6 space-y-6">
          {/* KPI Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard title="Total Tours" value="682" change="+12 from yesterday" changeType="positive" icon={Truck} />
            <KpiCard title="Active Drivers" value="80" change="2 on leave" changeType="neutral" icon={Users} />
            <KpiCard
              title="Coverage Rate"
              value="98.2%"
              change="+0.4% vs last week"
              changeType="positive"
              icon={CheckCircle2}
            />
            <KpiCard
              title="Avg. Solve Time"
              value="4.2s"
              change="-0.8s improvement"
              changeType="positive"
              icon={Clock}
            />
          </div>

          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <TourCoverageChart />
            <BlockMixChart />
          </div>

          {/* Bottom Row */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <RecentJobsTable />
            <DriverUtilizationChart />
          </div>
        </div>
      </main>
    </div>
  )
}
