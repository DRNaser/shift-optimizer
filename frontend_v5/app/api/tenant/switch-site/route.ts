// =============================================================================
// SOLVEREIGN BFF - Switch Site Endpoint
// =============================================================================
// POST /api/tenant/switch-site
//
// TRUST ANCHOR:
// - Validates site_id belongs to current tenant
// - Updates session.current_site_id (server-side state)
// - Frontend only updates AFTER server ACK
// - Audit logs the site switch
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import type { SwitchSiteRequest, SwitchSiteResponse } from '@/lib/tenant-types';

// =============================================================================
// MOCK VALIDATION (Replace with actual DB lookup in production)
// =============================================================================

const VALID_SITE_IDS = ['site-hh-nord', 'site-muc-west'];

// =============================================================================
// HANDLER
// =============================================================================

export async function POST(request: NextRequest) {
  try {
    const body: SwitchSiteRequest = await request.json();
    const { site_id } = body;

    if (!site_id) {
      return NextResponse.json(
        { error: 'site_id is required' },
        { status: 400 }
      );
    }

    // In production: Validate site belongs to tenant from session
    // const cookieStore = await cookies();
    // const sessionCookie = cookieStore.get('__Host-sv_tenant');
    // const session = decryptSession(sessionCookie.value);
    // const sites = await fetchSites(session.tenant_id, session.user.site_ids);
    // if (!sites.find(s => s.id === site_id)) {
    //   return NextResponse.json({ error: 'Site not found' }, { status: 404 });
    // }

    // Mock validation
    if (!VALID_SITE_IDS.includes(site_id)) {
      return NextResponse.json(
        { error: 'Site not found or not accessible' },
        { status: 404 }
      );
    }

    // Update session with new current_site_id
    // In production: Update encrypted session cookie
    // await updateSession(session.user_id, { current_site_id: site_id });

    // Set cookie to persist site preference (server-side)
    const cookieStore = await cookies();
    cookieStore.set('sv_current_site', site_id, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict',
      path: '/',
      maxAge: 60 * 60 * 24 * 30, // 30 days
    });

    // Audit log the site switch
    // await auditLog({
    //   tenant_id: session.tenant_id,
    //   user_id: session.user_id,
    //   action: 'SITE_SWITCH',
    //   details: { from_site_id: session.current_site_id, to_site_id: site_id },
    // });

    const response: SwitchSiteResponse = {
      success: true,
      current_site_id: site_id,
    };

    return NextResponse.json(response);
  } catch (error) {
    console.error('[switch-site] Error:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
