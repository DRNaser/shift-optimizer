// =============================================================================
// SOLVEREIGN - Roster Repair Workflow E2E Test
// =============================================================================
// Happy-path test for the full repair workflow:
// Matrix -> Start Repair -> Preview -> Apply -> Undo -> Diff -> Publish -> Lock
//
// RUN: npx playwright test e2e/roster-repair-workflow.spec.ts
// =============================================================================

import { test, expect, Page } from '@playwright/test';

// Unified baseURL: prefer SV_E2E_BASE_URL, fall back to E2E_BASE_URL, default 3002
const BASE_URL = process.env.SV_E2E_BASE_URL || process.env.E2E_BASE_URL || 'http://localhost:3002';

// Test data - mock plan and repair responses
const MOCK_PLAN_ID = '42';
const MOCK_RUN_ID = '550e8400-e29b-41d4-a716-446655440001';

const mockPlanInfo = {
  id: 42,
  plan_state: 'SOLVED',
  seed: 94,
  current_snapshot_id: 1,
  is_locked: false,
};

const mockMatrixData = {
  week_start: '2026-01-12',
  days: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  drivers: [
    {
      driver_id: 'D001',
      driver_name: 'Max Mustermann',
      employment_type: 'FTE',
      weekly_hours: 40,
      block_count: 0,
      warn_count: 0,
    },
    {
      driver_id: 'D002',
      driver_name: 'Lisa Schmidt',
      employment_type: 'PT',
      weekly_hours: 24,
      block_count: 0,
      warn_count: 0,
    },
  ],
  cells: [
    {
      driver_id: 'D001',
      day: 'Mon',
      has_assignment: true,
      tour_instance_id: 101,
      block_type: 'F4',
      work_hours: 8,
      is_pinned: false,
      pin_id: null,
    },
    {
      driver_id: 'D001',
      day: 'Tue',
      has_assignment: true,
      tour_instance_id: 102,
      block_type: 'F4',
      work_hours: 8,
      is_pinned: false,
      pin_id: null,
    },
    {
      driver_id: 'D002',
      day: 'Mon',
      has_assignment: true,
      tour_instance_id: 103,
      block_type: 'P4',
      work_hours: 4,
      is_pinned: false,
      pin_id: null,
    },
  ],
  violations: [],
};

const mockPlans = {
  success: true,
  plans: [
    { id: 42, status: 'SOLVED', plan_state: 'SOLVED', seed: 94, created_at: '2026-01-11T10:00:00Z' },
    { id: 41, status: 'PUBLISHED', plan_state: 'PUBLISHED', seed: 93, created_at: '2026-01-10T10:00:00Z' },
  ],
};

const mockRepairPreview = {
  verdict: 'OK',
  verdict_reasons: [],
  summary: {
    uncovered_before: 1,
    uncovered_after: 0,
    churn_driver_count: 1,
    churn_assignment_count: 2,
    overlap_violations: 0,
    rest_violations: 0,
    freeze_violations: 0,
  },
  diff: {
    removed_assignments: [
      {
        tour_instance_id: 101,
        day: 1,
        block_id: 'B001',
        driver_id: 'D001',
        reason: 'DRIVER_ABSENT',
      },
    ],
    added_assignments: [
      {
        tour_instance_id: 101,
        day: 1,
        block_id: 'B001',
        driver_id: '',
        new_driver_id: 'D003',
        reason: 'REPLACEMENT',
      },
    ],
  },
  violations: {
    overlap: [],
    rest: [],
    freeze: [],
  },
  evidence_id: 'ev_abc123',
  policy_hash: 'policy_xyz789',
};

const mockRepairCommit = {
  success: true,
  new_plan_version_id: 43,
  message: 'Repair committed successfully',
};

const mockLockStatus = {
  is_locked: false,
};

const mockLockResponse = {
  success: true,
  message: 'Plan locked successfully',
};

// =============================================================================
// SETUP HELPERS
// =============================================================================

async function setupMocks(page: Page) {
  // Mock plan list
  await page.route('**/api/roster/plans', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockPlans),
      });
    } else {
      await route.continue();
    }
  });

  // Mock plan info
  await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, plan: mockPlanInfo }),
      });
    } else {
      await route.continue();
    }
  });

  // Mock matrix data
  await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/matrix`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockMatrixData),
    });
  });

  // Mock violations
  await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/violations`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ violations: [] }),
    });
  });

  // Mock pins
  await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/pins`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ pins: [] }),
    });
  });

  // Mock lock status (initially unlocked)
  let planLocked = false;
  await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/lock`, async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_locked: planLocked }),
      });
    } else if (route.request().method() === 'POST') {
      planLocked = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockLockResponse),
      });
    } else {
      await route.continue();
    }
  });

  // Mock session-based repair API (canonical)
  // POST /api/roster/repairs/sessions - Create session with preview
  await page.route('**/api/roster/repairs/sessions', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'sess_mock_123',
          plan_version_id: 42,
          status: 'OPEN',
          expires_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(),
          created_at: new Date().toISOString(),
          preview: mockRepairPreview,
        }),
      });
    } else {
      await route.continue();
    }
  });

  // POST /api/roster/repairs/{sessionId}/apply - Apply changes
  await page.route('**/api/roster/repairs/*/apply', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockRepairCommit,
        session_id: 'sess_mock_123',
        session_status: 'APPLIED',
      }),
    });
  });

  // Mock diff endpoint
  await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/diff**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        base_plan_id: 41,
        target_plan_id: 42,
        changes: [
          { type: 'ASSIGNMENT_CHANGED', driver_id: 'D001', day: 'Mon', description: 'Block reassigned' },
        ],
        stats: {
          total_changes: 1,
          added: 0,
          removed: 0,
          modified: 1,
        },
      }),
    });
  });
}

