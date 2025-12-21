"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Area, AreaChart, ResponsiveContainer, XAxis, YAxis, Tooltip, Legend } from "recharts"

const data = [
  { hour: "06:00", manual: 15, automated: 18, policy: 16 },
  { hour: "08:00", manual: 45, automated: 52, policy: 48 },
  { hour: "10:00", manual: 65, automated: 70, policy: 68 },
  { hour: "12:00", manual: 50, automated: 48, policy: 50 },
  { hour: "14:00", manual: 55, automated: 58, policy: 56 },
  { hour: "16:00", manual: 48, automated: 52, policy: 50 },
  { hour: "18:00", manual: 35, automated: 38, policy: 36 },
  { hour: "20:00", manual: 18, automated: 22, policy: 19 },
]

export function TimeDistributionChart() {
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Block Start Time Distribution</CardTitle>
        <p className="text-sm text-muted-foreground">When blocks typically start throughout the day</p>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="manualGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="oklch(0.65 0.18 280)" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="oklch(0.65 0.18 280)" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="automatedGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="oklch(0.72 0.15 175)" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="oklch(0.72 0.15 175)" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="hour" stroke="oklch(0.65 0 0)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="oklch(0.65 0 0)" fontSize={12} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "oklch(0.17 0.01 250)",
                  border: "1px solid oklch(0.28 0.01 250)",
                  borderRadius: "8px",
                  color: "oklch(0.95 0 0)",
                }}
              />
              <Legend
                wrapperStyle={{ color: "oklch(0.65 0 0)" }}
                formatter={(value) => <span className="text-muted-foreground text-sm">{value}</span>}
              />
              <Area
                type="monotone"
                dataKey="manual"
                name="Manual"
                stroke="oklch(0.65 0.18 280)"
                fill="url(#manualGradient)"
                strokeWidth={2}
              />
              <Area
                type="monotone"
                dataKey="automated"
                name="Automated"
                stroke="oklch(0.72 0.15 175)"
                fill="url(#automatedGradient)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
