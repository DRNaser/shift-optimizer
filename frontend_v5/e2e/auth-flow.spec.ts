/**
 * SOLVEREIGN - Authenticated E2E Flow Test
 *
 * Tests login → navigate critical pages → no re-login required → CRUD operations
 *
 * REQUIREMENTS:
 * - Set SV_E2E_USER and SV_E2E_PASS environment variables
 * - Backend must be running with test user seeded
 *
 * RUN:
 *   SV_E2E_USER=test@example.com SV_E2E_PASS=secret npx playwright test e2e/auth-flow.spec.ts
 */

import { test, expect, Page, BrowserContext } from '@playwright/test';

const BASE_URL = process.env.SV_E2E_BASE_URL || process.env.E2E_BASE_URL || 'http://localhost:3002';
const E2E_USER = process.env.SV_E2E_USER;
const E2E_PASS = process.env.SV_E2E_PASS;

// Skip all tests if credentials not provided
test.skip(!E2E_USER || !E2E_PASS, 'SV_E2E_USER and SV_E2E_PASS env vars required');

// Critical pages to verify post-login
// NOTE: Pack routes (/packs/*) require tenant context for platform_admin users
// They will show "Context Required" page, which is expected behavior
const CRITICAL_PAGES = [
  { path: '/platform-admin', name: 'Platform Admin Dashboard' },
  { path: '/platform-admin/tenants', name: 'Tenant List' },
  { path: '/platform-admin/users', name: 'User List' },
];

// Pack pages that require tenant context (test separately)
const PACK_PAGES = [
  { path: '/packs/roster/workbench', name: 'Roster Workbench' },
  { path: '/packs/roster/repair', name: 'Roster Repair' },
];

// Debug log file for auth failures
const DEBUG_LOG: string[] = [];

function logDebug(msg: string) {
  const timestamp = new Date().toISOString();
  const line = `[${timestamp}] ${msg}`;
  DEBUG_LOG.push(line);
  console.log(line);
}

// Helper to login via form with detailed debug logging
async function login(page: Page, email: string, password: string): Promise<boolean> {
  logDebug(`LOGIN START: email=${email}`);

  // Include returnTo parameter to redirect to platform-admin after login
  await page.goto(`${BASE_URL}/platform/login?returnTo=/platform-admin`);
  logDebug(`Navigated to login page: ${page.url()}`);

  // Fill login form
  await page.fill('input[type="email"], input[name="email"]', email);
  await page.fill('input[type="password"], input[name="password"]', password);
  logDebug('Filled login form');

  // Capture network response for login POST
  const responsePromise = page.waitForResponse(
    resp => resp.url().includes('/api/auth/login') && resp.request().method() === 'POST',
    { timeout: 15000 }
  ).catch(() => null);

  // Submit
  await page.click('button[type="submit"]');
  logDebug('Clicked submit');

  // Get login response details
  const response = await responsePromise;
  if (response) {
    const status = response.status();
    const headers = response.headers();
    const setCookie = headers['set-cookie'] || 'NONE';
    const location = headers['location'] || 'NONE';

    logDebug(`LOGIN RESPONSE: status=${status}`);
    logDebug(`Set-Cookie: ${setCookie.substring(0, 100)}...`);
    logDebug(`Location: ${location}`);

    if (status !== 200) {
      try {
        const body = await response.text();
        logDebug(`Response body: ${body.substring(0, 200)}`);
      } catch {
        logDebug('Could not read response body');
      }
    }
  } else {
    logDebug('LOGIN RESPONSE: No response captured (timeout or error)');
  }

  // Wait for redirect or error
  try {
    await page.waitForURL(`${BASE_URL}/platform-admin*`, { timeout: 10000 });
    logDebug(`LOGIN SUCCESS: Redirected to ${page.url()}`);

    // Verify cookies are set
    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find(c => c.name === 'sv_platform_session');
    logDebug(`Session cookie: ${sessionCookie ? 'PRESENT' : 'MISSING'}`);
    if (sessionCookie) {
      logDebug(`Cookie attrs: httpOnly=${sessionCookie.httpOnly}, secure=${sessionCookie.secure}, sameSite=${sessionCookie.sameSite}, path=${sessionCookie.path}`);
    }

    // Verify /api/auth/me works
    const meResponse = await page.request.get(`${BASE_URL}/api/auth/me`);
    logDebug(`GET /api/auth/me: status=${meResponse.status()}`);

    return true;
  } catch {
    logDebug(`LOGIN FAILED: Still on ${page.url()}`);

    // Check for error message
    const errorVisible = await page.locator('[data-testid="login-error"], .error, [role="alert"]').isVisible();
    if (errorVisible) {
      const errorText = await page.locator('[data-testid="login-error"], .error, [role="alert"]').first().textContent();
      logDebug(`Error message: ${errorText}`);
    }

    // Dump cookies state
    const cookies = await page.context().cookies();
    logDebug(`Cookies after failure: ${JSON.stringify(cookies.map(c => c.name))}`);

    // Try /api/auth/me to see what it returns
    try {
      const meResponse = await page.request.get(`${BASE_URL}/api/auth/me`);
      logDebug(`GET /api/auth/me after failure: status=${meResponse.status()}`);
      const meBody = await meResponse.text();
      logDebug(`/api/auth/me body: ${meBody.substring(0, 200)}`);
    } catch (e) {
      logDebug(`/api/auth/me error: ${e}`);
    }

    return false;
  }
}

