"use client"

import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { CheckCircle2, Loader2, Circle } from "lucide-react"
import { cn } from "@/lib/utils"

interface SolveProgressProps {
  isRunning: boolean
  onComplete?: () => void
}

interface PhaseStatus {
  name: string
  description: string
  status: "pending" | "running" | "completed"
  progress: number
}

export function SolveProgress({ isRunning, onComplete }: SolveProgressProps) {
  const [phases, setPhases] = useState<PhaseStatus[]>([
    { name: "Block Generation", description: "Creating candidate blocks from tours", status: "pending", progress: 0 },
    { name: "Phase 1: CP-SAT", description: "Selecting optimal block combination", status: "pending", progress: 0 },
    { name: "Phase 2: Greedy", description: "Assigning blocks to drivers", status: "pending", progress: 0 },
    { name: "Validation", description: "Checking constraints and coverage", status: "pending", progress: 0 },
  ])
  const [currentPhase, setCurrentPhase] = useState(0)
  const [stats, setStats] = useState({ blocks: 0, selected: 0, assigned: 0 })

  useEffect(() => {
    if (!isRunning) {
      setPhases((p) => p.map((phase) => ({ ...phase, status: "pending", progress: 0 })))
      setCurrentPhase(0)
      setStats({ blocks: 0, selected: 0, assigned: 0 })
      return
    }

    const interval = setInterval(() => {
      setPhases((prev) => {
        const updated = [...prev]
        if (currentPhase < updated.length) {
          const phase = updated[currentPhase]
          if (phase.progress < 100) {
            phase.status = "running"
            phase.progress = Math.min(phase.progress + Math.random() * 15 + 5, 100)
            // Update stats based on phase
            if (currentPhase === 0) setStats((s) => ({ ...s, blocks: Math.floor(phase.progress * 300) }))
            if (currentPhase === 1) setStats((s) => ({ ...s, selected: Math.floor(phase.progress * 3.5) }))
            if (currentPhase === 2) setStats((s) => ({ ...s, assigned: Math.floor(phase.progress * 0.8) }))
          } else {
            phase.status = "completed"
            if (currentPhase < updated.length - 1) {
              setCurrentPhase((c) => c + 1)
            } else {
              onComplete?.()
            }
          }
        }
        return updated
      })
    }, 300)

    return () => clearInterval(interval)
  }, [isRunning, currentPhase, onComplete])

  const overallProgress = phases.reduce((acc, p) => acc + p.progress, 0) / phases.length

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Solve Progress</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Overall Progress</span>
            <span className="text-foreground font-medium">{Math.round(overallProgress)}%</span>
          </div>
          <Progress value={overallProgress} className="h-2 bg-secondary [&>div]:bg-primary" />
        </div>

        <div className="space-y-4">
          {phases.map((phase, index) => (
            <div key={phase.name} className="space-y-2">
              <div className="flex items-center gap-2">
                {phase.status === "completed" ? (
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                ) : phase.status === "running" ? (
                  <Loader2 className="h-4 w-4 text-primary animate-spin" />
                ) : (
                  <Circle className="h-4 w-4 text-muted-foreground" />
                )}
                <span
                  className={cn(
                    "text-sm font-medium",
                    phase.status === "pending" ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {phase.name}
                </span>
              </div>
              <p className="text-xs text-muted-foreground ml-6">{phase.description}</p>
              {phase.status === "running" && (
                <Progress value={phase.progress} className="h-1 ml-6 bg-secondary [&>div]:bg-primary" />
              )}
            </div>
          ))}
        </div>

        {isRunning && (
          <div className="grid grid-cols-3 gap-4 pt-4 border-t border-border">
            <div className="text-center">
              <p className="text-2xl font-bold text-foreground">{stats.blocks.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">Blocks Generated</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-primary">{stats.selected}</p>
              <p className="text-xs text-muted-foreground">Blocks Selected</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-foreground">{stats.assigned}</p>
              <p className="text-xs text-muted-foreground">Drivers Assigned</p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
