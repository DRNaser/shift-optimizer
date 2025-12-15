"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { CheckCircle2, Loader2, Circle } from "lucide-react"
import { cn } from "@/lib/utils"

interface SolveProgressProps {
  isRunning: boolean
  isComplete?: boolean
}

interface PhaseStatus {
  name: string
  description: string
}

const phases: PhaseStatus[] = [
  { name: "Block Generation", description: "Creating candidate blocks from tours" },
  { name: "Phase 1: CP-SAT", description: "Selecting optimal block combination" },
  { name: "Phase 2: Greedy", description: "Assigning blocks to drivers" },
  { name: "Validation", description: "Checking constraints and coverage" },
]

export function SolveProgress({ isRunning, isComplete }: SolveProgressProps) {
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Solve Progress</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Overall Progress</span>
            <span className="text-foreground font-medium">
              {isComplete ? "100%" : isRunning ? "Running..." : "Ready"}
            </span>
          </div>
          <Progress
            value={isComplete ? 100 : isRunning ? 50 : 0}
            className="h-2 bg-secondary [&>div]:bg-primary"
          />
        </div>

        <div className="space-y-4">
          {phases.map((phase) => (
            <div key={phase.name} className="space-y-2">
              <div className="flex items-center gap-2">
                {isComplete ? (
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                ) : isRunning ? (
                  <Loader2 className="h-4 w-4 text-primary animate-spin" />
                ) : (
                  <Circle className="h-4 w-4 text-muted-foreground" />
                )}
                <span
                  className={cn(
                    "text-sm font-medium",
                    !isRunning && !isComplete ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {phase.name}
                </span>
              </div>
              <p className="text-xs text-muted-foreground ml-6">{phase.description}</p>
            </div>
          ))}
        </div>

        {isRunning && (
          <div className="pt-4 border-t border-border">
            <p className="text-xs text-muted-foreground text-center">
              Optimization in progress. This may take a few moments...
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
