"use client"

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

interface SolverConfigProps {
  config: {
    minHours: number
    maxHours: number
    maxGap: number
    usePolicy: boolean
    policyWeight: number
    timeLimit: number
  }
  onConfigChange: (config: SolverConfigProps["config"]) => void
}

export function SolverConfig({ config, onConfigChange }: SolverConfigProps) {
  return (
    <Card className="bg-card border-border">
      <CardHeader>
        <CardTitle className="text-card-foreground">Solver Configuration</CardTitle>
        <CardDescription>Adjust optimization parameters</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="minHours" className="text-foreground">
              Min Weekly Hours
            </Label>
            <Input
              id="minHours"
              type="number"
              value={config.minHours}
              onChange={(e) => onConfigChange({ ...config, minHours: Number(e.target.value) })}
              className="bg-secondary border-border text-foreground"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="maxHours" className="text-foreground">
              Max Weekly Hours
            </Label>
            <Input
              id="maxHours"
              type="number"
              value={config.maxHours}
              onChange={(e) => onConfigChange({ ...config, maxHours: Number(e.target.value) })}
              className="bg-secondary border-border text-foreground"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="maxGap" className="text-foreground">
            Max Gap Between Tours (minutes)
          </Label>
          <Input
            id="maxGap"
            type="number"
            value={config.maxGap}
            onChange={(e) => onConfigChange({ ...config, maxGap: Number(e.target.value) })}
            className="bg-secondary border-border text-foreground"
          />
        </div>

        <div className="space-y-2">
          <Label className="text-foreground">Time Limit (seconds)</Label>
          <Select
            value={config.timeLimit.toString()}
            onValueChange={(v) => onConfigChange({ ...config, timeLimit: Number(v) })}
          >
            <SelectTrigger className="bg-secondary border-border text-foreground">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-card border-border">
              <SelectItem value="30">30 seconds</SelectItem>
              <SelectItem value="60">1 minute</SelectItem>
              <SelectItem value="120">2 minutes</SelectItem>
              <SelectItem value="300">5 minutes</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-foreground">Use Style Policy</Label>
            <p className="text-xs text-muted-foreground">Apply learned scheduling preferences</p>
          </div>
          <Switch checked={config.usePolicy} onCheckedChange={(v) => onConfigChange({ ...config, usePolicy: v })} />
        </div>

        {config.usePolicy && (
          <div className="space-y-2">
            <div className="flex justify-between">
              <Label className="text-foreground">Policy Weight</Label>
              <span className="text-sm text-muted-foreground">{config.policyWeight}%</span>
            </div>
            <Slider
              value={[config.policyWeight]}
              onValueChange={([v]) => onConfigChange({ ...config, policyWeight: v })}
              max={100}
              step={5}
              className="[&_[role=slider]]:bg-primary"
            />
            <p className="text-xs text-muted-foreground">Higher values prioritize style matching over efficiency</p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