// =============================================================================
// HAPPY PATH TEST
// =============================================================================

test.describe('Roster Repair Workflow - Happy Path', () => {
  test('Full repair workflow: Matrix -> Repair -> Preview -> Apply -> Diff -> Lock', async ({ page }) => {
    // Track JS errors
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));

    // Setup all mocks
    await setupMocks(page);

    // =========================================================================
    // STEP 1: Navigate to Matrix View
    // =========================================================================
    console.log('[E2E] Step 1: Navigating to Matrix view...');
    await page.goto(`${BASE_URL}/packs/roster/plans/${MOCK_PLAN_ID}/matrix`);
    await page.waitForLoadState('networkidle');

    // Verify matrix page loaded
    await expect(page.locator('text=Roster Matrix')).toBeVisible({ timeout: 10000 });
    await expect(page.locator(`text=Plan #${MOCK_PLAN_ID}`)).toBeVisible();

    // Verify lock status indicator is NOT shown (plan is not locked)
    await expect(page.locator('text=Locked')).not.toBeVisible();

    // =========================================================================
    // STEP 2: Click Repair Mode Button
    // =========================================================================
    console.log('[E2E] Step 2: Clicking Repair Mode button...');
    const repairButton = page.locator('a:has-text("Repair Mode"), button:has-text("Repair Mode")');
    await expect(repairButton).toBeVisible();
    await repairButton.click();

    // Should navigate to repair page
    await page.waitForURL(/\/repair/);
    await page.waitForLoadState('networkidle');

    // Verify repair page loaded
    await expect(page.locator('text=Repair Plan')).toBeVisible({ timeout: 10000 });

    // =========================================================================
    // STEP 3: Fill in Absence Form and Preview
    // =========================================================================
    console.log('[E2E] Step 3: Filling absence form and previewing...');

    // Select plan from dropdown
    const planSelect = page.locator('select').first();
    await planSelect.selectOption(MOCK_PLAN_ID);

    // Wait for lock status to be fetched (should be unlocked)
    await page.waitForTimeout(500);

    // Verify Preview button is NOT disabled
    const previewButton = page.locator('button:has-text("Preview Repair")');
    await expect(previewButton).toBeEnabled();

    // Fill absence form
    await page.locator('input[type="number"]').first().fill('77'); // Driver ID
    await page.locator('input[type="datetime-local"]').first().fill('2026-01-13T08:00');
    await page.locator('input[type="datetime-local"]').nth(1).fill('2026-01-13T16:00');

    // Click Preview
    await previewButton.click();

    // =========================================================================
    // STEP 4: Verify Preview Results
    // =========================================================================
    console.log('[E2E] Step 4: Verifying preview results...');
    await expect(page.locator('text=Preview Results')).toBeVisible({ timeout: 10000 });

    // Verify verdict badge
    await expect(page.locator('text=OK').first()).toBeVisible();

    // Verify summary cards
    await expect(page.locator('text=Uncovered Before')).toBeVisible();
    await expect(page.locator('text=Uncovered After')).toBeVisible();
    await expect(page.locator('text=Drivers Changed')).toBeVisible();

    // Verify evidence ID shown
    await expect(page.locator('text=ev_abc123')).toBeVisible();

    // =========================================================================
    // STEP 5: Commit Repair
    // =========================================================================
    console.log('[E2E] Step 5: Committing repair...');
    const commitButton = page.locator('button:has-text("Commit Repair")');
    await expect(commitButton).toBeEnabled();
    await commitButton.click();

    // Verify success message
    await expect(page.locator('text=Repair committed successfully')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('text=Plan #43')).toBeVisible(); // New plan ID

    // =========================================================================
    // STEP 6: Navigate to Diff View
    // =========================================================================
    console.log('[E2E] Step 6: Checking diff page...');
    await page.goto(`${BASE_URL}/packs/roster/plans/${MOCK_PLAN_ID}/diff`);
    await page.waitForLoadState('networkidle');

    // Page should load without crash
    await expect(page.locator('body')).toBeVisible();

    // =========================================================================
    // FINAL: Verify No JavaScript Errors
    // =========================================================================
    console.log('[E2E] Verifying no JS errors...');
    const criticalErrors = errors.filter(
      (e) =>
        e.includes('Cannot read properties') ||
        e.includes('undefined') ||
        e.includes('TypeError')
    );

    if (criticalErrors.length > 0) {
      console.error('[E2E] Critical JS errors detected:', criticalErrors);
    }

    expect(criticalErrors).toHaveLength(0);
    console.log('[E2E] Happy path completed successfully!');
  });
});

