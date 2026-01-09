# SOLVEREIGN Frontend Architecture Analysis

> **Status**: REVISED v2 - POST-CHALLENGE
> **Scope**: Enterprise SaaS Frontend Design
> **Author**: Architecture Review
> **Date**: 2026-01-06
> **Stack**: Next.js 16.1.1 + React 19 + Tailwind 4

---

## 1. EXECUTIVE SUMMARY

Diese Analyse bewertet die vorgeschlagene Frontend-Architektur kritisch und identifiziert:
- **12 Blindspots** in der ursprünglichen Planung
- **8 Security Gaps** die geschlossen werden müssen
- **5 UX Anti-Patterns** die vermieden werden sollten
- **Optimiertes 4-Layer Design** mit klarer Separation

---

## 2. BRANDING & DESIGN SYSTEM

### 2.1 Logo Analysis
```
┌─────────────────────────────────────────────────┐
│  [S]  SOLVEREIGN CORE                           │
│   ↑         ↑         ↑                         │
│   │         │         └── Grau = Modular/Pack   │
│   │         └── Weiß = Primär/Vertrauen         │
│   └── Cyan-Blau = Tech/Innovation               │
└─────────────────────────────────────────────────┘
```

### 2.2 Design Tokens (aus Logo abgeleitet)

```css
/* SOLVEREIGN Design System */
:root {
  /* Primary Palette */
  --sv-primary-100: #E6F4F9;
  --sv-primary-300: #7FC8E8;
  --sv-primary-500: #4AA8C7;  /* Logo Cyan */
  --sv-primary-700: #2D7A99;
  --sv-primary-900: #1A4D61;

  /* Neutral Palette (aus Logo Background) */
  --sv-neutral-50:  #F8FAFC;
  --sv-neutral-100: #F1F5F9;
  --sv-neutral-300: #CBD5E1;
  --sv-neutral-500: #64748B;
  --sv-neutral-700: #334155;
  --sv-neutral-800: #2D3B4D;  /* Logo BG */
  --sv-neutral-900: #1E293B;

  /* Semantic Colors */
  --sv-success: #10B981;
  --sv-warning: #F59E0B;
  --sv-error:   #EF4444;
  --sv-info:    var(--sv-primary-500);

  /* Typography */
  --sv-font-sans: 'Inter', -apple-system, sans-serif;
  --sv-font-mono: 'JetBrains Mono', monospace;

  /* Spacing Scale (8px base) */
  --sv-space-1: 0.25rem;   /* 4px */
  --sv-space-2: 0.5rem;    /* 8px */
  --sv-space-4: 1rem;      /* 16px */
  --sv-space-6: 1.5rem;    /* 24px */
  --sv-space-8: 2rem;      /* 32px */
}
```

---

## 3. ARCHITECTURE LAYERS (4-Layer Model)

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAYER 0: PUBLIC SURFACE                      │
│  marketing.solvereign.io                                        │
│  ├── Landing Page                                               │
│  ├── Pricing                                                    │
│  ├── Documentation (Read-Only)                                  │
│  ├── Login/Signup                                               │
│  └── Status Page                                                │
├─────────────────────────────────────────────────────────────────┤
│                    LAYER 1: PLATFORM CONSOLE                    │
│  platform.solvereign.io (Super-Admin Only)                      │
│  ├── Tenant Management                                          │
│  ├── Pack Catalog & Entitlements                                │
│  ├── Infrastructure Health                                      │
│  ├── Global Audit Trail                                         │
│  └── Billing/Usage Metering                                     │
├─────────────────────────────────────────────────────────────────┤
│                    LAYER 2: TENANT CONSOLE                      │
│  {tenant}.solvereign.io (Tenant Users)                          │
│  ├── CORE MODULES (always visible)                              │
│  │   ├── Dashboard/Work Queue                                   │
│  │   ├── Scenarios & Plan Versions                              │
│  │   ├── Audits & Compliance                                    │
│  │   ├── Lock/Freeze Management                                 │
│  │   ├── Evidence Vault                                         │
│  │   └── Repair Center                                          │
│  │                                                              │
│  ├── TENANT ADMIN (Tenant-Admin Role)                           │
│  │   ├── Sites & Depots                                         │
│  │   ├── Users & Roles                                          │
│  │   ├── Skills Taxonomy                                        │
│  │   ├── Integrations                                           │
│  │   └── Pack Configuration                                     │
│  │                                                              │
│  └── PACK WORKSPACES (conditional)                              │
│      ├── [Routing Pack]                                         │
│      └── [Roster Pack]                                          │
├─────────────────────────────────────────────────────────────────┤
│                    LAYER 3: PACK WORKSPACES                     │
│  Dynamisch geladen basierend auf Entitlements                   │
│  ├── Routing Pack                                               │
│  │   ├── Stop Import                                            │
│  │   ├── Team Builder                                           │
│  │   ├── Route Visualization                                    │
│  │   └── Routing KPIs                                           │
│  │                                                              │
│  └── Roster Pack                                                │
│      ├── Forecast Import                                        │
│      ├── Driver Pool                                            │
│      ├── Schedule Matrix                                        │
│      └── Compliance Dashboard                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. BLINDSPOT ANALYSIS (12 identifiziert)

