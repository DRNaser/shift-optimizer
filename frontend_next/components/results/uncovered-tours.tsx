"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { AlertTriangle } from "lucide-react"

const uncoveredTours = [
  { id: "T-1042", day: "Mon", time: "05:30-07:00", reason: "Early morning slot" },
  { id: "T-1156", day: "Mon", time: "21:00-22:30", reason: "Late evening slot" },
  { id: "T-2089", day: "Tue", time: "05:45-07:15", reason: "Early morning slot" },
  { id: "T-3201", day: "Wed", time: "21:30-23:00", reason: "Late evening slot" },
  { id: "T-4055", day: "Thu", time: "05:15-06:45", reason: "Early morning slot" },
  { id: "T-4312", day: "Thu", time: "13:00-14:30", reason: "Isolated time slot" },
  { id: "T-5178", day: "Fri", time: "21:15-22:45", reason: "Late evening slot" },
  { id: "T-6022", day: "Sat", time: "05:00-06:30", reason: "Early morning slot" },
  { id: "T-6089", day: "Sat", time: "22:00-23:30", reason: "Late evening slot" },
  { id: "T-7015", day: "Sun", time: "05:30-07:00", reason: "Early morning slot" },
  { id: "T-7102", day: "Sun", time: "12:30-14:00", reason: "Isolated time slot" },
  { id: "T-7198", day: "Sun", time: "21:45-23:15", reason: "Late evening slot" },
]

export function UncoveredTours() {
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
