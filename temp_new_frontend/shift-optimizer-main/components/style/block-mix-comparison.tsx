"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Bar, BarChart, ResponsiveContainer, XAxis, YAxis, Tooltip, Legend } from "recharts"

const data = [
  { type: "1-Tour", manual: 38, automated: 35, policy: 37 },
  { type: "2-Tour", manual: 42, automated: 45, policy: 44 },
  { type: "3-Tour", manual: 20, automated: 20, policy: 19 },
]

export function BlockMixComparison() {
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Block Mix Comparison</CardTitle>
        <p className="text-sm text-muted-foreground">Distribution by tour count across scheduling methods</p>
      </CardHeader>
      <CardContent>
        <div className="h-[300px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <XAxis dataKey="type" stroke="oklch(0.65 0 0)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="oklch(0.65 0 0)" fontSize={12} tickLine={false} axisLine={false} unit="%" />
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
              <Bar dataKey="manual" name="Manual" fill="oklch(0.65 0.18 280)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="automated" name="Automated" fill="oklch(0.72 0.15 175)" radius={[4, 4, 0, 0]} />
              <Bar dataKey="policy" name="Policy-guided" fill="oklch(0.75 0.15 85)" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  )
}
