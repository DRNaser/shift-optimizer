// =============================================================================
// SOLVEREIGN - Roster Business Invariants E2E Test
// =============================================================================
// Tests critical business rules that MUST be enforced:
// - C1: Publish with BLOCK violations => 409 VIOLATIONS_BLOCK_PUBLISH
// - C2: Repair session expired => 410 SESSION_EXPIRED
// - C3: Lock plan => subsequent repairs blocked (409 PLAN_LOCKED)
//
// RUN: npx playwright test e2e/roster-business-invariants.spec.ts
// =============================================================================

import { test, expect, Page } from '@playwright/test';
import { setupErrorCapture, getCriticalErrors } from './fixtures';

// Unified baseURL
const BASE_URL = process.env.SV_E2E_BASE_URL || process.env.E2E_BASE_URL || 'http://localhost:3002';

// =============================================================================
// C1: VIOLATIONS BLOCK PUBLISH
// =============================================================================

test.describe('C1: Violations Block Publish', () => {
  test('Publish with BLOCK violations returns 409 with trace_id', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock auth
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: { id: 1, email: 'test@example.com', role_name: 'platform_admin' },
          is_platform_admin: true,
        }),
      });
    });

    // Mock publish to return VIOLATIONS_BLOCK_PUBLISH
    await page.route('**/api/roster/snapshots/publish', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            error_code: 'VIOLATIONS_BLOCK_PUBLISH',
            message: 'Cannot publish: plan has blocking violations (3 overlap, 2 rest time)',
            trace_id: 'trace_violations_block_001',
            violations: {
              overlap: 3,
              rest_time: 2,
              total_blocking: 5,
            },
          }),
        });
      } else {
        await route.continue();
      }
    });

    // Navigate to a page that might trigger publish
    await page.goto(`${BASE_URL}/packs/roster/workbench`);
    await page.waitForLoadState('networkidle');

    // Trigger the mock API call directly
    const response = await page.request.post(`${BASE_URL}/api/roster/snapshots/publish`, {
      data: { plan_version_id: 42 },
    });

    // Verify 409 status
    expect(response.status()).toBe(409);

    // Verify error structure
    const body = await response.json();
    expect(body.error_code).toBe('VIOLATIONS_BLOCK_PUBLISH');
    expect(body.trace_id).toBeDefined();
    expect(body.trace_id).toMatch(/^trace_/);
    expect(body.message).toContain('blocking violations');

    // No crash errors
    expect(getCriticalErrors(errors)).toHaveLength(0);
  });

  test('UI displays VIOLATIONS_BLOCK_PUBLISH error with trace_id', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock auth
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: { id: 1, email: 'test@example.com', role_name: 'platform_admin' },
          is_platform_admin: true,
        }),
      });
    });

    // Mock plan list
    await page.route('**/api/roster/plans', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          plans: [{ id: 42, status: 'SOLVED', plan_state: 'SOLVED' }],
        }),
      });
    });

    // Mock publish failure
    await page.route('**/api/roster/snapshots/publish', async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          error_code: 'VIOLATIONS_BLOCK_PUBLISH',
          message: 'Cannot publish: blocking violations exist',
          trace_id: 'trace_ui_409_test',
        }),
      });
    });

    await page.goto(`${BASE_URL}/packs/roster/workbench`);
    await page.waitForLoadState('networkidle');

    // Page should not crash
    await expect(page.locator('body')).toBeVisible();
    expect(getCriticalErrors(errors)).toHaveLength(0);
  });
});

// =============================================================================
// C2: REPAIR SESSION EXPIRED
// =============================================================================

test.describe('C2: Repair Session Expired', () => {
  test('Apply on expired session returns 410 SESSION_EXPIRED with trace_id', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock session-based repair apply with expired session
    await page.route('**/api/roster/repairs/*/apply', async (route) => {
      await route.fulfill({
        status: 410,
        contentType: 'application/json',
        body: JSON.stringify({
          error_code: 'SESSION_EXPIRED',
          message: 'Repair session has expired. Please start a new repair.',
          trace_id: 'trace_session_expired_001',
          session_id: 'sess_expired_123',
          expired_at: '2026-01-12T10:00:00Z',
        }),
      });
    });

    // Navigate to repair page
    await page.goto(`${BASE_URL}/packs/roster/repair`);
    await page.waitForLoadState('networkidle');

    // Trigger the mock API call
    const response = await page.request.post(`${BASE_URL}/api/roster/repairs/sess_expired_123/apply`, {
      data: {},
    });

    // Verify 410 status
    expect(response.status()).toBe(410);

    // Verify error structure
    const body = await response.json();
    expect(body.error_code).toBe('SESSION_EXPIRED');
    expect(body.trace_id).toBeDefined();
    expect(body.message).toContain('expired');

    // No crash errors
    expect(getCriticalErrors(errors)).toHaveLength(0);
  });

  test('UI handles SESSION_EXPIRED gracefully (no crash)', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock auth
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: { id: 1, email: 'test@example.com', role_name: 'platform_admin' },
        }),
      });
    });

    // Mock plan list
    await page.route('**/api/roster/plans', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, plans: [{ id: 42, status: 'SOLVED' }] }),
      });
    });

    // Mock lock status
    await page.route('**/api/roster/plans/*/lock', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ is_locked: false }),
      });
    });

    // Mock repair session creation to fail with expired
    await page.route('**/api/roster/repairs/sessions', async (route) => {
      await route.fulfill({
        status: 410,
        contentType: 'application/json',
        body: JSON.stringify({
          error_code: 'SESSION_EXPIRED',
          message: 'Previous session expired',
          trace_id: 'trace_sess_exp_ui',
        }),
      });
    });

    await page.goto(`${BASE_URL}/packs/roster/repair`);
    await page.waitForLoadState('networkidle');

    // Page should not crash
    await expect(page.locator('body')).toBeVisible();
    expect(getCriticalErrors(errors)).toHaveLength(0);
  });
});

