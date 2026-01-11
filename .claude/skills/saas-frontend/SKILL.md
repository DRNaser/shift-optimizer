---
name: saas-frontend
description: Build and wire SOLVEREIGN SaaS frontend pages. Use when creating new pages, components, API routes, or connecting features to the backend. Handles routing, auth, RBAC, and API integration.
allowed-tools: Read, Grep, Glob, Edit, Write, Bash(npx:*)
---

# SOLVEREIGN SaaS Frontend Builder

## Quick Reference

### Tech Stack
- **Framework**: Next.js 14+ (App Router)
- **Styling**: Tailwind CSS + shadcn/ui
- **Auth**: Internal RBAC (Argon2id + HttpOnly cookies)
- **API**: FastAPI backend at `:8000`
- **State**: React Context + Server Components

### Key Directories
```
frontend_v5/
├── app/                      # Next.js App Router
│   ├── (platform)/          # Platform admin routes (grouped)
│   │   ├── platform-admin/  # Admin dashboard pages
│   │   ├── home/            # Platform home after login
│   │   └── select-tenant/   # Context switcher
│   ├── (tenant)/            # Tenant-scoped routes
│   │   ├── dashboard/       # Tenant dashboard
│   │   ├── scenarios/       # Plan scenarios
│   │   └── imports/         # Data imports
│   ├── (packs)/             # Pack-specific routes
│   │   └── roster/          # Roster workbench
│   ├── platform/            # Auth routes (no group)
│   │   └── login/           # Login page
│   ├── packs/               # Pack entry points
│   ├── my-plan/             # Driver portal (public)
│   └── api/                 # BFF API routes
│       ├── auth/            # Auth endpoints
│       ├── platform-admin/  # Admin BFF
│       └── portal/          # Portal BFF
├── components/
│   ├── ui/                  # Base UI components
│   ├── layout/              # Layout components
│   ├── domain/              # Domain-specific components
│   ├── platform/            # Platform admin components
│   ├── tenant/              # Tenant components
│   ├── portal/              # Driver portal components
│   └── plans/               # Plan management components
└── lib/
    ├── auth/                # Auth utilities
    ├── hooks/               # Custom hooks
    ├── platform-api.ts      # Platform API client
    ├── tenant-api.ts        # Tenant API client
    ├── portal-api.ts        # Portal API client
    └── types.ts             # Shared types
```

---

## Page Creation Checklist

### 1. Determine Route Group

| Use Case | Route Group | Layout | Auth Required |
|----------|-------------|--------|---------------|
| Platform admin pages | `(platform)/platform-admin/` | PlatformLayout | platform_admin |
| Tenant operations | `(tenant)/` | TenantLayout | tenant_admin+ |
| Pack features | `(packs)/` | PackLayout | dispatcher+ |
| Driver portal | `my-plan/` | None | portal_session |
| Auth pages | `platform/` | MinimalLayout | None |

### 2. Create Page File

```tsx
// app/(platform)/platform-admin/[feature]/page.tsx
import { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Feature Name | SOLVEREIGN',
};

export default function FeaturePage() {
  return (
    <div className="container mx-auto py-6">
      <h1 className="text-2xl font-bold mb-6">Feature Name</h1>
      {/* Page content */}
    </div>
  );
}
```

### 3. Add to Sidebar Navigation

Edit `components/layout/platform-sidebar.tsx`:

```tsx
const navigation = [
  // ... existing items
  {
    name: 'New Feature',
    href: '/platform-admin/new-feature',
    icon: IconComponent,
  },
];
```

---

## API Integration Patterns

### BFF Route Pattern (Required for all API calls)

Browser calls Next.js API route, which signs requests to FastAPI:

```
Browser → /api/platform-admin/tenants → FastAPI /api/platform/tenants
```

### Create BFF Route

```tsx
// app/api/platform-admin/tenants/route.ts
import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';

const BACKEND_URL = process.env.SOLVEREIGN_BACKEND_URL || 'http://localhost:8000';

export async function GET(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('admin_session');

  if (!sessionCookie) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const response = await fetch(`${BACKEND_URL}/api/platform/tenants`, {
    headers: {
      Cookie: `admin_session=${sessionCookie.value}`,
    },
    cache: 'no-store',
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}

export async function POST(request: NextRequest) {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get('admin_session');

  if (!sessionCookie) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const body = await request.json();

  const response = await fetch(`${BACKEND_URL}/api/platform/tenants`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Cookie: `admin_session=${sessionCookie.value}`,
    },
    body: JSON.stringify(body),
    cache: 'no-store',
  });

  const data = await response.json();
  return NextResponse.json(data, { status: response.status });
}
```