### BLINDSPOT #1: Session Management Cross-Layer
**Problem**: Keine klare Session-Isolation zwischen Platform Console und Tenant Console.
**Risiko**: Super-Admin Session könnte in Tenant-Context "leaken".
**Fix**:
```typescript
// Separate Session Stores
interface PlatformSession {
  type: 'platform';
  adminId: string;
  permissions: PlatformPermission[];
}

interface TenantSession {
  type: 'tenant';
  tenantId: string;
  userId: string;
  siteId: string | null;  // CRITICAL: Site-Scope
  roles: TenantRole[];
}

// Session Guard
function requireTenantContext(session: Session): asserts session is TenantSession {
  if (session.type !== 'tenant') {
    throw new ForbiddenError('Tenant context required');
  }
}
```

### BLINDSPOT #2: Site-Scoping im UI fehlt
**Problem**: Original-Design erwähnt Sites, aber nicht wie User zwischen Sites wechseln.
**Risiko**: User sieht Daten von allen Sites vermischt.
**Fix**: Site-Selector in Header (persistent) + RLS-Enforcement.
```
┌─────────────────────────────────────────────────────┐
│ [S] SOLVEREIGN   │ Site: [Wien ▼]  │  [?] [👤]     │
└─────────────────────────────────────────────────────┘
```

### BLINDSPOT #3: Pack Activation Flow unspezifiziert
**Problem**: Wie wird ein Pack aktiviert? Wer darf das? Was passiert mit Daten?
**Fix**: Expliziter Activation Wizard mit:
1. Prerequisite Check (required integrations)
2. Migration Consent (DB schema changes)
3. Role Assignment (who can use this pack)
4. Initial Setup Checklist

### BLINDSPOT #4: Empty States nicht designed
**Problem**: "Noch keine Daten" ist lazy - keine Guidance.
**Fix**: Action-Oriented Empty States:
```
┌─────────────────────────────────────────────────────┐
│                                                     │
│        📦 Keine Stops importiert                    │
│                                                     │
│   Dein erster Import startet den Workflow.          │
│                                                     │
│   [CSV hochladen]  [API Docs]  [Sample herunterladen]│
│                                                     │
│   ────────────────────────────────────────────      │
│   Setup Progress: ████░░░░░░ 40%                    │
│   ☑ Site angelegt                                   │
│   ☑ Depot konfiguriert                              │
│   ☐ Stops importieren ← DU BIST HIER               │
│   ☐ Teams anlegen                                   │
│   ☐ Erstes Scenario erstellen                       │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### BLINDSPOT #5: Offline/Degraded Mode
**Problem**: Was passiert wenn OSRM/Backend down ist?
**Fix**:
- Read-Only Mode mit cached data
- "Last Known Good" Anzeige
- Graceful degradation pro Feature
- Service Status Banner

### BLINDSPOT #6: Multi-Tab Conflict
**Problem**: User öffnet gleiche Entity in 2 Tabs, editiert beide.
**Fix**: ETag/If-Match Pattern (nicht nur UI-Banner):

```typescript
// 1. GET Response includes ETag
// HTTP/1.1 200 OK
// ETag: "abc123def456"
// { "id": "plan-1", "status": "DRAFT", ... }

// 2. Frontend stores ETag
const { data, etag } = await api.plans.get(planId);
planStore.setEtag(planId, etag);

