# API Types Reference

## Auth Types

### Login Request/Response
```typescript
// POST /api/auth/login
interface LoginRequest {
  email: string;
  password: string;
}

interface LoginResponse {
  user_id: string;
  email: string;
  display_name: string | null;
  role_name: string;
  tenant_id: number | null;
  site_id: number | null;
  is_platform_admin: boolean;
}
// Sets cookie: admin_session (HttpOnly)
```

### Current User
```typescript
// GET /api/auth/me
interface MeResponse {
  user_id: string;
  email: string;
  display_name: string | null;
  role_name: string;
  tenant_id: number | null;
  site_id: number | null;
  is_platform_scope: boolean;
  active_tenant_id: number | null;  // Context switching
  active_site_id: number | null;
  permissions: string[];
}
```

---

## Platform Admin Types

### Tenant
```typescript
// GET/POST /api/platform/tenants
interface TenantCreate {
  name: string;  // 2-100 chars
  owner_display_name?: string;
}

interface TenantResponse {
  id: number;
  name: string;
  is_active: boolean;
  created_at: string;  // ISO datetime
  user_count?: number;
  site_count?: number;
}
```

### Site
```typescript
// GET/POST /api/platform/tenants/{tenant_id}/sites
interface SiteCreate {
  name: string;  // 2-100 chars
  code?: string;  // max 10 chars, auto-generated if not provided
}

interface SiteResponse {
  id: number;
  tenant_id: number;
  name: string;
  code: string | null;
  created_at: string;
}
```

### User
```typescript
// GET/POST /api/platform/users
interface UserCreate {
  email: string;  // EmailStr
  display_name?: string;  // max 100 chars
  password: string;  // min 8 chars
  tenant_id: number;
  site_id?: number;
  role_name: string;  // tenant_admin, dispatcher, etc.
}

interface UserResponse {
  id: string;  // UUID
  email: string;
  display_name: string | null;
  is_active: boolean;
  is_locked: boolean;
  created_at: string;
  last_login_at: string | null;
  bindings: BindingInfo[];
}

interface BindingInfo {
  id: number;
  tenant_id: number | null;
  site_id: number | null;
  role_id: number;
  role_name: string;
  is_active: boolean;
}
```

### Binding
```typescript
// POST /api/platform/bindings
interface BindingCreate {
  user_id: string;
  tenant_id: number;
  site_id?: number;
  role_name: string;
}

interface BindingResponse {
  id: number;
  user_id: string;
  tenant_id: number | null;
  site_id: number | null;
  role_id: number;
  role_name: string;
  is_active: boolean;
}
```

### Role
```typescript
// GET /api/platform/roles
interface RoleResponse {
  id: number;
  name: string;  // platform_admin, tenant_admin, dispatcher, etc.
  display_name: string;
  description: string | null;
  is_system: boolean;
}
```

### Permission
```typescript
// GET /api/platform/permissions
interface PermissionResponse {
  id: number;
  key: string;  // platform.tenants.write, portal.summary.read, etc.
  display_name: string;
  description: string | null;
  category: string | null;  // platform, tenant, portal
}
```

### Password Reset
```typescript
// POST /api/platform/users/{user_id}/request-password-reset
interface PasswordResetRequest {
  send_email?: boolean;  // default false (pilot mode)
}

interface PasswordResetResponse {
  reset_token: string;  // Only in pilot mode
  reset_link: string;
  expires_in_minutes: number;  // 60
  message: string;
}

// POST /api/platform/complete-password-reset (PUBLIC)
interface PasswordResetComplete {
  token: string;
  new_password: string;  // min 8 chars
}
```

### Context Switching
```typescript
// GET/POST/DELETE /api/platform/context
interface ContextSetRequest {
  tenant_id: number;
  site_id?: number;
}

interface ContextResponse {
  active_tenant_id: number | null;
  active_site_id: number | null;
  tenant_name: string | null;
  site_name: string | null;
}
```

