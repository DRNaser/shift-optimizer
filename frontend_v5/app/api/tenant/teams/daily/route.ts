// =============================================================================
// SOLVEREIGN BFF - Teams Daily Endpoint
// =============================================================================
// GET /api/tenant/teams/daily?date=YYYY-MM-DD - List daily team assignments
//
// 2-PERSON ENFORCEMENT:
// - GET returns demand_status per assignment
// - MISMATCH_UNDER = stop requires 2 but team has 1
// - MISMATCH_OVER = team has 2 but stop only needs 1 (warning only)
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import { cookies } from 'next/headers';
import type { TeamDailyAssignment, Team } from '@/lib/tenant-api';

async function getTenantContext() {
  const cookieStore = await cookies();
  const tenantCode = cookieStore.get('sv_tenant_code')?.value || 'lts-transport';
  const siteCode = cookieStore.get('sv_current_site')?.value || 'wien';
  return { tenantCode, siteCode };
}

// =============================================================================
// MOCK DATA
// =============================================================================

const MOCK_TEAMS: Team[] = [
  {
    id: 'team-001',
    team_code: 'T-001',
    driver_1_id: 'drv-001',
    driver_1_name: 'Max Mueller',
    driver_2_id: 'drv-002',
    driver_2_name: 'Hans Schmidt',
    team_size: 2,
    skills: ['MONTAGE_BASIC', 'MONTAGE_ADVANCED'],
    is_active: true,
  },
  {
    id: 'team-002',
    team_code: 'T-002',
    driver_1_id: 'drv-003',
    driver_1_name: 'Peter Weber',
    driver_2_id: null,
    driver_2_name: null,
    team_size: 1,
    skills: ['DELIVERY'],
    is_active: true,
  },
  {
    id: 'team-003',
    team_code: 'T-003',
    driver_1_id: 'drv-004',
    driver_1_name: 'Karl Fischer',
    driver_2_id: null,
    driver_2_name: null,
    team_size: 1,
    skills: ['DELIVERY', 'ENTSORGUNG'],
    is_active: true,
  },
];

const MOCK_ASSIGNMENTS: TeamDailyAssignment[] = [
  {
    id: 'asgn-001',
    date: '2026-01-06',
    team_id: 'team-001',
    team: MOCK_TEAMS[0],
    vehicle_id: 'veh-001',
    shift_start: '08:00',
    shift_end: '17:00',
    requires_two_person: true,
    demand_status: 'MATCHED',
  },
  {
    id: 'asgn-002',
    date: '2026-01-06',
    team_id: 'team-002',
    team: MOCK_TEAMS[1],
    vehicle_id: 'veh-002',
    shift_start: '06:00',
    shift_end: '14:00',
    requires_two_person: false,
    demand_status: 'MATCHED',
  },
  {
    id: 'asgn-003',
    date: '2026-01-06',
    team_id: 'team-003',
    team: MOCK_TEAMS[2],
    vehicle_id: 'veh-003',
    shift_start: '10:00',
    shift_end: '18:00',
    requires_two_person: true, // PROBLEM: requires 2 but team has 1
    demand_status: 'MISMATCH_UNDER',
  },
];

// =============================================================================
// HANDLERS
// =============================================================================

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const date = searchParams.get('date') || new Date().toISOString().split('T')[0];
  const { tenantCode, siteCode } = await getTenantContext();

  // In production: Call backend
  // const response = await tenantFetch<TeamDailyAssignment[]>(
  //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily?date=${date}`,
  //   { tenantCode, siteCode }
  // );

  // Mock: Filter by date
  const assignments = MOCK_ASSIGNMENTS.filter(a => a.date === date);

  // Add summary metadata
  const response = {
    date,
    assignments,
    summary: {
      total_teams: assignments.length,
      matched: assignments.filter(a => a.demand_status === 'MATCHED').length,
      mismatch_under: assignments.filter(a => a.demand_status === 'MISMATCH_UNDER').length,
      mismatch_over: assignments.filter(a => a.demand_status === 'MISMATCH_OVER').length,
      can_publish: assignments.filter(a => a.demand_status === 'MISMATCH_UNDER').length === 0,
    },
  };

  return NextResponse.json(response);
}
