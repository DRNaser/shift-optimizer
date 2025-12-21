"use client"

import { useState } from "react"
import { AppSidebar } from "@/components/app-sidebar"
import { AppHeader } from "@/components/app-header"
import { TourUpload } from "@/components/solve/tour-upload"
import { SolverConfig } from "@/components/solve/solver-config"
import { SolveProgress } from "@/components/solve/solve-progress"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Play, RotateCcw, CheckCircle2, AlertCircle } from "lucide-react"
import { useRouter } from "next/navigation"

export default function SolvePage() {
  const router = useRouter()
  const [tourCount, setTourCount] = useState(0)
  const [isRunning, setIsRunning] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [config, setConfig] = useState({
    minHours: 42,
    maxHours: 53,
    maxGap: 90,
    usePolicy: true,
    policyWeight: 60,
    timeLimit: 60,
  })

  const handleStartSolve = () => {
    setIsRunning(true)
    setIsComplete(false)
  }

  const handleComplete = () => {
    setIsRunning(false)
    setIsComplete(true)
  }

  const handleReset = () => {
    setIsRunning(false)
    setIsComplete(false)
  }

  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1 ml-64">
        <AppHeader title="Solve" />
        <div className="p-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Left Column - Upload and Config */}
            <div className="lg:col-span-2 space-y-6">
              <TourUpload onToursLoaded={setTourCount} />
              <SolverConfig config={config} onConfigChange={setConfig} />
            </div>

            {/* Right Column - Progress and Actions */}
            <div className="space-y-6">
              <SolveProgress isRunning={isRunning} onComplete={handleComplete} />

              <Card className="bg-card border-border">
                <CardHeader>
                  <CardTitle className="text-card-foreground">Actions</CardTitle>
                  <CardDescription>Start or manage the optimization</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {isComplete ? (
                    <div className="space-y-4">
                      <div className="flex items-center gap-2 p-3 bg-primary/10 rounded-lg">
                        <CheckCircle2 className="h-5 w-5 text-primary" />
                        <div>
                          <p className="text-sm font-medium text-foreground">Optimization Complete</p>
                          <p className="text-xs text-muted-foreground">98.2% coverage achieved</p>
                        </div>
                      </div>
                      <Button
                        className="w-full bg-primary text-primary-foreground hover:bg-primary/90"
                        onClick={() => router.push("/results")}
                      >
                        View Results
                      </Button>
                      <Button
                        variant="outline"
                        className="w-full border-border text-foreground hover:bg-secondary bg-transparent"
                        onClick={handleReset}
                      >
                        <RotateCcw className="h-4 w-4 mr-2" />
                        New Optimization
                      </Button>
                    </div>
                  ) : (
                    <>
                      {tourCount === 0 && (
                        <div className="flex items-center gap-2 p-3 bg-secondary rounded-lg">
                          <AlertCircle className="h-5 w-5 text-muted-foreground" />
                          <p className="text-sm text-muted-foreground">Upload tour data to begin</p>
                        </div>
                      )}
                      <Button
                        className="w-full bg-primary text-primary-foreground hover:bg-primary/90"
                        disabled={tourCount === 0 || isRunning}
                        onClick={handleStartSolve}
                      >
                        {isRunning ? (
                          <>
                            <span className="animate-pulse">Optimizing...</span>
                          </>
                        ) : (
                          <>
                            <Play className="h-4 w-4 mr-2" />
                            Start Optimization
                          </>
                        )}
                      </Button>
                      {tourCount > 0 && !isRunning && (
                        <p className="text-xs text-muted-foreground text-center">
                          Ready to optimize {tourCount} tours for {Math.ceil(tourCount / 8.5)} drivers
                        </p>
                      )}
                    </>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </main>
    </div>
  )
}
