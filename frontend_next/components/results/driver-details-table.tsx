"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import { Search } from "lucide-react"
import { cn } from "@/lib/utils"

interface DriverRow {
  id: string
  name: string
  blocks: number
  tours: number
  hours: number
  daysWorked: number
  status: "optimal" | "warning" | "error"
}

const drivers: DriverRow[] = Array.from({ length: 80 }, (_, i) => {
  const hours = 42 + Math.floor(Math.random() * 12)
  const blocks = Math.floor(hours / 4)
  const tours = blocks * 2
  return {
    id: `DRV-${String(i + 1).padStart(3, "0")}`,
    name: `Driver ${i + 1}`,
    blocks,
    tours,
    hours,
    daysWorked: Math.floor(Math.random() * 2) + 4,
    status: hours < 42 ? "error" : hours > 51 ? "warning" : "optimal",
  }
})

export function DriverDetailsTable() {
  const [search, setSearch] = useState("")

  const filteredDrivers = drivers.filter(
    (d) => d.id.toLowerCase().includes(search.toLowerCase()) || d.name.toLowerCase().includes(search.toLowerCase()),
  )

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
              {filteredDrivers.slice(0, 20).map((driver) => (
                <TableRow key={driver.id} className="border-border hover:bg-secondary/50">
                  <TableCell>
                    <div>
                      <p className="font-mono text-sm text-foreground">{driver.id}</p>
                      <p className="text-xs text-muted-foreground">{driver.name}</p>
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
