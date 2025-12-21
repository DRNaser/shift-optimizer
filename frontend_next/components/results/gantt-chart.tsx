"use client"

import { useState, useEffect } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Button } from "@/components/ui/button"
import { ChevronLeft, ChevronRight, Loader2, AlertTriangle } from "lucide-react"
import { cn } from "@/lib/utils"
import { SolveResponse } from "@/lib/api"

interface Block {
  id: string
  tours: number
  start: number
  end: number
  day: number
}

interface Driver {
  id: string
  name: string
  blocks: Block[]
  totalHours: number
}

const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
const dayMap: Record<string, number> = {
  "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3,
  "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6,
  "Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6
}
const hours = Array.from({ length: 16 }, (_, i) => i + 6) // 6am to 10pm

export function GanttChart() {
  const [selectedDay, setSelectedDay] = useState<string>("all")
  const [page, setPage] = useState(0)
  const [drivers, setDrivers] = useState<Driver[]>([])
  const [loading, setLoading] = useState(true)
  const driversPerPage = 10

  useEffect(() => {
    const stored = sessionStorage.getItem('solveResult')
    if (stored) {
      try {
        const result: SolveResponse = JSON.parse(stored)
        // Group assignments by driver
        const driverMap = new Map<string, Driver>()

        for (const assignment of result.assignments) {
          const driverId = assignment.driver_id
          if (!driverMap.has(driverId)) {
            driverMap.set(driverId, {
              id: driverId,
              name: driverId,
              blocks: [],
              totalHours: 0
            })
          }

          const driver = driverMap.get(driverId)!
          const block = assignment.block

          // Parse start/end times
          const startParts = block.tours[0]?.start_time?.split(":") || ["0", "0"]
          const endParts = block.tours[block.tours.length - 1]?.end_time?.split(":") || ["0", "0"]
          const start = parseInt(startParts[0]) + parseInt(startParts[1]) / 60
          const end = parseInt(endParts[0]) + parseInt(endParts[1]) / 60

          driver.blocks.push({
            id: block.id,
            tours: block.tours.length,
            start: start,
            end: end,
            day: dayMap[assignment.day] ?? 0
          })
          driver.totalHours += block.total_work_hours || (end - start)
        }

        setDrivers(Array.from(driverMap.values()))
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

  if (drivers.length === 0) {
    return (
      <Card className="bg-card border-border">
        <CardHeader>
          <CardTitle className="text-card-foreground">Driver Schedule</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 p-3 bg-secondary rounded-lg">
            <AlertTriangle className="h-5 w-5 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No schedule data yet. Run an optimization first.</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  const filteredDrivers = drivers.slice(page * driversPerPage, (page + 1) * driversPerPage)

  return (
    <Card className="bg-card border-border">
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle className="text-card-foreground">Driver Schedule</CardTitle>
          <p className="text-sm text-muted-foreground">Weekly block assignments per driver</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={selectedDay} onValueChange={setSelectedDay}>
            <SelectTrigger className="w-32 bg-secondary border-border text-foreground">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-card border-border">
              <SelectItem value="all">All Days</SelectItem>
              {days.map((day, i) => (
                <SelectItem key={day} value={i.toString()}>
                  {day}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="border-border bg-transparent hover:bg-secondary"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm text-muted-foreground px-2">
              {page + 1} / {Math.ceil(drivers.length / driversPerPage)}
            </span>
            <Button
              variant="outline"
              size="icon"
              onClick={() => setPage((p) => Math.min(Math.ceil(drivers.length / driversPerPage) - 1, p + 1))}
              disabled={page >= Math.ceil(drivers.length / driversPerPage) - 1}
              className="border-border bg-transparent hover:bg-secondary"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <div className="min-w-[1000px]">
            {/* Header */}
            <div className="flex border-b border-border pb-2 mb-2">
              <div className="w-32 flex-shrink-0 text-sm font-medium text-muted-foreground">Driver</div>
              <div className="flex-1 flex">
                {hours.map((hour) => (
                  <div key={hour} className="flex-1 text-xs text-muted-foreground text-center">
                    {hour}:00
                  </div>
                ))}
              </div>
              <div className="w-20 flex-shrink-0 text-sm font-medium text-muted-foreground text-right">Hours</div>
            </div>

            {/* Rows */}
            {filteredDrivers.map((driver) => {
              const dayBlocks =
                selectedDay === "all"
                  ? driver.blocks
                  : driver.blocks.filter((b) => b.day === Number.parseInt(selectedDay))

              return (
                <div key={driver.id} className="flex items-center py-2 border-b border-border/50 hover:bg-secondary/30">
                  <div className="w-32 flex-shrink-0">
                    <p className="text-sm font-medium text-foreground">{driver.id}</p>
                    <p className="text-xs text-muted-foreground">{driver.name}</p>
                  </div>
                  <div className="flex-1 relative h-8">
                    {dayBlocks.map((block) => {
                      const left = ((block.start - 6) / 16) * 100
                      const width = ((block.end - block.start) / 16) * 100
                      const colors = ["bg-chart-1", "bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5"]
                      const colorIndex = selectedDay === "all" ? block.day % 5 : 0

                      return (
                        <div
                          key={block.id}
                          className={cn(
                            "absolute h-6 top-1 rounded text-xs flex items-center justify-center text-primary-foreground font-medium",
                            colors[colorIndex],
                          )}
                          style={{ left: `${left}%`, width: `${width}%` }}
                          title={`${block.tours} tour(s), ${block.start}:00-${block.end}:00`}
                        >
                          {block.tours}T
                        </div>
                      )
                    })}
                  </div>
                  <div className="w-20 flex-shrink-0 text-right">
                    <span
                      className={cn(
                        "text-sm font-medium",
                        driver.totalHours >= 42 && driver.totalHours <= 53 ? "text-primary" : "text-destructive",
                      )}
                    >
                      {driver.totalHours}h
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