// 3. PUT/PATCH includes If-Match
async function updatePlan(planId: string, updates: PlanUpdate) {
  const etag = planStore.getEtag(planId);

  try {
    await fetch(`/api/plans/${planId}`, {
      method: 'PATCH',
      headers: {
        'If-Match': etag,  // Server validates
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(updates),
    });
  } catch (e) {
    if (e.status === 412) {  // Precondition Failed
      // Show conflict dialog
      showConflictDialog({
        message: 'Plan wurde von jemand anderem geändert',
        options: ['Neu laden', 'Überschreiben', 'Abbrechen'],
      });
    }
    throw e;
  }
}
```

**Backend FastAPI**:
```python
@router.patch("/plans/{plan_id}")
async def update_plan(
    plan_id: str,
    updates: PlanUpdate,
    if_match: str = Header(..., alias="If-Match"),
):
    plan = await get_plan(plan_id)

    if plan.etag != if_match:
        raise HTTPException(
            status_code=412,
            detail={"error": "CONFLICT", "current_etag": plan.etag}
        )

    # Proceed with update...
```

### BLINDSPOT #7: Audit Trail im UI
**Problem**: Audit Log existiert im Backend, aber keine UI dafür.
**Fix**: Audit Viewer mit:
- Timeline View pro Entity
- Filter by User/Action/Time
- Diff Viewer für Changes
- Export to CSV/JSON

### BLINDSPOT #8: Error Recovery UX
**Problem**: Was passiert wenn Solve Job failed?
**Fix**: Error Detail Page mit:
- Stack Trace (for admins)
- Plain-Language Explanation
- "Retry" Button
- "Report Issue" mit Pre-filled Context

### BLINDSPOT #9: Bulk Operations
**Problem**: Keine Bulk-Actions für Listen (z.B. alle Failed Items löschen).
**Fix**: Selection Mode für alle Listen:
```
┌─────────────────────────────────────────────────────┐
│ ☐ Select All  │  3 selected  │ [🗑️ Delete] [📤 Export]│
├─────────────────────────────────────────────────────┤
│ ☑ Scenario-001  │ FAILED   │ 2026-01-05            │
│ ☑ Scenario-002  │ FAILED   │ 2026-01-05            │
│ ☐ Scenario-003  │ SOLVED   │ 2026-01-06            │
│ ☑ Scenario-004  │ FAILED   │ 2026-01-06            │
└─────────────────────────────────────────────────────┘
```

### BLINDSPOT #10: Keyboard Navigation
**Problem**: Enterprise Users erwarten Keyboard Shortcuts.
**Fix**:
- Global Shortcuts (Cmd+K → Command Palette)
- Context Shortcuts (Arrow keys in tables)
- Shortcut Reference (? key)

### BLINDSPOT #11: Export/Print für Evidence
**Problem**: Evidence Pack nur als Download? Was wenn Auditor Print will?
**Fix**:
- Print-Optimized View (CSS @media print)
- PDF Export mit Watermark + Hash
- QR Code linking to online verification

### BLINDSPOT #12: Localization Architecture
**Problem**: Keine i18n Strategie erwähnt.
**Fix**:
- DE/EN mandatory (DACH market)
- ICU Message Format
- RTL-ready CSS (future proofing)
- Number/Date formatting per locale

---

## 5. SECURITY ANALYSIS (8 Gaps)

### SECURITY GAP #1: Token Storage + Cookie Isolation
**Problem**: Wo werden Auth Tokens gespeichert? Session-Isolation zwischen Layers?
**Risk**: XSS kann Tokens stehlen aus localStorage. Cross-layer session leak.
**Fix**:
```typescript
// NEVER localStorage for auth tokens
// Use httpOnly cookies + CSRF protection + __Host- prefix

// Cookie Configuration (Backend sets these):
// platform.solvereign.io:
//   Set-Cookie: __Host-sv_platform=...; Secure; HttpOnly; SameSite=Strict; Path=/
//
// {tenant}.solvereign.io:
//   Set-Cookie: __Host-sv_tenant=...; Secure; HttpOnly; SameSite=Strict; Path=/

// __Host- prefix enforces:
// - Secure flag required
// - No Domain attribute (host-only)
// - Path must be /

// Frontend: No token storage, rely on cookies
async function apiCall(endpoint: string) {
  return fetch(endpoint, {
    credentials: 'include',  // Send cookies
    headers: {
      'X-CSRF-Token': getCsrfToken()  // From meta tag
    }
  });
}
```

**CRITICAL**: Tenant/Site context comes from SERVER SESSION, not client headers:
```typescript
// ❌ WRONG: Client sets tenant header (manipulable)
fetch('/api/scenarios', {
  headers: { 'X-Tenant-ID': tenantId }
})

// ✅ CORRECT: BFF (Server Component/API Route) injects from session
// app/api/scenarios/route.ts
export async function GET(request: NextRequest) {
  const session = await getSession(request);  // Server validates
  const tenantId = session.tenantId;          // From cookie claims

  return backendApi.get('/scenarios', {
    headers: { 'X-Tenant-ID': tenantId }      // Server→Server, trusted
  });
}
```

### SECURITY GAP #2: Route Protection
**Problem**: Wie werden Pack-Routes geschützt wenn Pack nicht aktiviert?
**Fix**:
```typescript
// Route Guard with Entitlement Check
const RoutingPackRoutes = {
  path: '/routing',
  element: <PackGuard packId="routing"><RoutingLayout /></PackGuard>,
  children: [...]
};

function PackGuard({ packId, children }) {
  const { entitlements } = useTenant();

  if (!entitlements.includes(packId)) {
    return <Navigate to="/403?reason=pack_not_enabled" />;
  }

  return children;
}
```

### SECURITY GAP #3: API Response Filtering
**Problem**: Backend sendet full objects, Frontend filtert?
**Risk**: Sensitive data in network tab visible.
**Fix**: Backend MUST filter responses by role. Frontend NEVER trusts "hidden" fields.

### SECURITY GAP #4: File Upload Validation
**Problem**: CSV Import - was wenn malicious file?
**Fix**:
```typescript
// Client-side pre-validation (UX, not security)
function validateUpload(file: File): ValidationResult {
  // Max size
  if (file.size > 10 * 1024 * 1024) {
    return { valid: false, error: 'File too large (max 10MB)' };
  }

  // Allowed types
  if (!['text/csv', 'application/json'].includes(file.type)) {
    return { valid: false, error: 'Only CSV/JSON allowed' };
  }

  return { valid: true };
}

// Server-side: Full validation, virus scan, content inspection
```

### SECURITY GAP #5: Iframe Embedding
**Problem**: Kann SOLVEREIGN in fremden Iframe geladen werden?
**Fix**: Backend/Edge headers ONLY (keine client-side frame-busting):
```
# Backend Response Headers (FastAPI middleware or Edge config)
X-Frame-Options: DENY
Content-Security-Policy: frame-ancestors 'none';
```

**WICHTIG**: KEIN client-side frame-busting wie:
```typescript
// ❌ NICHT VERWENDEN - kann umgangen werden
if (window.top !== window.self) {
  window.top.location = window.self.location;
}
```
CSP `frame-ancestors` ist der Standard (OWASP, MDN).

### SECURITY GAP #6: Clipboard Operations
**Problem**: "Copy Hash" Button - was wenn XSS?
**Fix**:
```typescript
// Safe clipboard write
async function copyToClipboard(text: string) {
  // Sanitize before copy
  const sanitized = text.replace(/[<>]/g, '');

  await navigator.clipboard.writeText(sanitized);

  // Audit log for sensitive data
  if (isSensitive(text)) {
    logAudit('clipboard_copy', { type: 'hash' });
  }
}
```

### SECURITY GAP #7: Console Logging in Production
**Problem**: console.log() leaks internal state.
**Fix**:
```typescript
// Build-time removal
// vite.config.ts
export default {
  esbuild: {
    drop: process.env.NODE_ENV === 'production' ? ['console', 'debugger'] : []
  }
};
```

### SECURITY GAP #8: Dependency Security
**Problem**: npm packages mit known vulnerabilities.
**Fix**:
```yaml
# .github/workflows/security.yml
- name: Audit Dependencies
  run: npm audit --audit-level=high

- name: License Check
  run: npx license-checker --onlyAllow "MIT;Apache-2.0;BSD-3-Clause"
```

---

## 6. UX ANTI-PATTERNS TO AVOID

### ANTI-PATTERN #1: Modal Hell
**Problem**: Modals inside modals.
**Fix**: Use side panels (drawers) for detail views, modals only for confirmations.

### ANTI-PATTERN #2: Infinite Scroll ohne Kontext
**Problem**: User verliert Position.
**Fix**: Virtual scroll + sticky "position indicator" + "Back to Top" FAB.

### ANTI-PATTERN #3: Form Validation nur on Submit
**Problem**: User füllt 20 Felder aus, dann 10 Fehler.
**Fix**: Inline validation on blur, form-level on submit, clear error messages.

### ANTI-PATTERN #4: Loading States ohne Progress
**Problem**: Spinner für 30s ohne Feedback.
**Fix**: Progress bar, ETA, "This usually takes 30s" message, cancel option.

### ANTI-PATTERN #5: Destructive Actions ohne Undo
**Problem**: "Are you sure?" dialogs sind ignoriert.
**Fix**: Soft-delete + Toast with Undo, or type-to-confirm for hard-delete.

---

## 7. COMPONENT HIERARCHY

```
src/
├── app/
│   ├── (public)/               # Layer 0: Marketing
│   │   ├── page.tsx            # Landing
│   │   ├── pricing/
│   │   └── docs/
│   │
│   ├── (platform)/             # Layer 1: Platform Console
│   │   ├── layout.tsx          # Platform Chrome
│   │   ├── tenants/
│   │   ├── packs/
│   │   ├── infrastructure/
│   │   └── billing/
│   │
│   ├── (tenant)/               # Layer 2: Tenant Console
│   │   ├── layout.tsx          # Tenant Chrome + Site Selector
│   │   ├── dashboard/
│   │   ├── scenarios/
│   │   ├── audits/
│   │   ├── evidence/
│   │   ├── repair/
│   │   ├── admin/              # Tenant Admin
│   │   │   ├── sites/
│   │   │   ├── users/
│   │   │   └── integrations/
│   │   │
│   │   └── packs/              # Layer 3: Pack Workspaces
│   │       ├── routing/
│   │       │   ├── stops/
│   │       │   ├── teams/
│   │       │   ├── routes/
│   │       │   └── kpis/
│   │       │
│   │       └── roster/
│   │           ├── forecasts/
│   │           ├── drivers/
│   │           ├── schedules/
│   │           └── compliance/
│   │
│   └── api/                    # API Routes (BFF)
│
├── components/
│   ├── ui/                     # Primitives (shadcn/ui)
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   └── ...
│   │
│   ├── core/                   # SOLVEREIGN Core Components
│   │   ├── scenario-card.tsx
│   │   ├── plan-version-badge.tsx
│   │   ├── audit-status.tsx
│   │   ├── evidence-viewer.tsx
│   │   ├── hash-display.tsx
│   │   └── repair-wizard.tsx
│   │
│   ├── layout/
│   │   ├── platform-shell.tsx
│   │   ├── tenant-shell.tsx
│   │   ├── site-selector.tsx
│   │   └── pack-nav.tsx
│   │
│   └── packs/                  # Pack-specific Components
│       ├── routing/
│       │   ├── route-map.tsx
│       │   ├── stop-table.tsx
│       │   └── team-builder.tsx
│       │
│       └── roster/
│           ├── schedule-matrix.tsx
│           ├── driver-card.tsx
│           └── forecast-parser.tsx
│
├── hooks/
│   ├── use-tenant.ts           # Tenant context
│   ├── use-session.ts          # Auth state
│   ├── use-site.ts             # Site scope
│   ├── use-entitlements.ts     # Pack access
│   └── use-audit-log.ts        # Audit logging
│
├── lib/
│   ├── api/                    # API client
│   ├── auth/                   # Auth utilities
│   ├── validation/             # Schema validation
│   └── utils/                  # Helpers
│
└── styles/
    ├── globals.css
    ├── design-tokens.css
    └── print.css               # Print styles
```

---

## 8. STATE MANAGEMENT

```typescript
// Layered State Architecture

// 1. Server State (React Query)
const { data: scenarios } = useQuery({
  queryKey: ['scenarios', tenantId, siteId],
  queryFn: () => api.scenarios.list({ tenantId, siteId }),
});

// 2. URL State (Search Params)
const [searchParams, setSearchParams] = useSearchParams();
const status = searchParams.get('status') || 'all';

// 3. UI State (Zustand for global, useState for local)
const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  theme: 'system',
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
}));

