// =============================================================================
// SOLVEREIGN E2E - Dispatcher Cockpit Tests
// =============================================================================
// Tests for the dispatcher cockpit MVP:
//   1. Happy path: list → detail → publish → lock
//   2. Denied path: kill switch blocks publish/lock
//   3. Denied path: non-Wien site blocks publish/lock
//   4. Denied path: missing approval fields blocked
//   5. Session: expired session redirects to login
//   6. RBAC: unauthorized role cannot publish/lock
//
// Run with: npx playwright test e2e/dispatcher-cockpit.spec.ts
// =============================================================================

import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000';

// =============================================================================
// TEST HELPERS
// =============================================================================

async function setupPlatformSession(page: Page, options: {
  role?: 'platform_admin' | 'dispatcher' | 'platform_viewer';
  email?: string;
} = {}) {
  const cookies = [
    {
      name: '__Host-sv_platform_session',
      value: 'mock-session-token',
      domain: 'localhost',
      path: '/',
      secure: true,
      sameSite: 'Strict' as const,
    },
    {
      name: 'sv_session',
      value: 'mock-session-value',
      domain: 'localhost',
      path: '/',
    },
    {
      name: '__Host-sv_platform_user_email',
      value: options.email || 'dispatcher@solvereign.com',
      domain: 'localhost',
      path: '/',
      secure: true,
      sameSite: 'Strict' as const,
    },
    {
      name: '__Host-sv_platform_user_role',
      value: options.role || 'dispatcher',
      domain: 'localhost',
      path: '/',
      secure: true,
      sameSite: 'Strict' as const,
    },
  ];

  await page.context().addCookies(cookies);
}

async function waitForPageLoad(page: Page) {
  await page.waitForLoadState('networkidle');
}

// =============================================================================
// HAPPY PATH TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - Happy Path', () => {
  test.beforeEach(async ({ page }) => {
    await setupPlatformSession(page, { role: 'dispatcher' });
  });

  test('should display runs list page with correct elements', async ({ page }) => {
    await page.goto(`${BASE_URL}/runs`);
    await waitForPageLoad(page);

    // Page title should be visible
    await expect(page.getByRole('heading', { name: 'Solver Runs' })).toBeVisible();

    // Site indicator should show Wien
    await expect(page.getByText('Wien Site')).toBeVisible();

    // Filter controls should be present
    await expect(page.getByRole('combobox')).toBeVisible();

    // Refresh button should be present
    await expect(page.getByRole('button', { name: 'Refresh' })).toBeVisible();
  });

  test('should filter runs by status', async ({ page }) => {
    await page.goto(`${BASE_URL}/runs`);
    await waitForPageLoad(page);

    // Open filter dropdown and select PASS
    const filterSelect = page.locator('select');
    await filterSelect.selectOption('PASS');

    // Wait for filter to apply
    await page.waitForTimeout(500);

    // URL should update with filter parameter (depending on implementation)
    // Or results should be filtered
  });

  test('should navigate to run detail page', async ({ page }) => {
    await page.goto(`${BASE_URL}/runs`);
    await waitForPageLoad(page);

    // If there are runs, click the first one
    const runCard = page.locator('[class*="cursor-pointer"]').first();
    if (await runCard.isVisible()) {
      await runCard.click();

      // Should navigate to detail page
      await expect(page).toHaveURL(/\/runs\/[a-zA-Z0-9-]+/);

      // Detail page elements should be visible
      await expect(page.getByText('Back to Runs')).toBeVisible();
    }
  });

  test('should display run detail with all sections', async ({ page }) => {
    // Navigate directly to a run detail (mock URL)
    await page.goto(`${BASE_URL}/runs/test-run-001?tenant=lts&site=wien`);
    await waitForPageLoad(page);

    // Check for key sections (if run exists)
    const backLink = page.getByText('Back to Runs');
    if (await backLink.isVisible()) {
      // KPI cards should be present
      await expect(page.getByText('Total Drivers')).toBeVisible();
      await expect(page.getByText('Coverage')).toBeVisible();

      // Audit results section should be present
      await expect(page.getByText('Audit Results')).toBeVisible();

      // Actions section should be present
      await expect(page.getByText('Actions')).toBeVisible();
    }
  });

  test('should show publish modal with approval fields', async ({ page }) => {
    await page.goto(`${BASE_URL}/runs/test-run-001?tenant=lts&site=wien`);
    await waitForPageLoad(page);

    // Click publish button if visible and enabled
    const publishButton = page.getByRole('button', { name: 'Publish Run' });
    if (await publishButton.isVisible() && await publishButton.isEnabled()) {
      await publishButton.click();

      // Modal should appear
      await expect(page.getByText('Approval Reason')).toBeVisible();

      // Confirm button should be disabled without reason
      const confirmButton = page.getByRole('button', { name: 'Publish' });
      await expect(confirmButton).toBeDisabled();

      // Enter reason
      await page.fill('textarea', 'Weekly schedule approval for Wien site');

      // Confirm button should now be enabled
      await expect(confirmButton).toBeEnabled();

      // Cancel to close modal
      await page.getByRole('button', { name: 'Cancel' }).click();
    }
  });

  test('should show repair request form', async ({ page }) => {
    await page.goto(`${BASE_URL}/runs/test-run-001?tenant=lts&site=wien`);
    await waitForPageLoad(page);

    // Click repair request button
    const repairButton = page.getByRole('button', { name: 'Request Repair' });
    if (await repairButton.isVisible()) {
      await repairButton.click();

      // Form should appear
      await expect(page.getByText('Driver ID')).toBeVisible();
      await expect(page.getByText('Driver Name')).toBeVisible();
      await expect(page.getByText('Absence Type')).toBeVisible();
      await expect(page.getByText('Affected Tours')).toBeVisible();

      // Cancel to close
      await page.getByRole('button', { name: 'Cancel' }).click();
    }
  });
});