### Session Management
```typescript
// GET /api/platform/sessions
interface SessionResponse {
  id: string;
  user_id: string;
  user_email: string;
  tenant_id: number | null;
  site_id: number | null;
  role_name: string;
  created_at: string;
  expires_at: string;
  last_activity_at: string | null;
  is_platform_scope: boolean;
}

// POST /api/platform/sessions/revoke
interface SessionRevokeRequest {
  user_id?: string;  // Revoke by user
  tenant_id?: number;  // Revoke by tenant
  all?: boolean;  // Revoke all (emergency)
  reason?: string;  // default "admin_revoke"
}
```

### User Lock/Disable
```typescript
// POST /api/platform/users/{user_id}/disable
// POST /api/platform/users/{user_id}/enable
// (No body required)

// POST /api/platform/users/{user_id}/lock
interface UserLockRequest {
  reason: string;  // 1-500 chars
}

// POST /api/platform/users/{user_id}/unlock
// (No body required)
```

---

## Portal Admin Types

### Summary
```typescript
// GET /api/portal-admin/summary
interface PortalSummary {
  snapshot_id: number;
  plan_week: string;
  total_drivers: number;
  sent_count: number;
  read_count: number;
  acked_count: number;
  declined_count: number;
  pending_count: number;
}
```

### Driver Details
```typescript
// GET /api/portal-admin/details
interface DriverDetail {
  driver_id: number;
  driver_name: string;
  contact_info: string | null;
  notification_status: 'pending' | 'sent' | 'delivered' | 'failed';
  read_at: string | null;
  ack_status: 'pending' | 'accepted' | 'declined' | null;
  acked_at: string | null;
  decline_reason: string | null;
}
```

### Resend Notification
```typescript
// POST /api/portal-admin/resend
interface ResendRequest {
  driver_id: number;
  channel?: 'whatsapp' | 'email' | 'sms';  // default whatsapp
}

interface ResendResponse {
  success: boolean;
  message_id: string | null;
  error: string | null;
}
```

---

## Portal Public Types (Driver Portal)

### Session Exchange
```typescript
// GET /api/portal/session?t={jwt_token}
// Sets cookie: portal_session
// Returns driver info
interface PortalSessionResponse {
  driver_id: number;
  driver_name: string;
  snapshot_id: number;
  plan_week: string;
  expires_at: string;
}
```

### Read Receipt
```typescript
// POST /api/portal/read
// (No body - uses portal_session cookie)
interface ReadResponse {
  success: boolean;
  read_at: string;
}
```

### Acknowledgment
```typescript
// POST /api/portal/ack
interface AckRequest {
  accepted: boolean;
  decline_reason?: string;  // Required if accepted=false
}

interface AckResponse {
  success: boolean;
  acked_at: string;
  status: 'accepted' | 'declined';
}
```

---

## Error Response Format

All API errors follow this format:

```typescript
interface ApiError {
  error: {
    code: string;  // e.g., "TENANT_ALREADY_EXISTS", "HTTP_401"
    message: string;
    field?: string;  // For validation errors
    details?: Record<string, unknown>;
  };
}
```

### Common Error Codes
| Code | Status | Meaning |
|------|--------|---------|
| `TENANT_NAME_INVALID` | 400 | Invalid tenant name format |
| `TENANT_ALREADY_EXISTS` | 409 | Duplicate tenant name |
| `USER_ALREADY_EXISTS` | 400 | Duplicate email |
| `RESOURCE_NOT_FOUND` | 404 | Entity not found |
| `INSUFFICIENT_PERMISSIONS` | 403 | Role cannot perform action |
| `INTERNAL_ERROR` | 500 | Server error (includes correlation_id) |

---

## Role Hierarchy

```
platform_admin (5) - Can assign any role
    ↓
tenant_admin (4) - Can assign tenant_admin and below
    ↓
operator_admin (3)
    ↓
dispatcher (2)
    ↓
ops_readonly (1)
```

### Role Assignment Rules
- `platform_admin` can assign any role
- `tenant_admin` can assign `tenant_admin` or below
- Other roles cannot assign roles
- `platform_admin` bindings have `tenant_id = NULL`
