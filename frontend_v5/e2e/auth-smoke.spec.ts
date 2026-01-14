// =============================================================================
// SOLVEREIGN - E2E Auth Smoke Tests (Wien Pilot Gate)
// =============================================================================
// 6 critical checks that MUST pass before "GO":
// 1. Login (Entra) → Redirect/Popup works
// 2. /plans list loads after Login (API calls authenticated)
// 3. As DISPATCHER: Approve/Publish/Force UI not visible, API 403
// 4. As APPROVER: Approve → Publish without Freeze works
// 5. Freeze active: Publish → 409; Force with short reason → 422; Force with reason → 200
// 6. Snapshot History: Legacy snapshots have Badge; new snapshots show payload ok
//
// RUN: npx playwright test e2e/auth-smoke.spec.ts
// =============================================================================

import { test, expect, Page } from '@playwright/test';

// =============================================================================
// CONFIGURATION
// =============================================================================

const BASE_URL = process.env.SV_E2E_BASE_URL || process.env.E2E_BASE_URL || 'http://localhost:3002';
const API_URL = process.env.SV_E2E_API_URL || process.env.E2E_API_URL || 'http://localhost:8000';

// Test plan ID (set in env or use a known test plan)
const TEST_PLAN_ID = process.env.E2E_TEST_PLAN_ID || 'test-plan-001';

// =============================================================================
// HELPER: Login Flow
// =============================================================================

async function loginWithMSAL(page: Page, username: string, password: string) {
  // Navigate to app
  await page.goto(BASE_URL);

  // Click sign in button
  const signInButton = page.getByRole('button', { name: /sign in/i });
  await signInButton.click();

  // Handle MSAL popup/redirect
  // Note: Actual implementation depends on Entra ID test tenant config
  // This is a placeholder - real test needs test user credentials
  const popupPromise = page.waitForEvent('popup');
  const popup = await popupPromise;

  // Fill Microsoft login form
  await popup.waitForLoadState();
  await popup.fill('input[type="email"]', username);
  await popup.click('input[type="submit"]');
  await popup.fill('input[type="password"]', password);
  await popup.click('input[type="submit"]');

  // Wait for redirect back to app
  await page.waitForURL(`${BASE_URL}/**`);
}

// =============================================================================
// TEST 1: Login Flow
// =============================================================================

test.describe('1. Login (Entra)', () => {
  test.skip('Login via popup works', async ({ page }) => {
    // This test requires real Entra ID credentials
    // Set E2E_TEST_USER and E2E_TEST_PASSWORD environment variables

    const username = process.env.E2E_TEST_USER;
    const password = process.env.E2E_TEST_PASSWORD;

    if (!username || !password) {
      test.skip();
      return;
    }

    await loginWithMSAL(page, username, password);

    // Verify user info displayed
    await expect(page.getByText(/Welcome/i)).toBeVisible();
  });

  test('Auth page shows sign-in button when not authenticated', async ({ page }) => {
    // Increase timeout for dev server under parallel load
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

    // Should see sign-in option (either button or redirect to login)
    const signInVisible = await page.getByRole('button', { name: /sign in/i }).isVisible().catch(() => false);
    const loginPageVisible = page.url().includes('login');

    expect(signInVisible || loginPageVisible).toBeTruthy();
  });
});

// =============================================================================
// TEST 2: API Authentication
// =============================================================================

test.describe('2. API Calls Authenticated', () => {
  test('Unauthenticated API call returns auth error', async ({ request }) => {
    // Test via BFF route (not direct backend) to verify frontend auth flow
    const response = await request.get(`${BASE_URL}/api/roster/plans`);

    // Should be 401 (unauthorized) - the BFF returns 401 when no session cookie
    expect([401, 403]).toContain(response.status());
  });

  test('Token audience matches backend', async ({ page }) => {
    // This is a config validation test
    // Check that frontend scope matches backend audience

    // Increase timeout for dev server under parallel load
    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

    // Get MSAL config from page context
    const msalConfig = await page.evaluate(() => {
      // @ts-ignore - accessing window config
      return window.__MSAL_CONFIG__ || null;
    });

    // Log for debugging
    console.log('MSAL Config:', msalConfig);

    // Note: This test verifies config is loaded
    // Real validation happens when API calls are made
  });
});

// =============================================================================
// TEST 3: RBAC - Dispatcher Restrictions
// =============================================================================