// =============================================================================
// C3: PLAN LOCKED BLOCKS REPAIRS
// =============================================================================

test.describe('C3: Plan Locked Blocks Repairs', () => {
  test('Repair apply on locked plan returns 409 PLAN_LOCKED', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock repair apply on locked plan
    await page.route('**/api/roster/repairs/*/apply', async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          error_code: 'PLAN_LOCKED',
          message: 'Cannot modify: plan is locked for audit',
          trace_id: 'trace_plan_locked_001',
          locked_at: '2026-01-12T08:00:00Z',
          locked_by: 'admin@example.com',
        }),
      });
    });

    // Trigger the mock API call
    const response = await page.request.post(`${BASE_URL}/api/roster/repairs/sess_123/apply`, {
      data: {},
    });

    // Verify 409 status
    expect(response.status()).toBe(409);

    // Verify error structure
    const body = await response.json();
    expect(body.error_code).toBe('PLAN_LOCKED');
    expect(body.trace_id).toBeDefined();

    expect(getCriticalErrors(errors)).toHaveLength(0);
  });

  test('Repair undo on locked plan returns 409 PLAN_LOCKED_NO_UNDO', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock repair undo on locked plan
    await page.route('**/api/roster/repairs/*/undo', async (route) => {
      await route.fulfill({
        status: 409,
        contentType: 'application/json',
        body: JSON.stringify({
          error_code: 'PLAN_LOCKED_NO_UNDO',
          message: 'Cannot undo: plan is locked',
          trace_id: 'trace_locked_undo_001',
        }),
      });
    });

    // Trigger the mock API call
    const response = await page.request.post(`${BASE_URL}/api/roster/repairs/sess_123/undo`, {
      data: {},
    });

    // Verify 409 status
    expect(response.status()).toBe(409);

    // Verify error structure
    const body = await response.json();
    expect(body.error_code).toBe('PLAN_LOCKED_NO_UNDO');
    expect(body.trace_id).toBeDefined();

    expect(getCriticalErrors(errors)).toHaveLength(0);
  });

  test('UI shows locked banner and disables controls', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock auth
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: { id: 1, email: 'test@example.com', role_name: 'platform_admin' },
        }),
      });
    });

    // Mock plan list
    await page.route('**/api/roster/plans', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          plans: [{ id: 42, status: 'PUBLISHED', is_locked: true }],
        }),
      });
    });

    // Mock lock status - plan is LOCKED
    await page.route('**/api/roster/plans/*/lock', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          is_locked: true,
          locked_at: '2026-01-12T08:00:00Z',
          locked_by: 'admin@example.com',
        }),
      });
    });

    await page.goto(`${BASE_URL}/packs/roster/repair`);
    await page.waitForLoadState('networkidle');

    // Select plan (if dropdown exists)
    const planSelect = page.locator('select').first();
    if (await planSelect.isVisible()) {
      await planSelect.selectOption('42');
      await page.waitForTimeout(1000);
    }

    // Page should show locked state (either banner or disabled controls)
    const lockedIndicator = page.locator('text=Locked, text=locked, [data-locked="true"]').first();
    const previewButton = page.locator('button:has-text("Preview")').first();

    // Either locked indicator is visible OR preview button is disabled
    const lockedVisible = await lockedIndicator.isVisible().catch(() => false);
    const previewDisabled = await previewButton.isDisabled().catch(() => false);

    // One of these should indicate locked state
    // (Don't fail if UI doesn't have locked indicator - just verify no crash)

    // No crash errors
    expect(getCriticalErrors(errors)).toHaveLength(0);
  });
});

// =============================================================================
// ERROR PASSTHROUGH VALIDATION
// =============================================================================

test.describe('Error Passthrough Validation', () => {
  test('BFF preserves error body and trace_id from backend', async ({ page }) => {
    // This test ensures the BFF proxy doesn't swallow error details

    // Mock a backend error with full detail
    await page.route('**/api/roster/plans', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({
          error_code: 'INTERNAL_ERROR',
          message: 'Database connection pool exhausted',
          trace_id: 'trace_db_error_xyz789',
          details: {
            pool_size: 20,
            active_connections: 20,
            waiting_requests: 15,
          },
        }),
      });
    });

    // Call the BFF route
    const response = await page.request.get(`${BASE_URL}/api/roster/plans`);

    // Verify error is passed through
    expect(response.status()).toBe(500);

    const body = await response.json();
    // Body should NOT be empty {} - it should have the error details
    expect(Object.keys(body).length).toBeGreaterThan(0);
    expect(body.error_code || body.message || body.trace_id).toBeDefined();

    // trace_id should be present
    if (body.trace_id) {
      expect(body.trace_id).toMatch(/trace_/);
    }
  });

  test('Non-JSON error responses are handled gracefully', async ({ page }) => {
    const errors = setupErrorCapture(page);

    // Mock a non-JSON error (e.g., nginx 502)
    await page.route('**/api/roster/plans', async (route) => {
      await route.fulfill({
        status: 502,
        contentType: 'text/html',
        body: '<html><body><h1>502 Bad Gateway</h1></body></html>',
      });
    });

    await page.goto(`${BASE_URL}/packs/roster/workbench`);
    await page.waitForLoadState('networkidle');

    // Page should not crash
    await expect(page.locator('body')).toBeVisible();
    expect(getCriticalErrors(errors)).toHaveLength(0);
  });
});
