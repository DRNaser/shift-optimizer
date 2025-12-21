"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const jobs = [
  { id: "JOB-001", date: "2024-01-15", tours: 682, drivers: 80, coverage: "98.2%", status: "completed" },
  { id: "JOB-002", date: "2024-01-14", tours: 695, drivers: 82, coverage: "97.8%", status: "completed" },
  { id: "JOB-003", date: "2024-01-13", tours: 678, drivers: 79, coverage: "99.1%", status: "completed" },
  { id: "JOB-004", date: "2024-01-12", tours: 701, drivers: 83, coverage: "96.5%", status: "completed" },
  { id: "JOB-005", date: "2024-01-11", tours: 688, drivers: 81, coverage: "98.7%", status: "completed" },
]

export function RecentJobsTable() {
  return (
    <Card className="bg-card border-border col-span-2">
      <CardHeader>
        <CardTitle className="text-card-foreground">Recent Optimization Jobs</CardTitle>
        <p className="text-sm text-muted-foreground">Last 5 completed optimization runs</p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow className="border-border hover:bg-transparent">
              <TableHead className="text-muted-foreground">Job ID</TableHead>
              <TableHead className="text-muted-foreground">Date</TableHead>
              <TableHead className="text-muted-foreground">Tours</TableHead>
              <TableHead className="text-muted-foreground">Drivers</TableHead>
              <TableHead className="text-muted-foreground">Coverage</TableHead>
              <TableHead className="text-muted-foreground">Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {jobs.map((job) => (
              <TableRow key={job.id} className="border-border hover:bg-secondary/50">
                <TableCell className="font-mono text-sm text-foreground">{job.id}</TableCell>
                <TableCell className="text-foreground">{job.date}</TableCell>
                <TableCell className="text-foreground">{job.tours}</TableCell>
                <TableCell className="text-foreground">{job.drivers}</TableCell>
                <TableCell className="text-primary font-medium">{job.coverage}</TableCell>
                <TableCell>
                  <Badge variant="secondary" className="bg-primary/20 text-primary border-0">
                    {job.status}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