// 4. Form State (React Hook Form)
const form = useForm<ScenarioForm>({
  resolver: zodResolver(scenarioSchema),
});

// 5. Context State (Auth, Tenant, Site)
const TenantContext = createContext<TenantContextValue>(null);

function TenantProvider({ children }) {
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [site, setSite] = useState<Site | null>(null);

  // Site changes trigger data refetch
  useEffect(() => {
    if (site) {
      queryClient.invalidateQueries({ queryKey: ['scenarios'] });
    }
  }, [site]);

  return (
    <TenantContext.Provider value={{ tenant, site, setSite }}>
      {children}
    </TenantContext.Provider>
  );
}
```

---

## 9. API INTEGRATION PATTERNS

```typescript
// Type-Safe API Client

// 1. OpenAPI Generated Types
import type { components, paths } from './api-types';

type Scenario = components['schemas']['Scenario'];
type CreateScenarioRequest = paths['/scenarios']['post']['requestBody']['content']['application/json'];

// 2. API Client with Interceptors
const api = createApiClient({
  baseUrl: '/api/v1',
  interceptors: {
    request: async (config) => {
      // Add CSRF token
      config.headers['X-CSRF-Token'] = getCsrfToken();

      // Add tenant/site context
      const { tenantId, siteId } = getTenantContext();
      config.headers['X-Tenant-ID'] = tenantId;
      if (siteId) {
        config.headers['X-Site-ID'] = siteId;
      }

      return config;
    },

    response: async (response) => {
      // Handle 401 → redirect to login
      if (response.status === 401) {
        window.location.href = '/login?reason=session_expired';
      }

      // Handle 403 → show permission error
      if (response.status === 403) {
        toast.error('Keine Berechtigung für diese Aktion');
      }

      return response;
    },
  },
});