// =============================================================================
// KILL SWITCH DENIAL TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - Kill Switch Denial', () => {
  test.beforeEach(async ({ page }) => {
    await setupPlatformSession(page, { role: 'dispatcher' });
  });

  test('should show kill switch active banner on runs list', async ({ page }) => {
    // Mock kill switch active response
    await page.route('**/api/platform/dispatcher/status**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          kill_switch_active: true,
          publish_enabled: false,
          lock_enabled: false,
          site_enabled: true,
          pending_repairs: 0,
        }),
      });
    });

    await page.goto(`${BASE_URL}/runs`);
    await waitForPageLoad(page);

    // Kill switch banner should be visible
    await expect(page.getByText('Kill Switch Active')).toBeVisible();
    await expect(page.getByText('KILL SWITCH ACTIVE')).toBeVisible();
  });

  test('should disable publish button when kill switch is active', async ({ page }) => {
    // Mock kill switch active
    await page.route('**/api/platform/dispatcher/status**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          kill_switch_active: true,
          publish_enabled: false,
          lock_enabled: false,
          site_enabled: true,
          pending_repairs: 0,
        }),
      });
    });

    // Mock run detail
    await page.route('**/api/platform/dispatcher/runs/test-run-001**', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'test-run-001',
            week_id: '2026-W02',
            status: 'PASS',
            publish_state: 'draft',
            created_at: '2026-01-08T10:00:00Z',
            solver_seed: 94,
            runtime_seconds: 120,
            can_publish: true,
            can_lock: false,
            kpis: {
              total_drivers: 145,
              fte_count: 145,
              pt_count: 0,
              coverage_pct: 100,
              total_tours: 1385,
              assigned_tours: 1385,
              unassigned_tours: 0,
              max_weekly_hours: 54,
              avg_weekly_hours: 42,
            },
            audits: [
              { name: 'Coverage', status: 'PASS', violation_count: 0 },
              { name: 'Overlap', status: 'PASS', violation_count: 0 },
              { name: 'Rest', status: 'PASS', violation_count: 0 },
              { name: 'Span Regular', status: 'PASS', violation_count: 0 },
              { name: 'Span Split', status: 'PASS', violation_count: 0 },
              { name: 'Fatigue', status: 'PASS', violation_count: 0 },
              { name: 'Reproducibility', status: 'PASS', violation_count: 0 },
            ],
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.goto(`${BASE_URL}/runs/test-run-001?tenant=lts&site=wien`);
    await waitForPageLoad(page);

    // Publish button should be disabled
    const publishButton = page.getByRole('button', { name: 'Publish Run' });
    if (await publishButton.isVisible()) {
      await expect(publishButton).toBeDisabled();
    }
  });

  test('should show blocked reason when kill switch prevents publish', async ({ page }) => {
    await page.route('**/api/platform/dispatcher/runs/test-run-001/publish**', async route => {
      await route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({
          error: 'KILL_SWITCH_ACTIVE',
          message: 'Kill switch is active. All publish operations are blocked.',
        }),
      });
    });

    // API call should return 403 with kill switch message
    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/publish?tenant=lts&site=wien`, {
      data: {
        approver_id: 'test@solvereign.com',
        approver_role: 'dispatcher',
        reason: 'Test publish',
      },
    });

    expect(response.status()).toBe(403);
    const body = await response.json();
    expect(body.error).toBe('KILL_SWITCH_ACTIVE');
  });
});

// =============================================================================
// NON-WIEN SITE DENIAL TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - Non-Wien Site Denial', () => {
  test.beforeEach(async ({ page }) => {
    await setupPlatformSession(page, { role: 'dispatcher' });
  });

  test('should show site not enabled banner for non-Wien site', async ({ page }) => {
    await page.route('**/api/platform/dispatcher/status**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          kill_switch_active: false,
          publish_enabled: false,
          lock_enabled: false,
          site_enabled: false, // Not Wien
          pending_repairs: 0,
        }),
      });
    });

    await page.goto(`${BASE_URL}/runs?tenant=lts&site=graz`);
    await waitForPageLoad(page);

    // Site not enabled banner should be visible
    await expect(page.getByText('Site Not Enabled')).toBeVisible();
  });

  test('API should return 403 for non-Wien site publish', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/publish?tenant=lts&site=graz`, {
      data: {
        approver_id: 'test@solvereign.com',
        approver_role: 'dispatcher',
        reason: 'Test publish for Graz',
      },
    });

    // Should return 403 (site not enabled) or 404 (run not found)
    expect([403, 404]).toContain(response.status());
  });
});