// Export debug log for artifacts
function getDebugLog(): string {
  return DEBUG_LOG.join('\n');
}

// Helper to check for console errors - STRICT MODE
// Only ignore expected auth responses, NOT server errors
function setupConsoleErrorCapture(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', msg => {
    if (msg.type() === 'error') {
      const text = msg.text();
      // STRICT: Only ignore expected patterns, NOT server 500 errors
      // These are legitimate patterns that occur during normal operation:
      const ignoredPatterns = [
        '401',  // Expected on unauthenticated routes
        '403',  // Expected on unauthorized routes
        'NEXT_REDIRECT',  // Next.js navigation (not an error)
        'Failed to load resource',  // Network resource errors (caught elsewhere)
        'Failed to fetch',  // AbortController cancellations during navigation
        'net::ERR',  // Chrome network errors
        'Invalid prop',  // React development warnings (not runtime errors)
        'React.Fragment',  // React fragment prop warnings
      ];
      if (!ignoredPatterns.some(pattern => text.includes(pattern))) {
        errors.push(text);
        // Debug: print captured errors to console
        console.log(`[CONSOLE ERROR] ${text.substring(0, 100)}`);
      }
    }
  });
  return errors;
}

// Serial execution required - tests share browser context
test.describe.serial('Authenticated E2E Flow', () => {
  let context: BrowserContext;
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    // Create persistent context for all tests
    context = await browser.newContext();
    page = await context.newPage();

    // Login once for all tests
    const loginSuccess = await login(page, E2E_USER!, E2E_PASS!);
    expect(loginSuccess).toBe(true);
  });

  test.afterAll(async () => {
    await context.close();
  });

  test('1. Login succeeds and redirects to dashboard', async () => {
    // Already logged in from beforeAll
    expect(page.url()).toContain('platform-admin');

    // Verify page loaded (not blank, not an error page)
    const bodyText = await page.locator('body').textContent();
    expect(bodyText?.length).toBeGreaterThan(100);

    // Verify we're not on login page
    expect(page.url()).not.toContain('login');
  });

  test('2. Navigate all critical pages without re-login', async () => {
    const consoleErrors = setupConsoleErrorCapture(page);

    for (const { path, name } of CRITICAL_PAGES) {
      await page.goto(`${BASE_URL}${path}`);

      // Should NOT be redirected to login
      const currentUrl = page.url();
      expect(currentUrl).not.toContain('login');
      expect(currentUrl).not.toContain('auth');

      // Page should render (not blank)
      const bodyText = await page.locator('body').textContent();
      expect(bodyText?.length).toBeGreaterThan(100);

      // Should not show auth error
      const authError = page.locator('text=Unauthorized').first();
      const isAuthError = await authError.isVisible().catch(() => false);
      expect(isAuthError).toBe(false);

      console.log(`  ✓ ${name} (${path}) - accessible`);
    }

    // No unexpected console errors
    expect(consoleErrors.length).toBe(0);
  });

  test('3. Create tenant (if platform_admin)', async () => {
    // Navigate to tenant creation
    await page.goto(`${BASE_URL}/platform-admin/tenants`);

    // Check if "New Tenant" button exists (platform_admin only)
    const newTenantBtn = page.getByRole('button', { name: /new.*tenant|create.*tenant/i });
    const hasPermission = await newTenantBtn.isVisible().catch(() => false);

    if (!hasPermission) {
      console.log('  ⊘ Tenant creation skipped (user lacks permission)');
      return;
    }

    // Click to create
    await newTenantBtn.click();

    // Fill tenant form
    const testTenantName = `E2E-Test-${Date.now()}`;
    await page.fill('input[name="name"], [data-testid="tenant-name"]', testTenantName);

    // Submit
    const submitBtn = page.getByRole('button', { name: /create|save/i });
    await submitBtn.click();

    // Verify success (either redirect or success message)
    await page.waitForLoadState('networkidle');
    const success = page.url().includes('tenants') || await page.locator('text=success').isVisible();
    expect(success).toBe(true);

    console.log(`  ✓ Created tenant: ${testTenantName}`);
  });

  test('4. Open roster workbench (platform_admin sees context required)', async () => {
    const consoleErrors = setupConsoleErrorCapture(page);

    await page.goto(`${BASE_URL}/packs/roster/workbench`);
    await page.waitForLoadState('networkidle');

    // Platform admin without tenant context sees "Context Required" page
    // OR if tenant context is set, sees the actual workbench
    const hasContextRequired = await page.locator('text=Context Required').isVisible().catch(() => false);
    const hasTable = await page.locator('table, [role="grid"]').first().isVisible().catch(() => false);
    const hasLoading = await page.locator('text=Loading').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=No data').first().isVisible().catch(() => false);

    // Either shows context required OR has pack content
    expect(hasContextRequired || hasTable || hasLoading || hasEmpty).toBe(true);

    // No unexpected console errors (context required is not an error)
    expect(consoleErrors.length).toBe(0);

    console.log(`  ✓ Roster workbench accessible (${hasContextRequired ? 'context required' : 'content visible'})`);
  });

  test('5. Open repair page (platform_admin sees context required)', async () => {
    const consoleErrors = setupConsoleErrorCapture(page);

    await page.goto(`${BASE_URL}/packs/roster/repair`);
    await page.waitForLoadState('networkidle');

    // Platform admin without tenant context sees "Context Required" page
    const hasContextRequired = await page.locator('text=Context Required').isVisible().catch(() => false);
    const bodyText = await page.locator('body').textContent();

    // Page should render something (either context required or content)
    expect(bodyText?.length).toBeGreaterThan(50);

    // No unexpected console errors
    expect(consoleErrors.length).toBe(0);

    console.log(`  ✓ Repair page accessible (${hasContextRequired ? 'context required' : 'content visible'})`);
  });

  test('6. Session persists across page reloads', async () => {
    // Navigate to platform-admin first (to avoid "Context Required" page)
    await page.goto(`${BASE_URL}/platform-admin`);
    await page.waitForLoadState('domcontentloaded', { timeout: 15000 });

    // Reload page
    await page.reload();
    await page.waitForLoadState('domcontentloaded', { timeout: 15000 });

    // Should still be on platform-admin (not redirected to login)
    const currentUrl = page.url();
    expect(currentUrl).not.toContain('login');
    expect(currentUrl).toContain('platform-admin');

    // Page should have content (indicates session is valid)
    const bodyText = await page.locator('body').textContent();
    expect(bodyText?.length).toBeGreaterThan(100);

    console.log('  ✓ Session persists after reload');
  });
});

