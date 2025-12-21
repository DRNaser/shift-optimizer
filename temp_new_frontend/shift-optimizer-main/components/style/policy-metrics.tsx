"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"

const metrics = [
  { name: "Block Mix Similarity", value: 94, description: "How closely the block type distribution matches manual" },
  { name: "Time Preference Alignment", value: 88, description: "Match with preferred scheduling times" },
  { name: "Gap Duration Match", value: 91, description: "Similarity in breaks between blocks" },
  { name: "Weekly Hours Balance", value: 96, description: "Distribution of hours across the week" },
  { name: "Driver Preference Score", value: 82, description: "Alignment with historical driver patterns" },
]

export function PolicyMetrics() {
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Policy Alignment Metrics</CardTitle>
        <p className="text-sm text-muted-foreground">How well automated scheduling matches learned preferences</p>
      </CardHeader>
      <CardContent className="space-y-5">
        {metrics.map((metric) => (
          <div key={metric.name} className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-sm font-medium text-foreground">{metric.name}</span>
              <span className="text-sm font-bold text-primary">{metric.value}%</span>
            </div>
            <Progress value={metric.value} className="h-2 bg-secondary [&>div]:bg-primary" />
            <p className="text-xs text-muted-foreground">{metric.description}</p>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}