// 3. React Query Hooks with Proper Keys
function useScenarios(filters: ScenarioFilters) {
  const { tenantId, siteId } = useTenant();

  return useQuery({
    queryKey: ['scenarios', tenantId, siteId, filters],
    queryFn: () => api.scenarios.list({ ...filters, siteId }),
    staleTime: 30_000,  // 30s
    refetchOnWindowFocus: true,
  });
}

// 4. Optimistic Updates with Rollback
function useLockPlan() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (planId: string) => api.plans.lock(planId),

    onMutate: async (planId) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['plans', planId] });

      // Snapshot previous value
      const previous = queryClient.getQueryData(['plans', planId]);

      // Optimistically update
      queryClient.setQueryData(['plans', planId], (old) => ({
        ...old,
        status: 'LOCKED',
        lockedAt: new Date().toISOString(),
      }));

      return { previous };
    },

    onError: (err, planId, context) => {
      // Rollback on error
      queryClient.setQueryData(['plans', planId], context.previous);
      toast.error('Lock fehlgeschlagen: ' + err.message);
    },

    onSettled: (_, __, planId) => {
      // Refetch to ensure consistency
      queryClient.invalidateQueries({ queryKey: ['plans', planId] });
    },
  });
}
```

---

## 10. TESTING STRATEGY

```typescript
// Testing Pyramid for Frontend

