"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { CheckCircle2, XCircle, AlertTriangle } from "lucide-react"

export function ResultsSummary() {
  const metrics = {
    totalTours: 682,
    coveredTours: 670,
    uncoveredTours: 12,
    totalDrivers: 80,
    assignedDrivers: 78,
    avgHoursPerDriver: 47.2,
    totalBlocks: 352,
    solveTime: 4.2,
  }

  const coverage = (metrics.coveredTours / metrics.totalTours) * 100

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Optimization Results</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Coverage */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Tour Coverage</span>
            <span className="text-foreground font-medium">{coverage.toFixed(1)}%</span>
          </div>
          <Progress value={coverage} className="h-3 bg-secondary [&>div]:bg-primary" />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{metrics.coveredTours} covered</span>
            <span>{metrics.uncoveredTours} uncovered</span>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-foreground">{metrics.totalDrivers}</p>
            <p className="text-xs text-muted-foreground">Total Drivers</p>
          </div>
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-primary">{metrics.assignedDrivers}</p>
            <p className="text-xs text-muted-foreground">Assigned</p>
          </div>
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-foreground">{metrics.totalBlocks}</p>
            <p className="text-xs text-muted-foreground">Total Blocks</p>
          </div>
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-foreground">{metrics.avgHoursPerDriver}h</p>
            <p className="text-xs text-muted-foreground">Avg Hours/Driver</p>
          </div>
        </div>

        {/* Constraints Check */}
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">Constraint Validation</p>
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              <span className="text-foreground">All drivers within 42-53h range</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              <span className="text-foreground">No overlapping blocks</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <AlertTriangle className="h-4 w-4 text-chart-3" />
              <span className="text-foreground">12 tours uncovered (low priority)</span>
            </div>
            <div className="flex items-center gap-2 text-sm">
              <XCircle className="h-4 w-4 text-destructive" />
              <span className="text-foreground">2 drivers below minimum hours</span>
            </div>
          </div>
        </div>

        {/* Solve Time */}
        <div className="pt-4 border-t border-border">
          <div className="flex justify-between items-center">
            <span className="text-sm text-muted-foreground">Total Solve Time</span>
            <span className="text-lg font-bold text-primary">{metrics.solveTime}s</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
