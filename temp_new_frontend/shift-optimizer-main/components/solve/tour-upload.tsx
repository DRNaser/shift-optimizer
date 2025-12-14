"use client"

import type React from "react"

import { useState, useCallback } from "react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Upload, FileText, X, CheckCircle2 } from "lucide-react"
import { cn } from "@/lib/utils"

interface UploadedFile {
  name: string
  size: number
  tours: number
}

export function TourUpload({ onToursLoaded }: { onToursLoaded: (count: number) => void }) {
  const [isDragging, setIsDragging] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null)

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const file = e.dataTransfer.files[0]
      if (file) {
        // Simulate parsing CSV
        const mockTours = Math.floor(Math.random() * 200) + 600
        setUploadedFile({ name: file.name, size: file.size, tours: mockTours })
        onToursLoaded(mockTours)
      }
    },
    [onToursLoaded],
  )

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) {
        const mockTours = Math.floor(Math.random() * 200) + 600
        setUploadedFile({ name: file.name, size: file.size, tours: mockTours })
        onToursLoaded(mockTours)
      }
    },
    [onToursLoaded],
  )

  const removeFile = () => {
    setUploadedFile(null)
    onToursLoaded(0)
  }

  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Tour Data</CardTitle>
        <CardDescription>Upload your tour forecast CSV file</CardDescription>
      </CardHeader>
      <CardContent>
        {!uploadedFile ? (
          <div
            className={cn(
              "border-2 border-dashed rounded-lg p-8 text-center transition-colors",
              isDragging ? "border-primary bg-primary/5" : "border-border hover:border-primary/50",
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <Upload className="h-10 w-10 mx-auto text-muted-foreground mb-4" />
            <p className="text-sm text-muted-foreground mb-2">Drag and drop your CSV file here, or</p>
            <label>
              <input type="file" accept=".csv" className="hidden" onChange={handleFileSelect} />
              <Button variant="secondary" className="cursor-pointer" asChild>
                <span>Browse Files</span>
              </Button>
            </label>
            <p className="text-xs text-muted-foreground mt-4">
              Supports CSV files with tour_id, start_time, end_time columns
            </p>
          </div>
        ) : (
          <div className="flex items-center justify-between p-4 bg-secondary rounded-lg">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-md bg-primary/20 flex items-center justify-center">
                <FileText className="h-5 w-5 text-primary" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">{uploadedFile.name}</p>
                <p className="text-xs text-muted-foreground">
                  {(uploadedFile.size / 1024).toFixed(1)} KB • {uploadedFile.tours} tours detected
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-primary" />
              <Button variant="ghost" size="icon" onClick={removeFile}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
