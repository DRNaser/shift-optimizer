# SOLVEREIGN Frontend Authentication Setup

> **Version**: V3.7.2 (Wien Pilot)
> **Last Updated**: 2026-01-08

## Overview

SOLVEREIGN uses Microsoft Entra ID (formerly Azure AD) for authentication via MSAL.js.
This document covers the setup, configuration, and usage of the auth system.

---

## Quick Start

### 1. Environment Variables

Create `.env.local` in `frontend_v5/`:

```bash
# Required: Azure AD App Registration
NEXT_PUBLIC_AZURE_AD_CLIENT_ID=<your-app-client-id>
NEXT_PUBLIC_AZURE_AD_TENANT_ID=<your-azure-tenant-id>
NEXT_PUBLIC_AZURE_AD_REDIRECT_URI=http://localhost:3000
NEXT_PUBLIC_AZURE_AD_API_SCOPE=api://<your-app-client-id>/access_as_user
```

### 2. Azure Portal Configuration

1. Go to **Azure Portal > App registrations > Your App**
2. Under **Authentication**:
   - Add redirect URI: `http://localhost:3000` (dev)
   - Add redirect URI: `https://your-domain.com` (prod)
   - Enable **ID tokens** and **Access tokens**
3. Under **API permissions**:
   - Add `openid`, `profile`, `email`, `offline_access`
   - Add your custom API scope
4. Under **App roles**, create:
   - `Platform.Admin`
   - `Tenant.Admin`
   - `Approver`
   - `Dispatcher`
   - `Viewer`

### 3. Run the App

```bash
cd frontend_v5
npm install
npm run dev
```

---

## Architecture

### Auth Components

```
lib/auth/
├── msal-config.ts      # MSAL configuration
├── auth-context.tsx    # React context + useAuth hook
├── protected-route.tsx # Route protection components
├── api-client.ts       # Authenticated API calls
└── index.ts           # Module exports
```

### Auth Flow

```
┌─────────────────────────────────────────────────────────────┐
│                         User                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    ProtectedRoute                           │
│  - Checks isAuthenticated                                   │
│  - Checks requiredRoles                                     │
│  - Shows login prompt if not authenticated                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     AuthProvider                            │
│  - Manages MSAL instance                                    │
│  - Handles login/logout                                     │
│  - Provides useAuth() hook                                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    useApi() hook                            │
│  - Injects Bearer token into requests                       │
│  - Handles token refresh                                    │
│  - Typed API methods                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Usage Examples

### Basic Authentication

```tsx
'use client';

import { useAuth } from '@/lib/auth';

export function MyComponent() {
  const { user, isAuthenticated, isLoading, login, logout } = useAuth();

  if (isLoading) return <div>Loading...</div>;

  if (!isAuthenticated) {
    return (
      <button onClick={() => login()}>
        Sign In with Microsoft
      </button>
    );
  }

  return (
    <div>
      <p>Welcome, {user?.name}</p>
      <p>Roles: {user?.roles.join(', ')}</p>
      <button onClick={() => logout()}>Sign Out</button>
    </div>
  );
}
```

### Protected Routes

```tsx
import { ProtectedRoute, RequireApprover } from '@/lib/auth';

// Basic protection (any authenticated user)
<ProtectedRoute>
  <Dashboard />
</ProtectedRoute>

// Role-based protection
<ProtectedRoute requiredRoles={['Platform.Admin', 'Tenant.Admin']}>
  <AdminPanel />
</ProtectedRoute>

// Convenience components
<RequireApprover>
  <PublishButton />
</RequireApprover>
```

### Authenticated API Calls

```tsx
'use client';

import { useApi } from '@/lib/auth';

export function PlanView({ planId }: { planId: string }) {
  const { api, isAuthenticated } = useApi();
  const [plan, setPlan] = useState(null);

  useEffect(() => {
    if (isAuthenticated) {
      api.plans.get(planId).then(response => {
        if (response.data) setPlan(response.data);
      });
    }
  }, [planId, isAuthenticated]);

  return <div>{plan?.name}</div>;
}
```

### Publishing with Freeze Handling

```tsx
import { PublishModal } from '@/components/plans/publish-modal';

<PublishModal
  isOpen={showPublish}
  onClose={() => setShowPublish(false)}
  planId={planId}
  onPublishSuccess={(snapshotId) => {
    console.log('Published:', snapshotId);
    router.refresh();
  }}
/>
```

### Legacy Snapshot Warnings

```tsx
import {
  LegacyBadge,
  LegacySnapshotAlert,
  SnapshotHistoryItem
} from '@/components/plans/legacy-snapshot-warning';