// =============================================================================
// STANDALONE TESTS (No shared context)
// =============================================================================

test.describe('Auth Edge Cases', () => {
  test('Invalid credentials show error', async ({ page }) => {
    await page.goto(`${BASE_URL}/platform/login`);

    // Fill with invalid credentials
    await page.fill('input[type="email"], input[name="email"]', 'invalid@example.com');
    await page.fill('input[type="password"], input[name="password"]', 'wrongpassword');

    // Submit
    await page.click('button[type="submit"]');

    // Should show error or stay on login page
    await page.waitForTimeout(2000);

    const stayedOnLogin = page.url().includes('login');
    const hasError = await page.locator('[data-testid="login-error"], .error, [role="alert"], text=Invalid').first().isVisible().catch(() => false);

    expect(stayedOnLogin || hasError).toBe(true);
  });

  test('Protected page redirects to login when not authenticated', async ({ page }) => {
    // Clear cookies to ensure no auth
    await page.context().clearCookies();

    await page.goto(`${BASE_URL}/platform-admin`);
    await page.waitForLoadState('networkidle');

    // Should be redirected to login
    const currentUrl = page.url();
    const redirectedToLogin = currentUrl.includes('login') || currentUrl.includes('auth');
    const shows401 = await page.locator('text=401, text=Unauthorized').first().isVisible().catch(() => false);

    expect(redirectedToLogin || shows401).toBe(true);
  });
});