// 1. Unit Tests (Vitest) - 60%
describe('hashDisplay', () => {
  it('truncates long hashes with ellipsis', () => {
    const result = truncateHash('abc123def456', 8);
    expect(result).toBe('abc1...6');
  });
});

// 2. Component Tests (Testing Library) - 30%
describe('ScenarioCard', () => {
  it('shows lock button only for AUDITED status', () => {
    render(<ScenarioCard scenario={{ status: 'AUDITED' }} />);
    expect(screen.getByRole('button', { name: /lock/i })).toBeInTheDocument();
  });

  it('disables lock button without APPROVER role', () => {
    render(
      <RoleProvider roles={['VIEWER']}>
        <ScenarioCard scenario={{ status: 'AUDITED' }} />
      </RoleProvider>
    );
    expect(screen.getByRole('button', { name: /lock/i })).toBeDisabled();
  });
});

// 3. E2E Tests (Playwright) - 10%
test('complete workflow: import → solve → lock', async ({ page }) => {
  await page.goto('/scenarios');

  // Create scenario
  await page.click('[data-testid="create-scenario"]');
  await page.setInputFiles('[data-testid="stops-upload"]', 'fixtures/stops.csv');
  await page.click('[data-testid="submit"]');

  // Wait for solve
  await expect(page.locator('[data-testid="status"]')).toHaveText('SOLVED', { timeout: 30000 });

  // Lock
  await page.click('[data-testid="lock-plan"]');
  await page.fill('[data-testid="confirm-lock"]', 'LOCK');
  await page.click('[data-testid="confirm-button"]');

  await expect(page.locator('[data-testid="status"]')).toHaveText('LOCKED');
});
```

---

## 11. PERFORMANCE OPTIMIZATION

```typescript
// 1. Code Splitting by Route
const RoutingPack = lazy(() => import('./packs/routing'));
const RosterPack = lazy(() => import('./packs/roster'));

// 2. Virtual Scrolling for Large Lists
import { useVirtualizer } from '@tanstack/react-virtual';

function StopList({ stops }) {
  const parentRef = useRef();

  const virtualizer = useVirtualizer({
    count: stops.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 48,
    overscan: 5,
  });

  return (
    <div ref={parentRef} style={{ height: '400px', overflow: 'auto' }}>
      <div style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((item) => (
          <StopRow key={item.key} stop={stops[item.index]} />
        ))}
      </div>
    </div>
  );
}

// 3. Memoization for Expensive Renders
const RouteMap = memo(function RouteMap({ routes }) {
  // Only re-render when routes array changes
  return <MapGL>{routes.map(r => <RouteLayer key={r.id} route={r} />)}</MapGL>;
}, (prev, next) => {
  // Custom comparison
  return prev.routes.length === next.routes.length &&
         prev.routes.every((r, i) => r.id === next.routes[i].id);
});