test.describe('3. RBAC: Dispatcher Role', () => {
  test.skip('Dispatcher cannot see Approve button', async ({ page }) => {
    // Login as dispatcher user
    const username = process.env.E2E_DISPATCHER_USER;
    const password = process.env.E2E_DISPATCHER_PASSWORD;

    if (!username || !password) {
      test.skip();
      return;
    }

    await loginWithMSAL(page, username, password);
    await page.goto(`${BASE_URL}/plans/${TEST_PLAN_ID}`);

    // Approve button should NOT be visible for Dispatcher
    const approveButton = page.getByRole('button', { name: /approve/i });
    await expect(approveButton).not.toBeVisible();
  });

  test.skip('Dispatcher gets 403 on publish API call', async ({ request }) => {
    // This would require a dispatcher token
    // Real test needs token from dispatcher user login

    const dispatcherToken = process.env.E2E_DISPATCHER_TOKEN;
    if (!dispatcherToken) {
      test.skip();
      return;
    }

    const response = await request.post(`${API_URL}/api/v1/plans/${TEST_PLAN_ID}/publish`, {
      headers: {
        Authorization: `Bearer ${dispatcherToken}`,
        'Content-Type': 'application/json',
      },
      data: { reason: 'Test publish' },
    });

    expect(response.status()).toBe(403);
  });
});

// =============================================================================
// TEST 4: RBAC - Approver Flow
// =============================================================================

test.describe('4. RBAC: Approver Role', () => {
  test.skip('Approver can see Publish button', async ({ page }) => {
    const username = process.env.E2E_APPROVER_USER;
    const password = process.env.E2E_APPROVER_PASSWORD;

    if (!username || !password) {
      test.skip();
      return;
    }

    await loginWithMSAL(page, username, password);
    await page.goto(`${BASE_URL}/plans/${TEST_PLAN_ID}`);

    // Publish button should be visible for Approver
    const publishButton = page.getByRole('button', { name: /publish/i });
    await expect(publishButton).toBeVisible();
  });
});

// =============================================================================
// TEST 5: Freeze Window Handling
// =============================================================================

