"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react"
import { SolveResponse } from "@/lib/api"

interface UncoveredTour {
  id: string
  day: string
  time: string
  reason: string
}

export function UncoveredTours() {
  const [uncoveredTours, setUncoveredTours] = useState<UncoveredTour[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const stored = sessionStorage.getItem('solveResult')
    if (stored) {
      try {
        const result: SolveResponse = JSON.parse(stored)
        // unassigned_tours from the response
        const unassigned = result.unassigned_tours || []
        const tours: UncoveredTour[] = unassigned.map((t: any) => ({
          id: t.id || 'Unknown',
          day: t.day || '',
          time: `${t.start_time || ''}-${t.end_time || ''}`,
          reason: 'Could not be assigned',
        }))
        setUncoveredTours(tours)
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

  if (uncoveredTours.length === 0) {
    return (
      <Card className="bg-card border-border">
        <CardHeader>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-primary" />
            <CardTitle className="text-card-foreground">All Tours Covered</CardTitle>
          </div>
          <p className="text-sm text-muted-foreground">All tours have been assigned to drivers</p>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-5 w-5 text-chart-3" />
          <CardTitle className="text-card-foreground">Uncovered Tours</CardTitle>
        </div>
        <p className="text-sm text-muted-foreground">{uncoveredTours.length} tours could not be assigned</p>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {uncoveredTours.map((tour) => (
            <div key={tour.id} className="flex items-center justify-between p-3 bg-secondary rounded-lg">
              <div className="flex items-center gap-3">
                <Badge variant="outline" className="border-border text-foreground font-mono">
                  {tour.id}
                </Badge>
                <div>
                  <p className="text-sm text-foreground">
                    {tour.day} {tour.time}
                  </p>
                  <p className="text-xs text-muted-foreground">{tour.reason}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