// 4. Preloading Critical Assets
<link rel="preload" href="/fonts/inter.woff2" as="font" crossOrigin />
<link rel="prefetch" href="/api/v1/scenarios" />
```

---

## 12. ACCESSIBILITY (a11y)

```typescript
// WCAG 2.1 AA Compliance

// 1. Semantic HTML
<nav aria-label="Hauptnavigation">
  <ul role="menubar">
    <li role="none">
      <a role="menuitem" href="/scenarios">Scenarios</a>
    </li>
  </ul>
</nav>

// 2. Focus Management
function Modal({ isOpen, onClose, children }) {
  const previousFocus = useRef<HTMLElement>();
  const closeRef = useRef<HTMLButtonElement>();

  useEffect(() => {
    if (isOpen) {
      previousFocus.current = document.activeElement as HTMLElement;
      closeRef.current?.focus();
    } else {
      previousFocus.current?.focus();
    }
  }, [isOpen]);

  return (
    <FocusTrap>
      <div role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <button ref={closeRef} onClick={onClose} aria-label="Schließen">×</button>
        {children}
      </div>
    </FocusTrap>
  );
}

// 3. Color Contrast (automatic check)
// Design tokens ensure 4.5:1 ratio minimum

// 4. Screen Reader Announcements
function useAnnounce() {
  return (message: string, priority: 'polite' | 'assertive' = 'polite') => {
    const el = document.getElementById('sr-announcer');
    if (el) {
      el.setAttribute('aria-live', priority);
      el.textContent = message;
    }
  };
}
```

---

## 13. DEPLOYMENT ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────┐
│                        CDN (Cloudflare)                         │
│                    Static Assets + Cache                        │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                        Load Balancer                            │
│                   SSL Termination + WAF                         │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        │                                           │
┌───────────────┐                         ┌───────────────┐
│  Frontend     │                         │   API         │
│  (Next.js)    │ ─── Internal LB ───────>│   (FastAPI)   │
│  SSR + BFF    │                         │               │
└───────────────┘                         └───────────────┘
        │                                           │
        │                                           │
┌───────────────┐                         ┌───────────────┐
│   Redis       │                         │  PostgreSQL   │
│   (Sessions)  │                         │   (RLS)       │
└───────────────┘                         └───────────────┘
```

---

## 14. TECH STACK (VERIFIED FROM REPO)

| Layer | Technology | Version | Rationale |
|-------|------------|---------|-----------|
| **Framework** | Next.js (App Router) | **16.1.1** | SSR, RSC, Server Actions |
| **React** | React + React-DOM | **19.2.3** | Concurrent features, use() |
| **Styling** | Tailwind CSS + shadcn/ui | **4.x** | New config format |
| **State** | React Query + Zustand | latest | Server/UI separation |
| **Forms** | React Hook Form + Zod | latest | Type-safe validation |
| **Tables** | TanStack Table | **8.21.3** | Already in repo |
| **Charts** | Recharts | **3.6.0** | Already in repo |
| **Maps** | MapLibre GL | latest | Open source, routing support |
| **Auth** | NextAuth.js v5 | latest | Enterprise SSO ready |
| **i18n** | next-intl | latest | App Router compatible |
| **Testing** | Vitest + Playwright | latest | Fast unit, reliable E2E |

**Verified package.json**:
```json
{
  "next": "16.1.1",
  "react": "19.2.3",
  "tailwindcss": "^4",
  "@tanstack/react-table": "^8.21.3",
  "recharts": "^3.6.0"
}
```

---

## 15. IMPLEMENTATION PHASES

### Phase 1: Foundation (Woche 1-2)
- [ ] Design System Setup (Tailwind config, tokens)
- [ ] Auth Flow (Login, Session, RBAC guards)
- [ ] Layout Shells (Platform, Tenant, Pack)
- [ ] Core Components (ScenarioCard, AuditStatus, HashDisplay)

### Phase 2: Core Modules (Woche 3-4)
- [ ] Dashboard / Work Queue
- [ ] Scenario CRUD
- [ ] Plan Version Viewer
- [ ] Audit Log UI
- [ ] Evidence Vault

### Phase 3: Tenant Admin (Woche 5)
- [ ] Site Management
- [ ] User Management
- [ ] Integration Config
- [ ] Pack Activation

### Phase 4: Routing Pack (Woche 6-7)
- [ ] Stop Import
- [ ] Team Builder
- [ ] Route Visualization
- [ ] KPI Dashboard

### Phase 5: Polish (Woche 8)
- [ ] Error States
- [ ] Empty States
- [ ] Keyboard Navigation
- [ ] Print/Export
- [ ] Performance Audit

---

## 16. PLAN LIFECYCLE STATE MACHINE (NEU)