// =============================================================================
// APPROVAL VALIDATION TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - Approval Validation', () => {
  test.beforeEach(async ({ page }) => {
    await setupPlatformSession(page, { role: 'dispatcher' });
  });

  test('should block publish with reason less than 10 characters', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/publish?tenant=lts&site=wien`, {
      data: {
        approver_id: 'test@solvereign.com',
        approver_role: 'dispatcher',
        reason: 'Short', // Less than 10 chars
      },
    });

    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body.error).toBe('INVALID_REASON');
  });

  test('should block publish without required fields', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/publish?tenant=lts&site=wien`, {
      data: {
        // Missing approver_id, approver_role, reason
      },
    });

    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body.error).toBe('MISSING_FIELDS');
  });

  test('should block lock without required fields', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/lock?tenant=lts&site=wien`, {
      data: {
        approver_id: 'test@solvereign.com',
        // Missing approver_role, reason
      },
    });

    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body.error).toBe('MISSING_FIELDS');
  });
});

// =============================================================================
// SESSION EXPIRY TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - Session Expiry', () => {
  test('should return 401 when session is missing', async ({ page }) => {
    // No session cookies set

    const response = await page.request.get(`${BASE_URL}/api/platform/dispatcher/runs?tenant=lts&site=wien`);

    expect(response.status()).toBe(401);
    const body = await response.json();
    expect(body.error).toBe('UNAUTHORIZED');
  });

  test('should redirect to login page when session expired on page load', async ({ page }) => {
    // No session cookies - should redirect to login

    await page.goto(`${BASE_URL}/runs`);

    // Should redirect to login page
    await expect(page).toHaveURL(/\/platform\/login/);
  });
});

// =============================================================================
// RBAC TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - RBAC Enforcement', () => {
  test('platform_viewer should not see publish button', async ({ page }) => {
    await setupPlatformSession(page, { role: 'platform_viewer' });

    // Mock run detail with viewer permissions
    await page.route('**/api/platform/dispatcher/runs/test-run-001**', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'test-run-001',
            week_id: '2026-W02',
            status: 'PASS',
            publish_state: 'draft',
            created_at: '2026-01-08T10:00:00Z',
            solver_seed: 94,
            runtime_seconds: 120,
            can_publish: false, // Viewer cannot publish
            can_lock: false,
            publish_blocked_reason: 'Insufficient permissions',
            kpis: {
              total_drivers: 145,
              fte_count: 145,
              pt_count: 0,
              coverage_pct: 100,
              total_tours: 1385,
              assigned_tours: 1385,
              unassigned_tours: 0,
              max_weekly_hours: 54,
              avg_weekly_hours: 42,
            },
            audits: [],
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.route('**/api/platform/dispatcher/status**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          kill_switch_active: false,
          publish_enabled: true,
          lock_enabled: true,
          site_enabled: true,
          pending_repairs: 0,
        }),
      });
    });

    await page.goto(`${BASE_URL}/runs/test-run-001?tenant=lts&site=wien`);
    await waitForPageLoad(page);

    // Publish button should be disabled for viewer
    const publishButton = page.getByRole('button', { name: 'Publish Run' });
    if (await publishButton.isVisible()) {
      await expect(publishButton).toBeDisabled();
    }

    // Blocked reason should be shown
    await expect(page.getByText('Insufficient permissions')).toBeVisible();
  });

  test('platform_viewer API calls should be rejected', async ({ page }) => {
    await setupPlatformSession(page, { role: 'platform_viewer' });

    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/publish?tenant=lts&site=wien`, {
      data: {
        approver_id: 'viewer@solvereign.com',
        approver_role: 'platform_viewer', // Invalid role for publish
        reason: 'Attempting to publish as viewer',
      },
    });

    // Should be rejected
    expect([400, 403]).toContain(response.status());
  });
});

