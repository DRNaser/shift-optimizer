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
import { TourInput, SolveResponse, solveForecast, SolveConfig } from "@/lib/api"

export default function SolvePage() {
  const router = useRouter()
  const [tourCount, setTourCount] = useState(0)
  const [tours, setTours] = useState<TourInput[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const [isComplete, setIsComplete] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<SolveResponse | null>(null)
  const [config, setConfig] = useState<SolveConfig>({
    minHours: 42,
    maxHours: 53,
    maxGap: 90,
    usePolicy: true,
    policyWeight: 60,
    timeLimit: 60,
  })

  const handleToursData = (loadedTours: TourInput[]) => {
    setTours(loadedTours)
    setError(null)
  }

  const handleStartSolve = async () => {
    if (tours.length === 0) return

    setIsRunning(true)
    setIsComplete(false)
    setError(null)

    try {
      const response = await solveForecast(tours, config)
      setResult(response)
      // Store result in sessionStorage for results page
      sessionStorage.setItem('solveResult', JSON.stringify(response))
      setIsComplete(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Solve failed')
    } finally {
      setIsRunning(false)
    }
  }

  const handleReset = () => {
    setIsRunning(false)
    setIsComplete(false)
    setTours([])
    setTourCount(0)
    setResult(null)
    setError(null)
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
              <TourUpload onToursLoaded={setTourCount} onToursData={handleToursData} />
              <SolverConfig config={config} onConfigChange={setConfig} />
            </div>

            {/* Right Column - Progress and Actions */}
            <div className="space-y-6">
              <SolveProgress isRunning={isRunning} />

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
                          <p className="text-xs text-muted-foreground">
                            {result ? `${result.stats.total_tours_assigned}/${result.stats.total_tours_input} tours assigned` : 'Ready'}
                          </p>
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
