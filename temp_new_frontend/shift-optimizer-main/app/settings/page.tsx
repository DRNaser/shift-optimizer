"use client"

import { useState } from "react"
import { AppSidebar } from "@/components/app-sidebar"
import { AppHeader } from "@/components/app-header"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

export default function SettingsPage() {
  const [settings, setSettings] = useState({
    apiEndpoint: "https://api.shiftoptimizer.com",
    defaultMinHours: 42,
    defaultMaxHours: 53,
    defaultMaxGap: 90,
    autoSave: true,
    notifications: true,
    theme: "dark",
  })

  return (
    <div className="flex min-h-screen">
      <AppSidebar />
      <main className="flex-1 ml-64">
        <AppHeader title="Settings" />
        <div className="p-6 max-w-4xl">
          <Tabs defaultValue="general" className="space-y-6">
            <TabsList className="bg-secondary border border-border">
              <TabsTrigger value="general" className="data-[state=active]:bg-card data-[state=active]:text-foreground">
                General
              </TabsTrigger>
              <TabsTrigger value="solver" className="data-[state=active]:bg-card data-[state=active]:text-foreground">
                Solver Defaults
              </TabsTrigger>
              <TabsTrigger value="api" className="data-[state=active]:bg-card data-[state=active]:text-foreground">
                API Configuration
              </TabsTrigger>
            </TabsList>

            <TabsContent value="general" className="space-y-6">
              <Card className="bg-card border-border">
                <CardHeader>
                  <CardTitle className="text-card-foreground">Preferences</CardTitle>
                  <CardDescription>Manage your application preferences</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label className="text-foreground">Auto-save Results</Label>
                      <p className="text-xs text-muted-foreground">Automatically save optimization results</p>
                    </div>
                    <Switch
                      checked={settings.autoSave}
                      onCheckedChange={(v) => setSettings({ ...settings, autoSave: v })}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <div className="space-y-0.5">
                      <Label className="text-foreground">Notifications</Label>
                      <p className="text-xs text-muted-foreground">Receive notifications when optimization completes</p>
                    </div>
                    <Switch
                      checked={settings.notifications}
                      onCheckedChange={(v) => setSettings({ ...settings, notifications: v })}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label className="text-foreground">Theme</Label>
                    <Select value={settings.theme} onValueChange={(v) => setSettings({ ...settings, theme: v })}>
                      <SelectTrigger className="w-48 bg-secondary border-border text-foreground">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-card border-border">
                        <SelectItem value="dark">Dark</SelectItem>
                        <SelectItem value="light">Light</SelectItem>
                        <SelectItem value="system">System</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="solver" className="space-y-6">
              <Card className="bg-card border-border">
                <CardHeader>
                  <CardTitle className="text-card-foreground">Default Solver Settings</CardTitle>
                  <CardDescription>Configure default parameters for new optimizations</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label htmlFor="defaultMin" className="text-foreground">
                        Default Min Hours
                      </Label>
                      <Input
                        id="defaultMin"
                        type="number"
                        value={settings.defaultMinHours}
                        onChange={(e) => setSettings({ ...settings, defaultMinHours: Number(e.target.value) })}
                        className="bg-secondary border-border text-foreground"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="defaultMax" className="text-foreground">
                        Default Max Hours
                      </Label>
                      <Input
                        id="defaultMax"
                        type="number"
                        value={settings.defaultMaxHours}
                        onChange={(e) => setSettings({ ...settings, defaultMaxHours: Number(e.target.value) })}
                        className="bg-secondary border-border text-foreground"
                      />
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="defaultGap" className="text-foreground">
                      Default Max Gap (minutes)
                    </Label>
                    <Input
                      id="defaultGap"
                      type="number"
                      value={settings.defaultMaxGap}
                      onChange={(e) => setSettings({ ...settings, defaultMaxGap: Number(e.target.value) })}
                      className="bg-secondary border-border text-foreground"
                    />
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="api" className="space-y-6">
              <Card className="bg-card border-border">
                <CardHeader>
                  <CardTitle className="text-card-foreground">API Configuration</CardTitle>
                  <CardDescription>Configure connection to the optimization backend</CardDescription>
                </CardHeader>
                <CardContent className="space-y-6">
                  <div className="space-y-2">
                    <Label htmlFor="apiEndpoint" className="text-foreground">
                      API Endpoint
                    </Label>
                    <Input
                      id="apiEndpoint"
                      value={settings.apiEndpoint}
                      onChange={(e) => setSettings({ ...settings, apiEndpoint: e.target.value })}
                      className="bg-secondary border-border text-foreground"
                    />
                    <p className="text-xs text-muted-foreground">The URL of your FastAPI backend server</p>
                  </div>
                  <Button className="bg-primary text-primary-foreground hover:bg-primary/90">Test Connection</Button>
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>

          <div className="mt-6 flex justify-end">
            <Button className="bg-primary text-primary-foreground hover:bg-primary/90">Save Changes</Button>
          </div>
        </div>
      </main>
    </div>
  )
}