### Frontend API Call

```tsx
// In component or page
async function fetchTenants() {
  const response = await fetch('/api/platform-admin/tenants');
  if (!response.ok) {
    throw new Error('Failed to fetch tenants');
  }
  return response.json();
}
```

---

## Backend API Endpoints Reference

### Auth (`/api/auth/*`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/login` | POST | `{email, password}` → session cookie |
| `/api/auth/logout` | POST | Revoke session |
| `/api/auth/me` | GET | Current user info |

### Platform Admin (`/api/platform/*`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/platform/tenants` | GET | List all tenants |
| `/api/platform/tenants` | POST | Create tenant |
| `/api/platform/tenants/{id}` | GET | Tenant details |
| `/api/platform/tenants/{id}/sites` | GET/POST | Sites for tenant |
| `/api/platform/users` | GET | List users |
| `/api/platform/users` | POST | Create user |
| `/api/platform/users/{id}/request-password-reset` | POST | Reset password |
| `/api/platform/bindings` | POST | Create user binding |
| `/api/platform/roles` | GET | List roles |
| `/api/platform/permissions` | GET | List permissions |
| `/api/platform/context` | GET/POST/DELETE | Context switching |
| `/api/platform/sessions` | GET | List sessions |
| `/api/platform/sessions/revoke` | POST | Revoke sessions |

### Portal Admin (`/api/portal-admin/*`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/portal-admin/summary` | GET | KPI summary |
| `/api/portal-admin/details` | GET | Driver details |
| `/api/portal-admin/resend` | POST | Resend notification |
| `/api/portal-admin/export` | GET | Export CSV |

### Portal Public (`/api/portal/*`)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/portal/session` | GET | Token → cookie |
| `/api/portal/read` | POST | Record read receipt |
| `/api/portal/ack` | POST | Accept/decline plan |

---

## Component Patterns

### Data Table with Loading

```tsx
'use client';

import { useState, useEffect } from 'react';
import { ApiError } from '@/components/ui/api-error';

interface DataItem {
  id: number;
  name: string;
}

export function DataTable() {
  const [data, setData] = useState<DataItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const response = await fetch('/api/platform-admin/data');
        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.error?.message || 'Failed to fetch');
        }
        const result = await response.json();
        setData(result);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  if (loading) {
    return <div className="animate-pulse">Loading...</div>;
  }

  if (error) {
    return <ApiError message={error} onRetry={() => window.location.reload()} />;
  }

  return (
    <table className="w-full">
      <thead>
        <tr>
          <th className="text-left p-2">ID</th>
          <th className="text-left p-2">Name</th>
        </tr>
      </thead>
      <tbody>
        {data.map((item) => (
          <tr key={item.id}>
            <td className="p-2">{item.id}</td>
            <td className="p-2">{item.name}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

### Form with Validation

```tsx
'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';

interface FormData {
  name: string;
  email: string;
}

export function CreateForm({ onSuccess }: { onSuccess?: () => void }) {
  const [formData, setFormData] = useState<FormData>({ name: '', email: '' });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const response = await fetch('/api/platform-admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData),
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error?.message || 'Failed to create');
      }

      onSuccess?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div className="bg-red-50 text-red-700 p-3 rounded">{error}</div>
      )}

      <div>
        <label className="block text-sm font-medium mb-1">Name</label>
        <input
          type="text"
          value={formData.name}
          onChange={(e) => setFormData({ ...formData, name: e.target.value })}
          className="w-full border rounded p-2"
          required
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Email</label>
        <input
          type="email"
          value={formData.email}
          onChange={(e) => setFormData({ ...formData, email: e.target.value })}
          className="w-full border rounded p-2"
          required
        />
      </div>

      <Button type="submit" disabled={submitting}>
        {submitting ? 'Creating...' : 'Create'}
      </Button>
    </form>
  );
}
```

---

## Auth & RBAC Patterns

### Protected Route Check

```tsx
// lib/auth/protected-route.tsx
'use client';

import { useAuth } from '@/lib/auth/auth-context';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';

