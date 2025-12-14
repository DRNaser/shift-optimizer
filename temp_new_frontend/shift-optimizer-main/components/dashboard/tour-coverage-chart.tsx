"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip } from "recharts"

const data = [
  { time: "06:00", covered: 45, total: 52 },
  { time: "08:00", covered: 78, total: 85 },
  { time: "10:00", covered: 120, total: 130 },
  { time: "12:00", covered: 95, total: 100 },
  { time: "14:00", covered: 110, total: 115 },
  { time: "16:00", covered: 88, total: 95 },
  { time: "18:00", covered: 65, total: 70 },
  { time: "20:00", covered: 30, total: 35 },
]

export function TourCoverageChart() {
  return (
    <Card className="bg-card border-border col-span-2">
      <CardHeader>
        <CardTitle className="text-card-foreground">Tour Coverage</CardTitle>
        <p className="text-sm text-muted-foreground">Tours covered vs total tours by time of day</p>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="coveredGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="oklch(0.72 0.15 175)" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="oklch(0.72 0.15 175)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" stroke="oklch(0.65 0 0)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="oklch(0.65 0 0)" fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "oklch(0.17 0.01 250)",
                  border: "1px solid oklch(0.28 0.01 250)",
                  borderRadius: "8px",
                  color: "oklch(0.95 0 0)",
                }}
              />
              <Area
                type="monotone"
                dataKey="total"
                stroke="oklch(0.45 0 0)"
                fill="transparent"
                strokeWidth={2}
                strokeDasharray="5 5"
              />
              <Area
                type="monotone"
                dataKey="covered"
                stroke="oklch(0.72 0.15 175)"
                fill="url(#coveredGradient)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
