# Component Reference

## Layout Components

### Platform Header
`components/layout/platform-header.tsx`

Features:
- User menu (email, logout)
- Context switcher indicator
- Build info

```tsx
import { PlatformHeader } from '@/components/layout/platform-header';

<PlatformHeader />
```

### Platform Sidebar
`components/layout/platform-sidebar.tsx`

Features:
- Navigation links
- Active route highlighting
- Collapsible sections

```tsx
import { PlatformSidebar } from '@/components/layout/platform-sidebar';

<PlatformSidebar />
```

### Context Switcher
`components/layout/context-switcher.tsx`

Features:
- Shows active tenant/site
- Quick switch dropdown
- Clear context button

```tsx
import { ContextSwitcher } from '@/components/layout/context-switcher';

<ContextSwitcher />
```

### Build Info
`components/layout/build-info.tsx`

Shows git commit hash and build timestamp in footer.

```tsx
import { BuildInfo } from '@/components/layout/build-info';

<BuildInfo />
```

---

## UI Components

### Button
`components/ui/button.tsx`

Variants: `default`, `destructive`, `outline`, `secondary`, `ghost`, `link`
Sizes: `default`, `sm`, `lg`, `icon`

```tsx
import { Button } from '@/components/ui/button';

<Button variant="default">Click me</Button>
<Button variant="destructive" size="sm">Delete</Button>
<Button variant="outline" disabled>Disabled</Button>
```

### Tabs
`components/ui/tabs.tsx`

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

<Tabs defaultValue="tab1">
  <TabsList>
    <TabsTrigger value="tab1">Tab 1</TabsTrigger>
    <TabsTrigger value="tab2">Tab 2</TabsTrigger>
  </TabsList>
  <TabsContent value="tab1">Content 1</TabsContent>
  <TabsContent value="tab2">Content 2</TabsContent>
</Tabs>
```

### Status Badges
`components/ui/status-badge.tsx`
`components/ui/plan-status-badge.tsx`
`components/ui/platform-status-badge.tsx`
`components/ui/run-status-badge.tsx`

```tsx
import { StatusBadge } from '@/components/ui/status-badge';

<StatusBadge status="success">Active</StatusBadge>
<StatusBadge status="warning">Pending</StatusBadge>
<StatusBadge status="error">Failed</StatusBadge>
```

### API Error
`components/ui/api-error.tsx`

```tsx
import { ApiError } from '@/components/ui/api-error';

<ApiError
  message="Failed to load data"
  details="Connection timeout"
  onRetry={() => fetchData()}
/>
```

### KPI Cards
`components/ui/kpi-cards.tsx`

```tsx
import { KPICards } from '@/components/ui/kpi-cards';

<KPICards
  items={[
    { label: 'Total Users', value: 145 },
    { label: 'Active', value: 120, trend: '+5%' },
    { label: 'Coverage', value: '98%' },
  ]}
/>
```

### Live Console
`components/ui/live-console.tsx`

Real-time log display for solver runs.

```tsx
import { LiveConsole } from '@/components/ui/live-console';

<LiveConsole
  logs={logs}
  autoScroll={true}
  maxLines={500}
/>
```

### Matrix View
`components/ui/matrix-view.tsx`

Grid display for schedule visualization.

```tsx
import { MatrixView } from '@/components/ui/matrix-view';

<MatrixView
  rows={drivers}
  columns={days}
  cellRenderer={(driver, day) => <ShiftPill shift={getShift(driver, day)} />}
/>
```

---

## Domain Components

### Roster Matrix
`components/domain/roster-matrix.tsx`

Full roster display with driver rows and day columns.

```tsx
import { RosterMatrix } from '@/components/domain/roster-matrix';

<RosterMatrix
  weekId="2026-W02"
  drivers={drivers}
  assignments={assignments}
/>
```

### Pipeline Stepper
`components/domain/pipeline-stepper.tsx`

Shows solver pipeline progress: Import → Solve → Audit → Publish.

```tsx
import { PipelineStepper } from '@/components/domain/pipeline-stepper';

<PipelineStepper
  steps={['import', 'solve', 'audit', 'publish']}
  currentStep="solve"
  status="running"
/>
```

### Shift Pill
`components/domain/shift-pill.tsx`

Colored badge for shift type display.

```tsx
import { ShiftPill } from '@/components/domain/shift-pill';