// In tables/lists
{snapshot.is_legacy && <LegacyBadge />}

// In detail views
{snapshot.is_legacy && <LegacySnapshotAlert />}

// In snapshot history
<SnapshotHistoryItem snapshot={snapshot} />
```

---

## Role Hierarchy

| Role | Permissions |
|------|-------------|
| `Platform.Admin` | Full platform access, all tenants |
| `Tenant.Admin` | Manage own tenant, approve/publish |
| `Approver` | Approve and publish plans |
| `Dispatcher` | View plans, request repairs |
| `Viewer` | Read-only access |

### Role Checking

```tsx
const { hasRole, hasAnyRole } = useAuth();

// Check single role
if (hasRole('Platform.Admin')) { /* ... */ }

// Check multiple roles (OR)
if (hasAnyRole(['Approver', 'Tenant.Admin', 'Platform.Admin'])) {
  // Can approve
}
```

---

## Error Handling

### API Error Codes

| Code | HTTP | Meaning |
|------|------|---------|
| `UNAUTHORIZED` | 401 | Token missing or expired |
| `FORBIDDEN` | 403 | Missing required role |
| `APP_TOKEN_NOT_ALLOWED` | 403 | M2M token cannot do this |
| `FREEZE_WINDOW_ACTIVE` | 409 | Publish blocked by freeze |
| `VALIDATION_ERROR` | 422 | Invalid request body |

### Handling in Components

```tsx
const response = await api.plans.publish(planId, { reason });

if (response.error) {
  switch (response.error.code) {
    case 'FREEZE_WINDOW_ACTIVE':
      // Show freeze warning
      break;
    case 'FORBIDDEN':
      // Show permission error
      break;
    default:
      // Generic error
  }
}
```

---

## Development Mode

When MSAL is not configured (`NEXT_PUBLIC_AZURE_AD_CLIENT_ID` not set):
- `ProtectedRoute` allows all access
- `useAuth()` returns unauthenticated state
- API calls will fail with 401 (backend requires token)

### Local Testing with Mock User

```javascript
// In browser console (dev only)
localStorage.setItem('sv_platform_user', JSON.stringify({
  email: 'test@example.com',
  name: 'Test User',
  id: 'test-001',
  role: 'platform_admin'
}));

// Clear mock
localStorage.removeItem('sv_platform_user');
```

---

## E2E Smoke Test

### Prerequisites
1. Environment variables configured
2. Backend running at `http://localhost:8000`
3. Test user in Entra ID with appropriate roles

### Test Flow

1. **Open App**: `http://localhost:3000`
2. **Sign In**: Click "Sign In with Microsoft"
3. **Verify User**: Check user name and roles displayed
4. **Test API**: Navigate to plans, verify data loads
5. **Test RBAC**: Try accessing admin routes with different roles
6. **Test Publish**: Open publish modal, verify freeze detection
7. **Sign Out**: Click logout, verify redirect to login

### Verification Checklist

- [ ] Login popup opens and redirects correctly
- [ ] User info displayed after login
- [ ] Token attached to API requests (check Network tab)
- [ ] Protected routes redirect unauthenticated users
- [ ] Role-gated routes show "Access Denied" for wrong roles
- [ ] Freeze window detected and displayed
- [ ] Force publish only visible for Approver+
- [ ] Logout clears session

---

## Troubleshooting

### "MSAL not configured"

Check environment variables are set correctly:
```bash
# Verify in browser console
console.log(process.env.NEXT_PUBLIC_AZURE_AD_CLIENT_ID);
```

### "Token expired"

MSAL handles refresh automatically. If issues persist:
- Clear localStorage
- Sign out and sign in again

### "CORS error on login"

Check redirect URIs in Azure Portal match exactly:
- Include trailing slash if used
- Match http vs https
- Match port numbers

### "Missing roles in token"

1. Verify App Roles created in Azure Portal
2. Assign roles to user in Enterprise Applications
3. Consent to permissions (admin consent may be required)

---

## Files Reference

| File | Purpose |
|------|---------|
| `lib/auth/msal-config.ts` | MSAL configuration and scopes |
| `lib/auth/auth-context.tsx` | React context, useAuth hook |
| `lib/auth/protected-route.tsx` | Route protection components |
| `lib/auth/api-client.ts` | Authenticated API client |
| `components/plans/publish-modal.tsx` | Publish with freeze handling |
| `components/plans/legacy-snapshot-warning.tsx` | Legacy snapshot warnings |
| `app/providers.tsx` | AuthProvider wrapper |
