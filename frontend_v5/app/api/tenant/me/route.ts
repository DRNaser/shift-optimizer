// =============================================================================
// SOLVEREIGN BFF - Tenant Me Endpoint
// =============================================================================
// GET /api/tenant/me
//
// TRUST ANCHOR:
// - Reads tenant context from __Host-sv_tenant cookie (HttpOnly, Secure)
// - Cookie is set by auth flow, contains encrypted tenant_id + user_id
// - This endpoint is the ONLY source of truth for frontend tenant context
// - Never trust client-provided tenant/site IDs
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import type { TenantMeResponse, Tenant, Site, User, PackId } from '@/lib/tenant-types';

// =============================================================================
// MOCK DATA (Replace with actual session/DB lookup in production)
// =============================================================================

const MOCK_TENANT: Tenant = {
  id: 'tenant-lts-001',
  slug: 'lts-transport',
  name: 'LTS Transport u. Logistik GmbH',
  logo_url: '/logos/lts.png',
  primary_color: '#0D4B8A',
  created_at: '2024-01-01T00:00:00Z',
  settings: {
    timezone: 'Europe/Berlin',
    locale: 'de-DE',
    week_start_day: 1,
    default_freeze_hours: 12,
    enabled_packs: ['routing'],
    features: {
      multi_site: true,
      custom_domain: false,
      sso_enabled: false,
      api_access: true,
      evidence_retention_days: 365,
    },
  },
};

const MOCK_SITES: Site[] = [
  {
    id: 'site-hh-nord',
    tenant_id: 'tenant-lts-001',
    code: 'HH-NORD',
    name: 'Hamburg Nord',
    timezone: 'Europe/Berlin',
    is_active: true,
    created_at: '2024-01-01T00:00:00Z',
    settings: {
      default_depot_id: 'depot-hh-001',
      shift_start_time: '06:00',
      shift_end_time: '22:00',
      max_drivers_per_shift: 200,
    },
  },
  {
    id: 'site-muc-west',
    tenant_id: 'tenant-lts-001',
    code: 'MUC-WEST',
    name: 'München West',
    timezone: 'Europe/Berlin',
    is_active: true,
    created_at: '2024-01-15T00:00:00Z',
    settings: {
      default_depot_id: 'depot-muc-001',
      shift_start_time: '05:30',
      shift_end_time: '22:00',
      max_drivers_per_shift: 150,
    },
  },
];

const MOCK_USER: User = {
  id: 'user-001',
  email: 'planner@lts-transport.de',
  name: 'Max Müller',
  tenant_id: 'tenant-lts-001',
  role: 'APPROVER',
  site_ids: [],  // Empty = access to all sites
  permissions: [
    'scenario:read', 'scenario:write',
    'plan:read', 'plan:write', 'plan:lock', 'plan:repair',
    'audit:read',
    'evidence:read', 'evidence:export',
  ],
  last_login_at: new Date().toISOString(),
};

// =============================================================================
// HANDLER
// =============================================================================

export async function GET(request: NextRequest) {
  // In production: Extract tenant/user from cookie
  // const cookieStore = await cookies();
  // const sessionCookie = cookieStore.get('__Host-sv_tenant');
  // if (!sessionCookie) {
  //   return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  // }
  // const session = decryptSession(sessionCookie.value);
  // const tenant = await fetchTenant(session.tenant_id);
  // const user = await fetchUser(session.user_id);
  // const sites = await fetchSites(session.tenant_id, user.site_ids);

  // Get current site from session (server-authoritative)
  // In production: const currentSiteId = session.current_site_id;
  const cookieStore = await cookies();
  const sitePreference = cookieStore.get('sv_current_site')?.value;
  const currentSiteId = sitePreference && MOCK_SITES.find(s => s.id === sitePreference)
    ? sitePreference
    : MOCK_SITES[0]?.id || null;

  const response: TenantMeResponse = {
    tenant: MOCK_TENANT,
    sites: MOCK_SITES,
    user: MOCK_USER,
    enabled_packs: ['routing'] as PackId[],  // Core is always implicit
    current_site_id: currentSiteId,
  };

  return NextResponse.json(response);
}