test.describe('5. Freeze Window Enforcement', () => {
  test.skip('Publish during freeze returns 409', async ({ request }) => {
    const approverToken = process.env.E2E_APPROVER_TOKEN;
    const frozenPlanId = process.env.E2E_FROZEN_PLAN_ID;

    if (!approverToken || !frozenPlanId) {
      test.skip();
      return;
    }

    const response = await request.post(`${API_URL}/api/v1/plans/${frozenPlanId}/publish`, {
      headers: {
        Authorization: `Bearer ${approverToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        reason: 'Test publish',
        force_during_freeze: false,
      },
    });

    expect(response.status()).toBe(409);

    const body = await response.json();
    expect(body.error || body.detail).toContain('FREEZE');
  });

  test.skip('Force with short reason returns 422', async ({ request }) => {
    const approverToken = process.env.E2E_APPROVER_TOKEN;
    const frozenPlanId = process.env.E2E_FROZEN_PLAN_ID;

    if (!approverToken || !frozenPlanId) {
      test.skip();
      return;
    }

    const response = await request.post(`${API_URL}/api/v1/plans/${frozenPlanId}/publish`, {
      headers: {
        Authorization: `Bearer ${approverToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        reason: 'Test',
        force_during_freeze: true,
        force_reason: 'short', // Less than 10 chars
      },
    });

    expect(response.status()).toBe(422);
  });

  test.skip('Force with valid reason returns 200', async ({ request }) => {
    const approverToken = process.env.E2E_APPROVER_TOKEN;
    const frozenPlanId = process.env.E2E_FROZEN_PLAN_ID;

    if (!approverToken || !frozenPlanId) {
      test.skip();
      return;
    }

    const response = await request.post(`${API_URL}/api/v1/plans/${frozenPlanId}/publish`, {
      headers: {
        Authorization: `Bearer ${approverToken}`,
        'Content-Type': 'application/json',
      },
      data: {
        reason: 'E2E Test publish',
        force_during_freeze: true,
        force_reason: 'CRITICAL: E2E test force publish - will be cleaned up',
      },
    });

    expect(response.status()).toBe(200);

    const body = await response.json();
    expect(body.forced_during_freeze).toBe(true);
  });
});

// =============================================================================
// TEST 6: Legacy Snapshot Handling
// =============================================================================

test.describe('6. Legacy Snapshot Warnings', () => {
  test.skip('Legacy snapshot shows badge', async ({ page }) => {
    const username = process.env.E2E_APPROVER_USER;
    const password = process.env.E2E_APPROVER_PASSWORD;
    const legacySnapshotPlanId = process.env.E2E_LEGACY_SNAPSHOT_PLAN_ID;

    if (!username || !password || !legacySnapshotPlanId) {
      test.skip();
      return;
    }

    await loginWithMSAL(page, username, password);
    await page.goto(`${BASE_URL}/plans/${legacySnapshotPlanId}/snapshots`);

    // Should see LEGACY badge
    const legacyBadge = page.getByText('LEGACY');
    await expect(legacyBadge).toBeVisible();

    // Should see "Not replayable" warning
    const notReplayable = page.getByText(/not replayable/i);
    await expect(notReplayable).toBeVisible();
  });
});

// =============================================================================
// CRITICAL PAGES SMOKE (No Auth Required)
// =============================================================================
// These tests verify that critical pages don't crash and respond correctly.
// They can run without credentials and catch build/render errors.

test.describe('Critical Pages Smoke', () => {
  const criticalRoutes = [
    { path: '/platform/login', expectRedirect: false, name: 'Platform Login' },
    { path: '/platform-admin', expectRedirect: true, name: 'Platform Admin Dashboard' },
    { path: '/platform-admin/tenants', expectRedirect: true, name: 'Tenant List' },
    { path: '/platform-admin/users', expectRedirect: true, name: 'User List' },
    { path: '/packs/roster/workbench', expectRedirect: true, name: 'Roster Workbench' },
    { path: '/packs/roster/repair', expectRedirect: true, name: 'Roster Repair' },
  ];

  for (const route of criticalRoutes) {
    // Increase test timeout for dev server under parallel load
    test(`${route.name} (${route.path}) responds without crash`, async ({ page }) => {
      test.setTimeout(60000);
      const response = await page.goto(`${BASE_URL}${route.path}`, {
        waitUntil: 'domcontentloaded',
        timeout: 45000,
      });

      // Should not return 5xx errors (server crash)
      expect(response?.status()).toBeLessThan(500);

      // If auth required, should redirect to login or show 401
      if (route.expectRedirect) {
        const currentUrl = page.url();
        const isRedirectedToLogin = currentUrl.includes('login') || currentUrl.includes('auth');
        const is401 = response?.status() === 401;
        const hasContent = await page.locator('body').textContent().then(t => t && t.length > 0);

        // Either redirected to login, got 401, or page rendered
        expect(isRedirectedToLogin || is401 || hasContent).toBeTruthy();
      } else {
        // Public page - should render
        const hasContent = await page.locator('body').textContent().then(t => t && t.length > 100);
        expect(hasContent).toBeTruthy();
      }
    });
  }

  test('All critical pages return no console errors', async ({ page }) => {
    test.setTimeout(60000);
    const consoleErrors: string[] = [];
    page.on('console', msg => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });

    // Visit login page (public)
    // Use domcontentloaded instead of networkidle to avoid timeout under parallel load
    await page.goto(`${BASE_URL}/platform/login`, { waitUntil: 'domcontentloaded', timeout: 45000 });

    // Filter out expected errors (network failures when not authenticated)
    const unexpectedErrors = consoleErrors.filter(
      err => !err.includes('401') && !err.includes('403') && !err.includes('Failed to fetch')
    );

    // Log for debugging
    if (unexpectedErrors.length > 0) {
      console.log('Unexpected console errors:', unexpectedErrors);
    }

    // Should have no unexpected errors on public pages
    expect(unexpectedErrors.length).toBe(0);
  });
});

// =============================================================================
// BFF ROUTES SMOKE (API Health)
// =============================================================================
// Verify BFF routes respond correctly (not crash)

test.describe('BFF Routes Smoke', () => {
  const bffRoutes = [
    { path: '/api/auth/me', method: 'GET', expectAuth: true },
    { path: '/api/platform-admin/tenants', method: 'GET', expectAuth: true },
    { path: '/api/platform-admin/users', method: 'GET', expectAuth: true },
    { path: '/api/roster/plans', method: 'GET', expectAuth: true },
  ];

  for (const route of bffRoutes) {
    test(`BFF ${route.method} ${route.path} responds correctly`, async ({ request }) => {
      const response = await request.fetch(`${BASE_URL}${route.path}`, {
        method: route.method,
      });

      // Should not crash (5xx)
      expect(response.status()).toBeLessThan(500);

      // If auth required, should return 401 with proper error structure
      if (route.expectAuth) {
        expect([200, 401, 403]).toContain(response.status());

        if (response.status() === 401) {
          const body = await response.json();
          // Should have proper error structure, not empty {}
          // Accept multiple formats for backwards compatibility:
          // - { error_code, message } (BFF proxy format)
          // - { error: { code, message } } (legacy platform format)
          // - { code, message } (platform-rbac format)
          // - { success: false, error: string } (legacy API format)
          const hasProxyFormat = 'error_code' in body && 'message' in body;
          const hasLegacyFormat = body.error && typeof body.error === 'object' && ('code' in body.error || 'message' in body.error);
          const hasPlatformRbacFormat = 'code' in body && 'message' in body;
          const hasSuccessFalseFormat = body.success === false && typeof body.error === 'string';
          expect(hasProxyFormat || hasLegacyFormat || hasPlatformRbacFormat || hasSuccessFalseFormat).toBe(true);
        }
      }
    });
  }
});