<ShiftPill type="früh" />  // Green
<ShiftPill type="spät" />  // Blue
<ShiftPill type="frei" />  // Gray
```

---

## Portal Components

### Portal KPI Cards
`components/portal/portal-kpi-cards.tsx`

Driver portal summary stats.

```tsx
import { PortalKPICards } from '@/components/portal/portal-kpi-cards';

<PortalKPICards
  total={100}
  sent={90}
  read={75}
  acked={60}
  declined={5}
/>
```

### Driver Table
`components/portal/driver-table.tsx`

Sortable/filterable driver list.

```tsx
import { DriverTable } from '@/components/portal/driver-table';

<DriverTable
  drivers={drivers}
  onSelect={(driver) => setSelected(driver)}
/>
```

### Driver Drawer
`components/portal/driver-drawer.tsx`

Side panel with driver details.

```tsx
import { DriverDrawer } from '@/components/portal/driver-drawer';

<DriverDrawer
  driver={selectedDriver}
  open={drawerOpen}
  onClose={() => setDrawerOpen(false)}
/>
```

### Status Filters
`components/portal/status-filters.tsx`

Filter buttons for notification status.

```tsx
import { StatusFilters } from '@/components/portal/status-filters';

<StatusFilters
  selected={['sent', 'pending']}
  onChange={(filters) => setFilters(filters)}
/>
```

### Resend Dialog
`components/portal/resend-dialog.tsx`

Confirmation dialog for resending notifications.

```tsx
import { ResendDialog } from '@/components/portal/resend-dialog';

<ResendDialog
  driver={driver}
  open={dialogOpen}
  onConfirm={handleResend}
  onCancel={() => setDialogOpen(false)}
/>
```

### Export CSV Button
`components/portal/export-csv-button.tsx`

Download CSV export of driver status.

```tsx
import { ExportCSVButton } from '@/components/portal/export-csv-button';

<ExportCSVButton snapshotId={123} />
```

---

## Platform Components

### Onboarding Wizard
`components/platform/onboarding-wizard.tsx`

Multi-step tenant setup wizard.

```tsx
import { OnboardingWizard } from '@/components/platform/onboarding-wizard';

<OnboardingWizard
  steps={['tenant', 'site', 'user']}
  onComplete={(data) => handleComplete(data)}
/>
```

### Resolve Escalation Dialog
`components/platform/resolve-escalation-dialog.tsx`

Dialog for resolving platform escalations.

```tsx
import { ResolveEscalationDialog } from '@/components/platform/resolve-escalation-dialog';

<ResolveEscalationDialog
  escalation={escalation}
  open={dialogOpen}
  onResolve={handleResolve}
/>
```

---

## Tenant Components

### Status Banner
`components/tenant/status-banner.tsx`

Shows tenant-wide alerts and status messages.

```tsx
import { StatusBanner } from '@/components/tenant/status-banner';

<StatusBanner
  status="warning"
  message="Plan not published yet"
/>
```

### Error Handler
`components/tenant/error-handler.tsx`

Tenant-scoped error boundary.

```tsx
import { ErrorHandler } from '@/components/tenant/error-handler';

<ErrorHandler>
  <TenantContent />
</ErrorHandler>
```

---

## Plans Components

### Publish Modal
`components/plans/publish-modal.tsx`

Confirmation modal for publishing plans.

```tsx
import { PublishModal } from '@/components/plans/publish-modal';

<PublishModal
  runId={runId}
  open={modalOpen}
  onConfirm={handlePublish}
  onCancel={() => setModalOpen(false)}
/>
```

### Legacy Snapshot Warning
`components/plans/legacy-snapshot-warning.tsx`

Warning banner for old snapshot formats.

```tsx
import { LegacySnapshotWarning } from '@/components/plans/legacy-snapshot-warning';

<LegacySnapshotWarning snapshotVersion={1} />
```

---

## Creating New Components

### File Location
- **UI components**: `components/ui/`
- **Layout**: `components/layout/`
- **Domain-specific**: `components/domain/`
- **Feature-specific**: `components/[feature]/`

### Template

```tsx
// components/ui/my-component.tsx
import { cn } from '@/lib/utils';

interface MyComponentProps {
  className?: string;
  children?: React.ReactNode;
}

export function MyComponent({ className, children }: MyComponentProps) {
  return (
    <div className={cn('base-styles', className)}>
      {children}
    </div>
  );
}
```

### Export Pattern
Add to barrel export if needed:

```tsx
// components/ui/index.ts
export { MyComponent } from './my-component';
```