// =============================================================================
// REPAIR REQUEST VALIDATION TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - Repair Request Validation', () => {
  test.beforeEach(async ({ page }) => {
    await setupPlatformSession(page, { role: 'dispatcher' });
  });

  test('should reject repair request without affected tours', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/repair?tenant=lts&site=wien`, {
      data: {
        driver_id: 'D001',
        driver_name: 'Test Driver',
        absence_type: 'sick',
        affected_tours: [], // Empty array
      },
    });

    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body.error).toBe('INVALID_TOURS');
  });

  test('should reject repair request without driver info', async ({ page }) => {
    const response = await page.request.post(`${BASE_URL}/api/platform/dispatcher/runs/test-run-001/repair?tenant=lts&site=wien`, {
      data: {
        // Missing driver_id, driver_name
        absence_type: 'sick',
        affected_tours: ['T001'],
      },
    });

    expect(response.status()).toBe(400);
    const body = await response.json();
    expect(body.error).toBe('MISSING_FIELDS');
  });
});

// =============================================================================
// EVIDENCE DOWNLOAD TESTS
// =============================================================================

test.describe('Dispatcher Cockpit - Evidence Download', () => {
  test.beforeEach(async ({ page }) => {
    await setupPlatformSession(page, { role: 'dispatcher' });
  });

  test('should display evidence hash when available', async ({ page }) => {
    await page.route('**/api/platform/dispatcher/runs/test-run-001**', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'test-run-001',
            week_id: '2026-W02',
            status: 'PASS',
            publish_state: 'locked',
            created_at: '2026-01-08T10:00:00Z',
            solver_seed: 94,
            runtime_seconds: 120,
            evidence_hash: 'sha256:abc123def456...',
            can_publish: false,
            can_lock: false,
            kpis: {
              total_drivers: 145,
              fte_count: 145,
              pt_count: 0,
              coverage_pct: 100,
              total_tours: 1385,
              assigned_tours: 1385,
              unassigned_tours: 0,
              max_weekly_hours: 54,
              avg_weekly_hours: 42,
            },
            audits: [],
          }),
        });
      } else {
        await route.continue();
      }
    });

    await page.route('**/api/platform/dispatcher/status**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          kill_switch_active: false,
          publish_enabled: true,
          lock_enabled: true,
          site_enabled: true,
          pending_repairs: 0,
        }),
      });
    });

    await page.goto(`${BASE_URL}/runs/test-run-001?tenant=lts&site=wien`);
    await waitForPageLoad(page);

    // Evidence hash should be visible
    await expect(page.getByText('Evidence Hash')).toBeVisible();
    await expect(page.getByText('sha256:abc123def456...')).toBeVisible();

    // Download button should be present
    await expect(page.getByRole('button', { name: 'Download Evidence' })).toBeVisible();
  });
});