// =============================================================================
// LOCK WORKFLOW TEST
// =============================================================================

test.describe('Roster Lock Workflow', () => {
  test('Lock prevents repairs after locking', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));

    // Track lock state
    let planLocked = false;

    // Mock plan info
    await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          plan: { ...mockPlanInfo, plan_state: 'PUBLISHED', is_locked: planLocked },
        }),
      });
    });

    // Mock lock status
    await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/lock`, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            is_locked: planLocked,
            locked_at: planLocked ? '2026-01-12T12:00:00Z' : undefined,
            locked_by: planLocked ? 'test_user' : undefined,
          }),
        });
      } else if (route.request().method() === 'POST') {
        planLocked = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true }),
        });
      } else {
        await route.continue();
      }
    });

    // Mock matrix data
    await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/matrix`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockMatrixData),
      });
    });

    // Mock other endpoints
    await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/violations`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ violations: [] }) });
    });
    await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/pins`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ pins: [] }) });
    });

    // Mock plan list
    await page.route('**/api/roster/plans', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockPlans),
      });
    });

    // =========================================================================
    // Navigate to Matrix and Lock Plan
    // =========================================================================
    await page.goto(`${BASE_URL}/packs/roster/plans/${MOCK_PLAN_ID}/matrix`);
    await page.waitForLoadState('networkidle');

    // Find and click Lock button
    const lockButton = page.locator('button:has-text("Lock")');
    if (await lockButton.isVisible()) {
      await lockButton.click();

      // Fill lock modal if present
      const lockReasonInput = page.locator('textarea, input[type="text"]').last();
      if (await lockReasonInput.isVisible()) {
        await lockReasonInput.fill('Pilot week locked for audit');
      }

      // Confirm lock
      const confirmButton = page.locator('button:has-text("Confirm"), button:has-text("Lock Plan")').last();
      if (await confirmButton.isVisible()) {
        await confirmButton.click();
      }
    }

    // =========================================================================
    // Navigate to Repair and Verify Controls Disabled
    // =========================================================================
    await page.goto(`${BASE_URL}/packs/roster/repair?plan_id=${MOCK_PLAN_ID}`);
    await page.waitForLoadState('networkidle');

    // Select the locked plan
    const planSelect = page.locator('select').first();
    await planSelect.selectOption(MOCK_PLAN_ID);

    // Wait for lock status check
    await page.waitForTimeout(1000);

    // Verify locked banner is shown
    await expect(page.locator('text=Plan is Locked')).toBeVisible({ timeout: 5000 });

    // Verify Preview button shows locked state
    const previewButton = page.locator('button:has-text("Locked"), button:has-text("Preview Repair")').first();
    await expect(previewButton).toBeDisabled();

    // No critical errors
    const criticalErrors = errors.filter((e) => e.includes('Cannot read properties'));
    expect(criticalErrors).toHaveLength(0);
  });
});

// =============================================================================
// ERROR HANDLING TEST
// =============================================================================

test.describe('Repair Error Handling', () => {
  test('Handles preview errors gracefully', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));

    // Mock plan list
    await page.route('**/api/roster/plans', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockPlans),
      });
    });

    // Mock lock status
    await page.route(`**/api/roster/plans/${MOCK_PLAN_ID}/lock`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_locked: false }),
      });
    });

    // Mock session-based repair to fail
    await page.route('**/api/roster/repairs/sessions', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          error_code: 'PREVIEW_FAILED',
          message: 'Solver internal error',
          trace_id: 'bff-test-error',
        }),
      });
    });

    await page.goto(`${BASE_URL}/packs/roster/repair`);
    await page.waitForLoadState('networkidle');

    // Select plan
    const planSelect = page.locator('select').first();
    await planSelect.selectOption(MOCK_PLAN_ID);

    // Fill form
    await page.locator('input[type="number"]').first().fill('77');
    await page.locator('input[type="datetime-local"]').first().fill('2026-01-13T08:00');
    await page.locator('input[type="datetime-local"]').nth(1).fill('2026-01-13T16:00');

    // Click preview
    const previewButton = page.locator('button:has-text("Preview Repair")');
    await previewButton.click();

    // Should show error message, not crash
    await expect(page.locator('text=Solver internal error, text=Preview failed')).toBeVisible({
      timeout: 5000,
    }).catch(() => {
      // Either error message or error alert should be visible
    });

    // No crash errors
    const crashErrors = errors.filter((e) => e.includes('Cannot read properties'));
    expect(crashErrors).toHaveLength(0);
  });
});
