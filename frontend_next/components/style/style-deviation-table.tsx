"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, Minus } from "lucide-react"

const deviations = [
  { feature: "Early Morning Blocks (5-7am)", manual: "12%", automated: "8%", diff: -4, trend: "down" },
  { feature: "Late Evening Blocks (8-10pm)", manual: "10%", automated: "14%", diff: 4, trend: "up" },
  { feature: "Single-Tour Blocks", manual: "38%", automated: "35%", diff: -3, trend: "down" },
  { feature: "3-Tour Blocks", manual: "20%", automated: "20%", diff: 0, trend: "neutral" },
  { feature: "Weekend Coverage", manual: "85%", automated: "92%", diff: 7, trend: "up" },
  { feature: "Avg Gap Duration", manual: "45min", automated: "52min", diff: 7, trend: "up" },
  { feature: "Peak Hour Density", manual: "68%", automated: "72%", diff: 4, trend: "up" },
]

export function StyleDeviationTable() {
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Style Deviation Analysis</CardTitle>
        <p className="text-sm text-muted-foreground">Differences between manual and automated scheduling</p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <TableHead className="text-muted-foreground">Feature</TableHead>
              <TableHead className="text-muted-foreground text-right">Manual</TableHead>
              <TableHead className="text-muted-foreground text-right">Automated</TableHead>
              <TableHead className="text-muted-foreground text-right">Diff</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {deviations.map((row) => (
              <TableRow key={row.feature} className="border-border hover:bg-secondary/50">
                <TableCell className="text-foreground font-medium">{row.feature}</TableCell>
                <TableCell className="text-right text-muted-foreground">{row.manual}</TableCell>
                <TableCell className="text-right text-foreground">{row.automated}</TableCell>
                <TableCell className="text-right">
                  <Badge
                    variant="secondary"
                    className={cn(
                      "border-0 gap-1",
                      row.trend === "up" && "bg-primary/20 text-primary",
                      row.trend === "down" && "bg-chart-2/20 text-chart-2",
                      row.trend === "neutral" && "bg-secondary text-muted-foreground",
                    )}
                  >
                    {row.trend === "up" && <TrendingUp className="h-3 w-3" />}
                    {row.trend === "down" && <TrendingDown className="h-3 w-3" />}
                    {row.trend === "neutral" && <Minus className="h-3 w-3" />}
                    {row.diff > 0 ? `+${row.diff}` : row.diff}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