UI muss alle Status korrekt abbilden:

```
┌─────────────────────────────────────────────────────────────────┐
│                     PLAN STATUS FLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  IMPORTED ──► SNAPSHOTTED ──► SOLVING ──► SOLVED               │
│                                   │          │                  │
│                                   ▼          ▼                  │
│                                FAILED    AUDITED                │
│                                            │                    │
│                                   ┌────────┴────────┐           │
│                                   ▼                 ▼           │
│                              AUDIT_PASS        AUDIT_FAIL       │
│                                   │                 │           │
│                                   ▼                 ▼           │
│                                LOCKED           DRAFT           │
│                                   │                 │           │
│                                   ▼                 ▼           │
│                                FROZEN          RE-SOLVE         │
│                                   │                             │
│                                   ▼                             │
│                              REPAIRING ──► REPAIRED             │
│                                                │                │
│                                                ▼                │
│                                           SUPERSEDED            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**UI Status Mapping**:
```typescript
const STATUS_CONFIG = {
  IMPORTED:    { color: 'gray',    icon: 'Upload',    actions: ['Snapshot'] },
  SNAPSHOTTED: { color: 'blue',    icon: 'Camera',    actions: ['Solve'] },
  SOLVING:     { color: 'blue',    icon: 'Loader',    actions: [], pulse: true },
  SOLVED:      { color: 'yellow',  icon: 'Check',     actions: ['Run Audit'] },
  FAILED:      { color: 'red',     icon: 'XCircle',   actions: ['Retry', 'View Error'] },
  AUDITED:     { color: 'green',   icon: 'Shield',    actions: ['Lock Plan'] },
  DRAFT:       { color: 'orange',  icon: 'Edit',      actions: ['Edit', 'Re-Solve'] },
  LOCKED:      { color: 'emerald', icon: 'Lock',      actions: ['Evidence', 'Repair'] },
  FROZEN:      { color: 'purple',  icon: 'Snowflake', actions: ['View Only'] },
  REPAIRING:   { color: 'blue',    icon: 'Wrench',    actions: [], pulse: true },
  REPAIRED:    { color: 'teal',    icon: 'CheckCircle', actions: ['Re-Audit'] },
  SUPERSEDED:  { color: 'gray',    icon: 'Archive',   actions: ['View History'] },
} as const;
```

---

## 17. SUCCESS METRICS (REVISED)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Lighthouse Score** | >90 all categories | CI check |
| **First Contentful Paint** | <1.5s | RUM |
| **Time to Interactive** | <3s | RUM |
| **Test Coverage** | >80% | Vitest |
| **A11y Violations** | 0 critical | axe-core |
| **Error Rate** | <0.1% | Sentry |

### Route-Based Bundle Budgets (REVISED)

Global <200KB ist unrealistisch mit MapLibre. Stattdessen route-based:

| Route | Budget (gzipped) | Contents |
|-------|------------------|----------|
| **Shell (initial)** | <100KB | Layout, Nav, Auth |
| **Dashboard** | +30KB | Summary cards, mini charts |
| **Scenarios List** | +40KB | Table, filters |
| **Plan Detail** | +50KB | Tabs, audit viewer |
| **Map View** | +220KB | MapLibre (lazy) |
| **KPI Dashboard** | +60KB | Recharts (lazy) |
| **Evidence Vault** | +30KB | File browser |

**Enforcement**:
```javascript
// next.config.js
module.exports = {
  experimental: {
    webpackBuildWorker: true,
  },
  // Route-specific budgets via custom webpack plugin
};
```

---

## 18. CONCLUSION (REVISED POST-CHALLENGE)

Die Architektur ist **solide konzipiert** nach Challenge-Korrekturen:

### Blocker FIXED:
| # | Issue | Status |
|---|-------|--------|
| 1 | Cookie Isolation (`__Host-` prefix) | ✅ Documented |
| 2 | Tenant from Session (not headers) | ✅ Documented |
| 3 | Frame-busting removed (CSP only) | ✅ Fixed |
| 4 | Next.js 16.1.1 (not 14) | ✅ Corrected |
| 5 | Route-based bundle budgets | ✅ Added |
| 6 | State Machine documented | ✅ Added |

### Nächste Schritte:
1. **Security First**: Cookie-Spec + Backend Guards implementieren
2. **Shell**: Platform + Tenant Layout mit Site-Selector
3. **Core Screens**: Scenarios → Plans → Audits → Evidence
4. **Pack Workspace**: Routing Pack UI

**Frontend-Verzeichnis**: `frontend_v5/` (bereits vorhanden mit Next.js 16.1.1)

