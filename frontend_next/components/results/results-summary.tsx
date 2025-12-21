"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { CheckCircle2, XCircle, AlertTriangle, Loader2 } from "lucide-react"
import { SolveResponse } from "@/lib/api"

export function ResultsSummary() {
  const [result, setResult] = useState<SolveResponse | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Read from sessionStorage
    const stored = sessionStorage.getItem('solveResult')
    if (stored) {
      try {
        setResult(JSON.parse(stored))
      } catch (e) {
        console.error('Failed to parse solve result:', e)
      }
    }
    setLoading(false)
  }, [])

  if (loading) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </CardContent>
      </Card>
    )
  }

  if (!result) {
    return (
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-card-foreground">Optimization Results</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 p-3 bg-secondary rounded-lg">
            <AlertTriangle className="h-5 w-5 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No results yet. Run an optimization first.</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  const stats = result.stats
  const validation = result.validation
  const totalTours = stats.total_tours_input || 0
  const coveredTours = stats.total_tours_assigned || 0
  const uncoveredTours = totalTours - coveredTours
  const coverage = totalTours > 0 ? (coveredTours / totalTours) * 100 : 0
  const totalDrivers = stats.total_drivers || 0
  const avgHours = stats.average_driver_utilization || 0

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Optimization Results</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Status */}
        <div className="flex items-center gap-2 p-3 bg-primary/10 rounded-lg">
          <CheckCircle2 className="h-5 w-5 text-primary" />
          <div>
            <p className="text-sm font-medium text-foreground">Status: {result.status}</p>
            <p className="text-xs text-muted-foreground">Version: {result.version}</p>
          </div>
        </div>

        {/* Coverage */}
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Tour Coverage</span>
            <span className="text-foreground font-medium">{coverage.toFixed(1)}%</span>
          </div>
          <Progress value={coverage} className="h-3 bg-secondary [&>div]:bg-primary" />
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>{coveredTours} covered</span>
            <span>{uncoveredTours} uncovered</span>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-foreground">{totalDrivers}</p>
            <p className="text-xs text-muted-foreground">Total Drivers</p>
          </div>
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-primary">{coveredTours}</p>
            <p className="text-xs text-muted-foreground">Tours Assigned</p>
          </div>
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-foreground">{Object.values(stats.block_counts || {}).reduce((a, b) => a + b, 0)}</p>
            <p className="text-xs text-muted-foreground">Total Blocks</p>
          </div>
          <div className="p-3 bg-secondary rounded-lg">
            <p className="text-2xl font-bold text-foreground">{avgHours.toFixed(1)}h</p>
            <p className="text-xs text-muted-foreground">Avg Hours/Driver</p>
          </div>
        </div>

        {/* Constraints Check */}
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">Constraint Validation</p>
          <div className="space-y-2">
            {validation.is_valid ? (
              <div className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                <span className="text-foreground">All constraints satisfied</span>
              </div>
            ) : (
              <>
                {validation.hard_violations.map((v, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <XCircle className="h-4 w-4 text-destructive" />
                    <span className="text-foreground">{v}</span>
                  </div>
                ))}
              </>
            )}
            {validation.warnings.map((w, i) => (
              <div key={i} className="flex items-center gap-2 text-sm">
                <AlertTriangle className="h-4 w-4 text-chart-3" />
                <span className="text-foreground">{w}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Block Mix */}
        {stats.block_mix && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-foreground">Block Mix</p>
            <div className="grid grid-cols-3 gap-2">
              {Object.entries(stats.block_mix).map(([type, pct]) => (
                <div key={type} className="p-2 bg-secondary rounded text-center">
                  <p className="text-lg font-bold text-foreground">{((pct as number) * 100).toFixed(0)}%</p>
                  <p className="text-xs text-muted-foreground">{type}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
