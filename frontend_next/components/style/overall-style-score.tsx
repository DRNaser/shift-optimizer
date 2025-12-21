"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts"

const data = [
  { name: "Score", value: 89 },
  { name: "Remaining", value: 11 },
]

export function OverallStyleScore() {
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Overall Style Score</CardTitle>
        <p className="text-sm text-muted-foreground">Combined policy alignment rating</p>
      </CardHeader>
      <CardContent>
        <div className="h-[200px] relative">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={80}
                startAngle={90}
                endAngle={-270}
                dataKey="value"
              >
                <Cell fill="oklch(0.72 0.15 175)" />
                <Cell fill="oklch(0.22 0.01 250)" />
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="text-4xl font-bold text-primary">89</p>
              <p className="text-sm text-muted-foreground">out of 100</p>
            </div>
          </div>
        </div>
        <div className="mt-4 space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Previous Score</span>
            <span className="text-foreground font-medium">84</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Improvement</span>
            <span className="text-primary font-medium">+5 points</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