export function ProtectedRoute({
  children,
  requiredRole,
}: {
  children: React.ReactNode;
  requiredRole?: string;
}) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.push('/platform/login');
    }
    if (!loading && user && requiredRole && user.role_name !== requiredRole) {
      router.push('/unauthorized');
    }
  }, [user, loading, router, requiredRole]);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return null;
  }

  return <>{children}</>;
}
```

### Role-Based UI

```tsx
function AdminPanel() {
  const { user } = useAuth();

  // Only platform_admin sees this
  if (user?.role_name !== 'platform_admin') {
    return null;
  }

  return (
    <div className="bg-yellow-50 p-4 rounded">
      <h3>Admin Controls</h3>
      {/* Admin-only features */}
    </div>
  );
}
```

---

## Page Templates

### List Page

```tsx
// app/(platform)/platform-admin/[resource]/page.tsx
import { Metadata } from 'next';
import { ResourceTable } from './resource-table';
import { CreateResourceButton } from './create-resource-button';

export const metadata: Metadata = {
  title: 'Resources | SOLVEREIGN',
};

export default function ResourcesPage() {
  return (
    <div className="container mx-auto py-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Resources</h1>
        <CreateResourceButton />
      </div>
      <ResourceTable />
    </div>
  );
}
```

### Detail Page

```tsx
// app/(platform)/platform-admin/[resource]/[id]/page.tsx
import { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { ResourceDetail } from './resource-detail';

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  return {
    title: `Resource ${id} | SOLVEREIGN`,
  };
}

export default async function ResourceDetailPage({ params }: Props) {
  const { id } = await params;

  return (
    <div className="container mx-auto py-6">
      <ResourceDetail id={id} />
    </div>
  );
}
```

### Form Page

```tsx
// app/(platform)/platform-admin/[resource]/new/page.tsx
import { Metadata } from 'next';
import { CreateResourceForm } from './create-resource-form';

export const metadata: Metadata = {
  title: 'Create Resource | SOLVEREIGN',
};

export default function CreateResourcePage() {
  return (
    <div className="container mx-auto py-6 max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">Create Resource</h1>
      <CreateResourceForm />
    </div>
  );
}
```

---

## Current SaaS Pages Map

### Platform Admin (`/platform-admin/`)
| Page | File | Status |
|------|------|--------|
| Dashboard | `page.tsx` | Done |
| Tenants List | `tenants/page.tsx` | Done |
| Tenant Detail | `tenants/[tenantId]/page.tsx` | Done |
| Create Tenant | `tenants/new/page.tsx` | Done |
| Users List | `users/page.tsx` | Done |
| Create User | `users/new/page.tsx` | Done |
| Roles | `roles/page.tsx` | Done |
| Permissions | `permissions/page.tsx` | Done |
| Sessions | `sessions/page.tsx` | Done |

### Auth (`/platform/`)
| Page | File | Status |
|------|------|--------|
| Login | `login/page.tsx` | Done |
| Home (after login) | `home/page.tsx` | Done |

### Context Switching
| Page | File | Status |
|------|------|--------|
| Select Tenant | `select-tenant/page.tsx` | Done |

### Portal Admin (`/portal-admin/`)
| Page | File | Status |
|------|------|--------|
| Dashboard | `dashboard/page.tsx` | Done |

### Missing/TODO Pages
| Page | Route | Priority |
|------|-------|----------|
| Password Reset | `/platform/reset-password` | High |
| User Detail | `/platform-admin/users/[id]` | Medium |
| Audit Log | `/platform-admin/audit` | Medium |
| Settings | `/platform-admin/settings` | Low |

---

## Build & Verify Commands

```bash
# Type check
cd frontend_v5 && npx tsc --noEmit

# Build
cd frontend_v5 && npx next build

# Dev server
cd frontend_v5 && npm run dev

# Lint
cd frontend_v5 && npm run lint
```

---

## Common Errors & Fixes

### "Unauthorized" on API calls
- Check `admin_session` cookie is being forwarded
- Verify BFF route reads cookies correctly

### "CORS error"
- All API calls must go through BFF routes
- Never call FastAPI directly from browser

### "Hydration mismatch"
- Use `'use client'` for components with state
- Wrap browser APIs in `useEffect`

### "Module not found"
- Check `@/` alias points to `frontend_v5/`
- Verify file exists at expected path

---

## Examples

### Example 1: Add new "Audit Log" page

1. Create page: `app/(platform)/platform-admin/audit/page.tsx`
2. Create BFF: `app/api/platform-admin/audit/route.ts`
3. Add to sidebar: `components/layout/platform-sidebar.tsx`
4. Build & verify: `npx next build`

### Example 2: Add form field to Create User

1. Edit: `app/(platform)/platform-admin/users/new/page.tsx`
2. Update type: `lib/types.ts`
3. Verify API accepts field: Check FastAPI schema

### Example 3: Create new tenant-scoped page

1. Create in `app/(tenant)/feature/page.tsx`
2. Use tenant layout for sidebar
3. Pass tenant context via headers in BFF
