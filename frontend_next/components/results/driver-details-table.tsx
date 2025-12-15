"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Search, Loader2, AlertTriangle } from "lucide-react"
import { cn } from "@/lib/utils"
import { SolveResponse } from "@/lib/api"

interface DriverRow {
  id: string
  name: string
  blocks: number
  tours: number
  hours: number
  daysWorked: number
  status: "optimal" | "warning" | "error"
}

export function DriverDetailsTable() {
  const [search, setSearch] = useState("")
  const [drivers, setDrivers] = useState<DriverRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const stored = sessionStorage.getItem('solveResult')
    if (stored) {
      try {
        const result: SolveResponse = JSON.parse(stored)
        // Group assignments by driver
        const driverMap = new Map<string, { blocks: number; tours: number; hours: number; days: Set<string> }>()

        for (const assignment of result.assignments) {
          const existing = driverMap.get(assignment.driver_id) || { blocks: 0, tours: 0, hours: 0, days: new Set<string>() }
          existing.blocks += 1
          existing.tours += assignment.block.tours.length
          existing.hours += assignment.block.total_work_hours
          existing.days.add(assignment.day)
          driverMap.set(assignment.driver_id, existing)
        }

        const driverRows: DriverRow[] = Array.from(driverMap.entries()).map(([id, data]) => ({
          id,
          name: id,
          blocks: data.blocks,
          tours: data.tours,
          hours: Math.round(data.hours * 10) / 10,
          daysWorked: data.days.size,
          status: data.hours < 42 ? "error" : data.hours > 51 ? "warning" : "optimal",
        }))

        setDrivers(driverRows)
      } catch (e) {
        console.error('Failed to parse solve result:', e)
      }
    }
    setLoading(false)
  }, [])

  const filteredDrivers = drivers.filter(
    (d) => d.id.toLowerCase().includes(search.toLowerCase()) || d.name.toLowerCase().includes(search.toLowerCase()),
  )

  if (loading) {
    return (
      <Card className="bg-card border-border">
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </CardContent>
      </Card>
    )
  }

  if (drivers.length === 0) {
    return (
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-card-foreground">Driver Assignments</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 p-3 bg-secondary rounded-lg">
            <AlertTriangle className="h-5 w-5 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No driver assignments yet. Run an optimization first.</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Driver Assignments</CardTitle>
        <div className="relative mt-2">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search drivers..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9 bg-secondary border-border text-foreground"
          />
        </div>
      </CardHeader>
      <CardContent>
        <div className="max-h-[400px] overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="text-muted-foreground">Driver ID</TableHead>
                <TableHead className="text-muted-foreground">Blocks</TableHead>
                <TableHead className="text-muted-foreground">Tours</TableHead>
                <TableHead className="text-muted-foreground">Hours</TableHead>
                <TableHead className="text-muted-foreground">Days</TableHead>
                <TableHead className="text-muted-foreground">Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredDrivers.map((driver) => (
                <TableRow key={driver.id} className="border-border hover:bg-secondary/50">
                  <TableCell>
                    <div>
                      <p className="font-mono text-sm text-foreground">{driver.id}</p>
                    </div>
                  </TableCell>
                  <TableCell className="text-foreground">{driver.blocks}</TableCell>
                  <TableCell className="text-foreground">{driver.tours}</TableCell>
                  <TableCell
                    className={cn(
                      "font-medium",
                      driver.status === "optimal"
                        ? "text-primary"
                        : driver.status === "warning"
                          ? "text-chart-3"
                          : "text-destructive",
                    )}
                  >
                    {driver.hours}h
                  </TableCell>
                  <TableCell className="text-foreground">{driver.daysWorked}</TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className={cn(
                        "border-0",
                        driver.status === "optimal" && "bg-primary/20 text-primary",
                        driver.status === "warning" && "bg-chart-3/20 text-chart-3",
                        driver.status === "error" && "bg-destructive/20 text-destructive",
                      )}
                    >
                      {driver.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