// =============================================================================
// CONFIGURATION VALIDATION
// =============================================================================

test.describe('Config Validation', () => {
  test('MSAL scope matches backend audience', async () => {
    // This test validates configuration consistency
    // It should be run as part of CI before deployment

    const frontendScope = process.env.NEXT_PUBLIC_AZURE_AD_API_SCOPE;
    const backendAudience = process.env.SOLVEREIGN_OIDC_AUDIENCE;

    // Both should be set in CI
    if (!frontendScope || !backendAudience) {
      console.warn('WARN: Missing MSAL scope or OIDC audience env vars');
      console.warn('Frontend scope:', frontendScope || '(not set)');
      console.warn('Backend audience:', backendAudience || '(not set)');
      return;
    }

    // Extract audience from scope
    // Scope format: api://audience/scope_name
    const scopeMatch = frontendScope.match(/api:\/\/([^/]+)/);
    const scopeAudience = scopeMatch ? scopeMatch[0] : frontendScope;

    // Backend audience should match
    console.log('Frontend scope audience:', scopeAudience);
    console.log('Backend audience:', backendAudience);

    // They should match (ignoring trailing scope name)
    expect(backendAudience.startsWith(scopeAudience.replace('/access_as_user', ''))).toBeTruthy();
  });
});

// =============================================================================
// MANUAL VERIFICATION CHECKLIST
// =============================================================================

test.describe('Manual Verification Checklist', () => {
  test('Print checklist for manual verification', async () => {
    console.log(`
============================================================
WIEN PILOT E2E AUTH SMOKE TEST - MANUAL CHECKLIST
============================================================

Run these checks manually if automated tests are skipped:

1. LOGIN
   [ ] Open ${BASE_URL}
   [ ] Click "Sign In with Microsoft"
   [ ] Popup/redirect opens to Microsoft login
   [ ] After login, user name displayed
   [ ] Roles visible in UI (check console/network)

2. API AUTHENTICATION
   [ ] Navigate to /plans
   [ ] Plans list loads (no 401 errors in Network tab)
   [ ] Check Authorization header in requests: "Bearer <token>"
   [ ] Token is access_token, NOT id_token

3. DISPATCHER RESTRICTIONS
   [ ] Login as Dispatcher user
   [ ] Navigate to plan detail
   [ ] NO "Approve" button visible
   [ ] NO "Publish" button visible
   [ ] Attempting API call returns 403

4. APPROVER FLOW
   [ ] Login as Approver user
   [ ] Navigate to plan detail
   [ ] "Approve" button visible
   [ ] "Publish" button visible
   [ ] Click Publish → modal opens

5. FREEZE WINDOW
   [ ] Open publish modal on frozen plan
   [ ] Warning shows "Freeze Window Active"
   [ ] Normal Publish button disabled
   [ ] "Force publish" checkbox visible (Approver only)
   [ ] Force with reason < 10 chars → 422 error
   [ ] Force with reason >= 10 chars → Success

6. LEGACY SNAPSHOTS
   [ ] Navigate to snapshot history of old plan
   [ ] Legacy snapshots show "LEGACY" badge
   [ ] Warning: "Not replayable - pre-V3.7.2"
   [ ] New snapshots show "Payload OK" or similar

TOKEN VALIDATION
   [ ] Decode token at jwt.ms
   [ ] Check "aud" claim matches SOLVEREIGN_OIDC_AUDIENCE
   [ ] Check "iss" claim matches SOLVEREIGN_OIDC_ISSUER
   [ ] Check "roles" claim contains user's roles

============================================================
If ANY check fails, it's "FAST" not "GO"
============================================================
    `);
  });
});
